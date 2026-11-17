import network
import urequests
import ujson
import usocket
import time
import ntptime
import machine
import framebuf
import gc
from machine import Pin, I2C, ADC, WDT
from ssd1306 import SSD1306_I2C


# =========================================================================
# 1. LOAD CONFIGURATION FROM .ENV FILE
# =========================================================================
env = {}
try:
    with open(".env", "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                env[key.strip()] = val.strip()
except OSError:
    print("WARNING: .env file not found on board!")

ENABLE_CPU_UNDERCLOCK = True

WIFI_SSID = env.get("WIFI_SSID", "")
WIFI_PASSWORD = env.get("WIFI_PASSWORD", "")
BABY_BUDDY_BASE_URL = env.get("BABY_BUDDY_BASE_URL", "http://192.168.1.100:8000")
CHILD_SLUG = env.get("CHILD_SLUG", "")

try:
    TIMEZONE_OFFSET_MINUTES = int(env.get("TIMEZONE_OFFSET_MINUTES", "0"))
except ValueError:
    TIMEZONE_OFFSET_MINUTES = 0

try:
    CHILD_ID = int(env.get("CHILD_ID", "1"))
except ValueError:
    CHILD_ID = 1

# =========================================================================
# 2. HARDWARE PINOUT & PARENT CONFIGURATION
# =========================================================================
PARENTS = {
    "parent_1": {
        "name": env.get("PARENT_1_NAME", "Parent 1"),
        "api_token": env.get("PARENT_1_TOKEN", ""),
        "tag": env.get("PARENT_1_TAG", "fed-by-parent-1"),
    },
    "parent_2": {
        "name": env.get("PARENT_2_NAME", "Parent 2"),
        "api_token": env.get("PARENT_2_TOKEN", ""),
        "tag": env.get("PARENT_2_TAG", "fed-by-parent-2"),
    },
}

# Bottom-Right (Pins 21-24): Rotary Encoder (with GND on Pin 23, + on Pin 36)
ENC_CLK_PIN = 16  # Physical Pin 21 (GP16)
ENC_DT_PIN = 17   # Physical Pin 22 (GP17)
ENC_SW_PIN = 18   # Physical Pin 24 (GP18)

# Top-Left (Pins 6-8): OLED Display (with GND on Pin 8, VDD on Pin 36)
OLED_SDA_PIN = 4  # Physical Pin 6 (GP4)
OLED_SCL_PIN = 5  # Physical Pin 7 (GP5)

# =========================================================================
# 3. FEEDING & UI SETTINGS
# =========================================================================
STEP_OZ = 0.25
MIN_OZ = 0.25
MAX_OZ = 12.00
DEFAULT_OZ = 4.00

DEBOUNCE_MS = 180
LONG_PRESS_MS = 700              # Hold knob 0.7s: Refreshes on main screen, or Cancels in menu!
HARD_RESET_HOLD_TICKS = 28       # 28 * 250ms = 7.0s hold anywhere forces machine.reset()
SLEEP_TIMEOUT_MS = 20000         # Turn off OLED & sleep after 20s of inactivity
ERROR_SLEEP_TIMEOUT_MS = 60000   # Turn off OLED if stuck on error screen for 60s
SLEEP_BATT_CHECK_SEC = 1800      # Check battery voltage every 30 mins while asleep
LOW_BATT_CUTOFF_VOLTS = 3.22     # Enter protective hibernate at or below 3.22V
LOW_BATT_RECOVER_VOLTS = 3.50    # Exit hibernate once USB is plugged in or LiPo > 3.50V
MIN_VALID_EPOCH = 1735689600     # Jan 1, 2025 00:00:00 UTC (guards against 2021 unsynced RTC)

FREQ_ACTIVE = 125_000_000
FREQ_IDLE = 24_000_000

FEED_TYPES = [
    {"label": "BREAST MILK", "api_value": "breast milk"},
    {"label": "FORMULA", "api_value": "formula"},
    {"label": "FORTIFIED", "api_value": "fortified breast milk"},
]

MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# =========================================================================
# 4. HARDWARE INITIALIZATION & CRYSTAL-LOCKED CLOCK
# =========================================================================
i2c = I2C(0, sda=Pin(OLED_SDA_PIN), scl=Pin(OLED_SCL_PIN), freq=400000)
oled = SSD1306_I2C(128, 64, i2c)
oled.contrast(15)

clk_pin = Pin(ENC_CLK_PIN, Pin.IN, Pin.PULL_UP)
dt_pin = Pin(ENC_DT_PIN, Pin.IN, Pin.PULL_UP)
sw_pin = Pin(ENC_SW_PIN, Pin.IN, Pin.PULL_UP)

# Instantiate WLAN once globally and NEVER call wlan.deinit()!
wlan = network.WLAN(network.STA_IF)
wlan_is_active = False
cached_batt_label = "--%"
last_vsys_volts = 4.00

# --- HARDWARE CRYSTAL MONOTONIC CLOCK ---
_base_epoch = time.time()
_base_ticks_ms = time.ticks_ms()
_remainder_ms = 0


def set_accurate_epoch(utc_epoch):
    global _base_epoch, _base_ticks_ms, _remainder_ms
    _base_epoch = int(utc_epoch)
    _base_ticks_ms = time.ticks_ms()
    _remainder_ms = 0


def now_epoch():
    """Returns exact UTC epoch seconds immune to CPU frequency scaling & tick overflow."""
    global _base_epoch, _base_ticks_ms, _remainder_ms
    now_t = time.ticks_ms()
    diff_ms = time.ticks_diff(now_t, _base_ticks_ms)
    if diff_ms >= 1000:
        total_ms = diff_ms + _remainder_ms
        _base_epoch += total_ms // 1000
        _remainder_ms = total_ms % 1000
        _base_ticks_ms = now_t
    elif diff_ms < 0:
        _base_ticks_ms = now_t
    return _base_epoch


def is_clock_valid():
    """Returns True if the clock has been synced past Jan 1, 2025."""
    return now_epoch() > MIN_VALID_EPOCH


# --- ROTARY ENCODER INTERRUPT HANDLER ---
encoder_delta = 0
last_clk_state = clk_pin.value()
last_enc_irq_ms = 0


def rotary_isr(pin):
    global encoder_delta, last_clk_state, last_enc_irq_ms
    current_clk = clk_pin.value()
    now = time.ticks_ms()

    if current_clk != last_clk_state and current_clk == 0:
        if time.ticks_diff(now, last_enc_irq_ms) > 5:
            if dt_pin.value() != current_clk:
                encoder_delta += 1  # Clockwise
            else:
                encoder_delta -= 1  # Counter-clockwise
            last_enc_irq_ms = now
    last_clk_state = current_clk


clk_pin.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=rotary_isr)


# --- SILICON WATCHDOG + 7-SECOND HARD RESET MONITOR ---
# 1. If the CPU ever hard-locks in a C driver (interrupts disabled), the RP2040
#    hardware watchdog (WDT) automatically resets the silicon after 8.3 seconds!
# 2. If the user holds the knob for 7 seconds, _check_emergency_reset() forces
#    an immediate machine.reset().
_wdt = None
_reset_hold_ticks = 0


def feed_wdt():
    if _wdt is not None and _reset_hold_ticks < HARD_RESET_HOLD_TICKS:
        try:
            _wdt.feed()
        except Exception:
            pass


def _check_emergency_reset(timer):
    global _reset_hold_ticks
    if sw_pin.value() == 0:  # Button is pressed (Active-Low)
        _reset_hold_ticks += 1
        if _reset_hold_ticks >= HARD_RESET_HOLD_TICKS:  # 28 * 250ms = 7.0 seconds
            machine.reset()
    else:
        _reset_hold_ticks = 0
    feed_wdt()


_reset_timer = machine.Timer(-1)
_reset_timer.init(
    period=250, mode=machine.Timer.PERIODIC, callback=_check_emergency_reset
)


def update_battery_status():
    """
    Safely reads VSYS on Pico W WITHOUT needing wlan.deinit():
    1. Only runs when Wi-Fi is inactive.
    2. Briefly drives GP25 HIGH for 2ms to open the VSYS/3 FET gate, samples ADC(29),
       and IMMEDIATELY restores BOTH GP25 and GP29 to PIO1 (Pin.ALT, alt=7).
    """
    global cached_batt_label, last_vsys_volts
    if wlan_is_active:
        return cached_batt_label
    try:
        Pin(25, Pin.OUT, value=1)
        Pin(29, Pin.IN, pull=None)
        time.sleep_ms(2)

        adc = ADC(29)
        raw = sum(adc.read_u16() for _ in range(5)) / 5
        vsys = (raw * 3.3 / 65535) * 3.0

        if vsys > 1.8:
            last_vsys_volts = vsys
            if vsys > 4.45:
                cached_batt_label = "USB"
            else:
                pct = int(max(0, min(100, (vsys - 3.30) / (4.15 - 3.30) * 100)))
                cached_batt_label = f"{pct}%"
    except Exception as e:
        print("Battery ADC read error:", e)
    finally:
        # CRITICAL: Restore BOTH GP25 (CS) and GP29 (DIO) to PIO1 (alt=7)
        # so the CYW43 SPI bus never stalls or deadlocks!
        try:
            Pin(29, Pin.ALT, pull=Pin.PULL_DOWN, alt=7)
            Pin(25, Pin.ALT, pull=Pin.PULL_DOWN, alt=7)
        except Exception:
            pass
    return cached_batt_label


# =========================================================================
# 5. GRAPHICAL UI HELPERS & 12-HOUR AM/PM FORMATTERS
# =========================================================================
_char_buf = bytearray(8)
_char_fb = framebuf.FrameBuffer(_char_buf, 8, 8, framebuf.MONO_VLSB)


def draw_scaled_text(text, x, y, scale=2, color=1):
    """Renders crisp scaled-up text (2x = 16x16px, 3x = 24x24px per char)."""
    for char in text:
        _char_fb.fill(0)
        _char_fb.text(char, 0, 0, 1)
        for row in range(8):
            for col in range(8):
                if _char_fb.pixel(col, row):
                    oled.fill_rect(
                        x + col * scale, y + row * scale, scale, scale, color
                    )
        x += 8 * scale


def draw_centered_text(text, y, color=1):
    x = max(0, (128 - len(text) * 8) // 2)
    oled.text(text, x, y, color)


def draw_centered_scaled_text(text, y, scale=2, color=1):
    width = len(text) * 8 * scale
    x = max(0, (128 - width) // 2)
    draw_scaled_text(text, x, y, scale=scale, color=color)


def format_oz(val):
    return f"{val:.2f}"


def format_clock_parts(epoch_secs):
    """Returns ('H:MM', 'AM'/'PM') in 12-hour format."""
    t = time.localtime(epoch_secs + TIMEZONE_OFFSET_MINUTES * 60)
    hour24 = t[3]
    minute = t[4]
    ampm = "AM" if hour24 < 12 else "PM"
    hour12 = hour24 % 12
    if hour12 == 0:
        hour12 = 12
    return f"{hour12}:{minute:02d}", ampm


def format_clock(epoch_secs):
    """Returns compact 12-hour AM/PM string like '3:45PM' or '12:15AM'."""
    time_str, ampm = format_clock_parts(epoch_secs)
    return f"{time_str}{ampm}"


def format_date(epoch_secs):
    t = time.localtime(epoch_secs + TIMEZONE_OFFSET_MINUTES * 60)
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"


def format_elapsed(last_epoch):
    """Returns a compact elapsed string so '2h14m (12:45PM)' always fits in 16 chars."""
    if last_epoch is None:
        return "No logs yet"
    diff_min = max(0, int((now_epoch() - last_epoch) // 60))
    if diff_min < 1:
        return "Now"
    elif diff_min < 60:
        return f"{diff_min}m ago"
    else:
        return f"{diff_min // 60}h{diff_min % 60:02d}m"


def draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch):
    """Main Idle Screen: Always displays the latest feeding amount & 12-hour AM/PM time."""
    oled.poweron()
    oled.fill(0)

    # 1. Top Inverted Header Bar ("LAST FEEDING" + Live Battery Badge)
    oled.fill_rect(0, 0, 128, 12, 1)
    oled.text("LAST FEEDING", 3, 2, 0)

    badge_w = len(cached_batt_label) * 8 + 4
    badge_x = 127 - badge_w
    oled.fill_rect(badge_x, 1, badge_w, 10, 0)
    oled.text(cached_batt_label, badge_x + 2, 2, 1)

    if last_epoch is None:
        draw_centered_scaled_text("NONE", 22, scale=2, color=1)
        oled.hline(0, 52, 128, 1)
        draw_centered_text("PUSH TO LOG", 55, 1)
        oled.show()
        return

    # 2. Center Giant Ounces Readout of the LAST feeding
    oz_str = format_oz(last_oz)
    num_scale = 2
    num_width = len(oz_str) * (8 * num_scale)
    unit_width = 2 * 8
    total_w = num_width + 4 + unit_width
    start_x = (128 - total_w) // 2

    draw_scaled_text(oz_str, start_x, 16, scale=num_scale, color=1)
    oled.text("oz", start_x + num_width + 4, 24, 1)

    # 3. Elapsed Time + 12-Hour AM/PM Clock Time (Guaranteed to fit in 16 chars!)
    elapsed_str = format_elapsed(last_epoch)
    clock_str = format_clock(last_epoch)
    sub_line = f"{elapsed_str} ({clock_str})"
    if len(sub_line) > 16:
        diff_h = max(0, int((now_epoch() - last_epoch) // 3600))
        sub_line = f"{diff_h}h ago ({clock_str})"
    draw_centered_text(sub_line[:16], 38, 1)

    # 4. Bottom Footer Prompt
    oled.hline(0, 52, 128, 1)
    draw_centered_text("PUSH TO LOG NEW", 55, 1)

    oled.show()


def draw_parent_menu(selected_parent_key):
    """Shows the parent currently selected for the next feeding."""
    parent_keys = list(PARENTS.keys())
    selected_idx = parent_keys.index(selected_parent_key)

    oled.poweron()
    oled.fill(0)
    oled.fill_rect(0, 0, 128, 13, 1)
    draw_centered_text("SELECT PARENT", 3, 0)

    for idx, parent_key in enumerate(parent_keys):
        y = 22 + idx * 18
        marker = ">" if idx == selected_idx else " "
        oled.text(marker + PARENTS[parent_key]["name"][:14], 8, y, 1)

    draw_centered_text("TURN + PUSH", 55)
    oled.show()


def draw_type_menu(type_idx):
    """Shows the food type selection step."""
    oled.poweron()
    oled.fill(0)
    oled.fill_rect(0, 0, 128, 13, 1)
    draw_centered_text("FOOD TYPE", 3, 0)

    for idx, feed_type in enumerate(FEED_TYPES):
        y = 22 + idx * 12
        marker = ">" if idx == type_idx else " "
        oled.text(marker + feed_type["label"][:15], 4, y, 1)

    draw_centered_text("TURN + PUSH", 55)
    oled.show()


def draw_amount_menu(amount_oz):
    """Shows the amount selection step."""
    oled.poweron()
    oled.fill(0)
    oled.fill_rect(0, 0, 128, 13, 1)
    draw_centered_text("FOOD AMOUNT", 3, 0)
    draw_centered_scaled_text(format_oz(amount_oz), 20, scale=3, color=1)
    draw_centered_text("TURN + PUSH", 55)
    oled.show()


def draw_start_menu(start_epoch):
    """Shows the feeding start-time selection step in 12-hour AM/PM format."""
    oled.poweron()
    oled.fill(0)
    oled.fill_rect(0, 0, 128, 13, 1)
    draw_centered_text("START TIME", 3, 0)
    draw_centered_text(format_date(start_epoch), 16)

    time_str, ampm = format_clock_parts(start_epoch)
    num_w = len(time_str) * 16
    ampm_w = 2 * 8
    total_w = num_w + 4 + ampm_w
    start_x = max(0, (128 - total_w) // 2)

    draw_scaled_text(time_str, start_x, 28, scale=2, color=1)
    oled.text(ampm, start_x + num_w + 4, 36, 1)

    draw_centered_text("TURN + PUSH", 55)
    oled.show()


def draw_summary(type_idx, amount_oz, start_epoch, selected_parent_key):
    """Shows feeding details before submission (with 12-hour AM/PM time)."""
    oled.poweron()
    oled.fill(0)
    oled.fill_rect(0, 0, 128, 13, 1)
    draw_centered_text("CONFIRM FEED", 3, 0)
    draw_centered_text(FEED_TYPES[type_idx]["label"][:16], 19)
    draw_centered_text(format_oz(amount_oz) + "oz " + format_clock(start_epoch), 31)
    draw_centered_text(PARENTS[selected_parent_key]["name"][:16], 43)
    draw_centered_text("PUSH TO SEND", 55)
    oled.show()


def draw_modal(title, big_line, sub_line="", progress=None):
    oled.poweron()
    oled.fill(0)
    oled.rect(0, 0, 128, 64, 1)
    oled.fill_rect(0, 0, 128, 13, 1)

    title_x = max(2, (128 - len(title) * 8) // 2)
    oled.text(title, title_x, 3, 0)

    big_x = max(4, (128 - len(big_line) * 16) // 2)
    draw_scaled_text(big_line, big_x, 20, scale=2, color=1)

    sub_x = max(4, (128 - len(sub_line) * 8) // 2)
    oled.text(sub_line, sub_x, 42, 1)

    if progress is not None:
        oled.rect(14, 53, 100, 6, 1)
        fill_w = int(96 * max(0.0, min(1.0, progress)))
        if fill_w > 0:
            oled.fill_rect(16, 55, fill_w, 2, 1)

    oled.show()


def halt_on_error(title, big_line, sub_line):
    global encoder_delta
    print(f"FATAL CONFIG ERROR: {title} | {big_line} | {sub_line}")
    if ENABLE_CPU_UNDERCLOCK:
        disable_wifi()
    draw_modal(title, big_line, sub_line, progress=None)

    start_ms = time.ticks_ms()
    screen_on = True
    while True:
        now_epoch()
        feed_wdt()
        if screen_on and time.ticks_diff(time.ticks_ms(), start_ms) > ERROR_SLEEP_TIMEOUT_MS:
            oled.poweroff()
            if ENABLE_CPU_UNDERCLOCK:
                machine.freq(FREQ_IDLE)
            screen_on = False

        if not screen_on:
            if any_button_pressed() or encoder_delta != 0:
                encoder_delta = 0
                if ENABLE_CPU_UNDERCLOCK:
                    machine.freq(FREQ_ACTIVE)
                draw_modal(title, big_line, sub_line, progress=None)
                wait_for_all_released()
                start_ms = time.ticks_ms()
                screen_on = True
            else:
                time.sleep_ms(100)
        else:
            time.sleep_ms(300)


# =========================================================================
# 6. POWER MANAGEMENT, LOW-BATTERY CUTOFF & WIFI
# =========================================================================
def disable_wifi():
    """
    Safely puts Wi-Fi radio to sleep WITHOUT calling wlan.deinit()!
    Calling wlan.deinit() right after closing a TCP socket deadlocks the RP2040
    CYW43 driver with interrupts disabled.
    """
    global wlan_is_active
    try:
        if wlan.isconnected():
            wlan.disconnect()
        wlan.active(False)
    except Exception as e:
        print("Wi-Fi disable error:", e)
    wlan_is_active = False
    time.sleep_ms(50)  # Let lwIP & CYW43 finish background socket cleanup
    update_battery_status()
    gc.collect()


def enter_low_battery_cutoff(show_warning=True):
    """
    Protects the LiPo battery & RP2040 flash from brownout if VSYS <= 3.22V:
    - Turns off Wi-Fi and OLED, drops CPU to 24MHz, and blocks Wi-Fi current spikes.
    - If user presses button/knob while low, flashes 'LOW BATTERY / CHARGE!' for 2s.
    - Automatically wakes back up as soon as USB power is connected (VSYS > 3.50V)!
    """
    global encoder_delta
    disable_wifi()

    if show_warning:
        if ENABLE_CPU_UNDERCLOCK:
            machine.freq(FREQ_ACTIVE)
        draw_modal("LOW BATTERY", "CHARGE!", "Plug in USB", progress=0.0)
        time.sleep_ms(2200)

    oled.poweroff()
    if ENABLE_CPU_UNDERCLOCK:
        machine.freq(FREQ_IDLE)

    encoder_delta = 0
    last_check_ms = time.ticks_ms()

    while True:
        now_epoch()
        feed_wdt()
        now = time.ticks_ms()

        # Check every 2 seconds if USB cable was plugged in
        if time.ticks_diff(now, last_check_ms) >= 2000:
            last_check_ms = now
            update_battery_status()
            if last_vsys_volts >= LOW_BATT_RECOVER_VOLTS:
                if ENABLE_CPU_UNDERCLOCK:
                    machine.freq(FREQ_ACTIVE)
                oled.poweron()
                encoder_delta = 0
                return

        # If user touches knob/button while battery is still dead, flash brief warning
        if encoder_delta != 0 or any_button_pressed():
            encoder_delta = 0
            update_battery_status()
            if last_vsys_volts >= LOW_BATT_RECOVER_VOLTS:
                if ENABLE_CPU_UNDERCLOCK:
                    machine.freq(FREQ_ACTIVE)
                oled.poweron()
                return
            if ENABLE_CPU_UNDERCLOCK:
                machine.freq(FREQ_ACTIVE)
            draw_modal("LOW BATTERY", "CHARGE!", "Plug in USB", progress=0.0)
            wait_for_all_released()
            time.sleep_ms(1500)
            oled.poweroff()
            if ENABLE_CPU_UNDERCLOCK:
                machine.freq(FREQ_IDLE)
            encoder_delta = 0

        time.sleep_ms(100)


def enter_sleep_mode():
    now_epoch()
    oled.poweroff()
    if ENABLE_CPU_UNDERCLOCK:
        disable_wifi()
        machine.freq(FREQ_IDLE)
    if last_vsys_volts <= LOW_BATT_CUTOFF_VOLTS:
        enter_low_battery_cutoff(show_warning=False)


def wake_from_sleep_mode():
    if ENABLE_CPU_UNDERCLOCK:
        machine.freq(FREQ_ACTIVE)
    now_epoch()
    update_battery_status()
    if last_vsys_volts <= LOW_BATT_CUTOFF_VOLTS:
        enter_low_battery_cutoff(show_warning=True)
    oled.poweron()


def sync_clock_from_baby_buddy():
    """
    Fallback clock sync if internet/NTP is down:
    Reads the HTTP 'Date: Sun, 15 Nov 2026 05:45:12 GMT' header directly
    from the local Baby Buddy server over LAN!
    """
    s = None
    gc.collect()
    try:
        clean_url = BABY_BUDDY_BASE_URL.split("://")[-1].split("/")[0]
        if ":" in clean_url:
            host, port_str = clean_url.split(":", 1)
            port = int(port_str)
        else:
            host = clean_url
            port = 80

        addr = usocket.getaddrinfo(host, port)[0][-1]
        s = usocket.socket()
        s.settimeout(2)
        s.connect(addr)
        req = f"HEAD /api/ HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        s.send(req.encode())

        while True:
            line = s.readline()
            if not line or line == b"\r\n":
                break
            if line.lower().startswith(b"date:"):
                parts = line.decode().strip().split()
                if len(parts) >= 6:
                    day = int(parts[2])
                    month = MONTH_MAP.get(parts[3], 1)
                    year = int(parts[4])
                    hms = [int(x) for x in parts[5].split(":")]
                    utc_epoch = time.mktime(
                        (year, month, day, hms[0], hms[1], hms[2], 0, 0)
                    )
                    if utc_epoch > MIN_VALID_EPOCH:
                        set_accurate_epoch(utc_epoch)
                        print("Synced clock from local Baby Buddy HTTP Date header!")
                        return True
    except Exception as e:
        print("Local HTTP Date sync failed:", e)
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass
        gc.collect()
    return False


def sync_clock():
    """
    1. Tries public NTP (pool.ntp.org) with a strict 2-second timeout.
    2. If ISP/DNS is down, falls back to reading the HTTP Date header
       directly from the local Baby Buddy server on your LAN!
    """
    if not wlan.isconnected():
        return False

    ntptime.host = "pool.ntp.org"
    ntptime.timeout = 2
    for _ in range(2):
        try:
            gc.collect()
            feed_wdt()
            ntptime.settime()
            if time.time() > MIN_VALID_EPOCH:
                set_accurate_epoch(time.time())
                return True
        except Exception as e:
            print("NTP sync attempt failed:", e)
            time.sleep_ms(200)

    if sync_clock_from_baby_buddy():
        return True

    return is_clock_valid()


def connect_wifi(sync_ntp=True):
    """
    Ensures GP25 & GP29 are restored to PIO1 (alt=7) BEFORE waking the CYW43 chip
    and reuses the global wlan instance without ever calling wlan.deinit()!
    """
    global wlan_is_active
    if ENABLE_CPU_UNDERCLOCK:
        machine.freq(FREQ_ACTIVE)

    wlan_is_active = True
    try:
        Pin(29, Pin.ALT, pull=Pin.PULL_DOWN, alt=7)
        Pin(25, Pin.ALT, pull=Pin.PULL_DOWN, alt=7)
    except Exception:
        pass

    gc.collect()
    feed_wdt()
    if not wlan.active():
        wlan.active(True)
        time.sleep_ms(80)
    try:
        pm_perf = getattr(network.WLAN, "PM_PERFORMANCE", 0xA11140)
        wlan.config(pm=pm_perf)
    except Exception:
        pass

    if wlan.isconnected():
        if sync_ntp:
            sync_clock()
        return True

    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    timeout = 24
    step = 0
    while not wlan.isconnected() and timeout > 0:
        now_epoch()
        feed_wdt()
        step += 1
        draw_modal(
            title="CONNECTING",
            big_line="WIFI...",
            sub_line=WIFI_SSID[:16],
            progress=(step / 12.0) % 1.0,
        )
        time.sleep_ms(400)
        timeout -= 1

    if wlan.isconnected():
        if sync_ntp:
            sync_clock()
        return True
    else:
        if ENABLE_CPU_UNDERCLOCK:
            disable_wifi()
        else:
            wlan_is_active = False
        return False


def parse_iso_to_utc_epoch(iso_str):
    date_part, rest = iso_str.split("T")
    time_part = rest[:8]

    tz_offset_sec = 0
    tz_part = rest[8:]
    if "." in tz_part:
        for i, ch in enumerate(tz_part):
            if ch in ("+", "-", "Z"):
                tz_part = tz_part[i:]
                break

    if tz_part.startswith("+") or tz_part.startswith("-"):
        sign = 1 if tz_part[0] == "+" else -1
        tz_clean = tz_part[1:].replace(":", "")
        if len(tz_clean) >= 4:
            tz_h = int(tz_clean[:2])
            tz_m = int(tz_clean[2:4])
            tz_offset_sec = sign * (tz_h * 3600 + tz_m * 60)

    date_values = [int(v) for v in date_part.split("-")]
    time_values = [int(v) for v in time_part.split(":")]
    raw_epoch = time.mktime(tuple(date_values + time_values + [0, 0]))
    return raw_epoch - tz_offset_sec


def fetch_latest_feeding():
    """Returns latest feeding (amount_oz, utc_epoch, parent_name) with a 5s socket timeout."""
    parent = PARENTS["parent_1"]
    url = (
        f"{BABY_BUDDY_BASE_URL}/api/feedings/"
        f"?child={CHILD_ID}&ordering=-end&limit=1"
    )
    headers = {
        "Authorization": f"Token {parent['api_token']}",
        "Accept": "application/json",
        "Connection": "close",
    }
    response = None
    gc.collect()
    feed_wdt()
    try:
        try:
            response = urequests.get(url, headers=headers, timeout=5)
        except TypeError:
            response = urequests.get(url, headers=headers)

        if response.status_code != 200:
            print("Latest feeding lookup failed:", response.status_code)
            return None

        results = ujson.loads(response.text).get("results", [])
        if not results:
            return None

        feeding = results[0]
        end_text = feeding.get("end", "")
        epoch = parse_iso_to_utc_epoch(end_text)

        matched_parent = ""
        feed_tags = feeding.get("tags", [])
        if isinstance(feed_tags, list):
            for p_info in PARENTS.values():
                if p_info["tag"] in feed_tags:
                    matched_parent = p_info["name"]
                    break

        return float(feeding.get("amount", 0)), epoch, matched_parent
    except Exception as e:
        print("Latest feeding lookup error:", e)
        return None
    finally:
        if response:
            try:
                response.close()
            except Exception:
                pass
        gc.collect()


def refresh_from_server(last_parent, last_oz, last_epoch, show_toast=True):
    """
    Manually triggered ONLY when holding the button on the main screen:
    connects to Wi-Fi, syncs NTP (or local HTTP Date fallback), fetches the
    latest feeding from Baby Buddy, and powers Wi-Fi back down.
    """
    global wlan_is_active
    draw_modal("REFRESHING", "LATEST...", "Connecting Wi-Fi", progress=0.25)

    if connect_wifi(sync_ntp=True):
        draw_modal("REFRESHING", "FETCHING", "Baby Buddy API", progress=0.75)
        latest = fetch_latest_feeding()

        if ENABLE_CPU_UNDERCLOCK:
            disable_wifi()
        else:
            wlan_is_active = False
            update_battery_status()

        if latest:
            last_oz, last_epoch, fetched_parent = latest
            if fetched_parent:
                last_parent = fetched_parent
            if show_toast:
                draw_modal(
                    "REFRESHED",
                    "UPDATED!",
                    f"{format_oz(last_oz)}oz ({format_clock(last_epoch)})",
                    progress=1.0,
                )
                time.sleep_ms(800)
        else:
            if show_toast:
                draw_modal("REFRESHED", "NO UPDATE", "Keep cached feed", progress=1.0)
                time.sleep_ms(800)
    else:
        draw_modal("WIFI FAILED", "NO NET", "Keep cached feed", progress=None)
        time.sleep_ms(1200)
        update_battery_status()

    return last_parent, last_oz, last_epoch


def verify_startup_config():
    if not connect_wifi(sync_ntp=True):
        halt_on_error("WIFI ERROR", "NO WIFI", "Check Config")

    draw_modal("STARTUP CHECK", "API...", "Checking config", progress=0.5)

    if not CHILD_SLUG:
        halt_on_error("CONFIG ERROR", "NO CHILD SLUG", "Set CHILD_SLUG")
    url = f"{BABY_BUDDY_BASE_URL}/api/children/{CHILD_SLUG}/"

    for key, parent in PARENTS.items():
        headers = {
            "Authorization": f"Token {parent['api_token']}",
            "Accept": "application/json",
            "Connection": "close",
        }
        response = None
        gc.collect()
        feed_wdt()
        try:
            try:
                response = urequests.get(url, headers=headers, timeout=5)
            except TypeError:
                response = urequests.get(url, headers=headers)
            status = response.status_code
            if status != 200:
                print(
                    f"Config Error for {parent['name']} (HTTP {status}):", response.text
                )
                if status in (401, 403):
                    halt_on_error(
                        "CONFIG ERROR",
                        f"HTTP {status}",
                        f"Bad Token:{parent['name'][:6]}",
                    )
                elif status == 404:
                    halt_on_error(
                        "CONFIG ERROR", "HTTP 404", f"Bad Child ID:{CHILD_ID}"
                    )
                else:
                    halt_on_error("CONFIG ERROR", f"HTTP {status}", "Check Config")
        except Exception as e:
            print("Startup API connection failed:", e)
            halt_on_error("CONFIG ERROR", "UNREACH", "Check Base URL")
        finally:
            if response:
                try:
                    response.close()
                except Exception:
                    pass
            gc.collect()

    # Ensure clock is synced (either via NTP or local Baby Buddy HTTP Date header)
    if not is_clock_valid():
        sync_clock_from_baby_buddy()
    if not is_clock_valid():
        halt_on_error("TIME ERROR", "NO CLOCK", "Check NTP/Server")

    draw_modal("STARTUP CHECK", "OK!", "Config Verified", progress=1.0)
    time.sleep_ms(1000)


def any_button_pressed():
    return sw_pin.value() == 0


def wait_for_all_released():
    """Waits for button release with a 2.5s safety timeout so a stuck pin never freezes the UI."""
    start_wait = time.ticks_ms()
    while any_button_pressed():
        now_epoch()
        feed_wdt()
        if time.ticks_diff(time.ticks_ms(), start_wait) > 2500:
            break
        time.sleep_ms(20)
    time.sleep_ms(DEBOUNCE_MS)


# =========================================================================
# 7. API SUBMISSION
# =========================================================================
def format_iso_time(epoch_secs):
    t = time.gmtime(epoch_secs)
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}T{t[3]:02d}:{t[4]:02d}:{t[5]:02d}Z"


def submit_bottle_feeding(parent_key, amount_oz, feed_type, start_epoch):
    parent = PARENTS[parent_key]

    if not connect_wifi(sync_ntp=True):
        draw_modal("WIFI FAILED", "NO NET", "Check Router", progress=0.0)
        time.sleep_ms(2500)
        return False

    draw_modal(
        title=f"LOGGING ({parent['name'].upper()})",
        big_line=f"{format_oz(amount_oz)} oz",
        sub_line=feed_type["label"],
        progress=0.75,
    )

    end_epoch = now_epoch()
    # Never submit a start time in the future if submission is delayed.
    if start_epoch > end_epoch:
        start_epoch = end_epoch

    url = f"{BABY_BUDDY_BASE_URL}/api/feedings/"
    headers = {
        "Authorization": f"Token {parent['api_token']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
    }
    payload = {
        "child": CHILD_ID,
        "start": format_iso_time(start_epoch),
        "end": format_iso_time(end_epoch),
        "type": feed_type["api_value"],
        "method": "bottle",
        "amount": amount_oz,
        "notes": f"Logged {format_oz(amount_oz)} oz via Pico by {parent['name']}",
        "tags": [parent["tag"]],
    }

    response = None
    success = False
    status_code = 0
    err_text = ""
    gc.collect()
    feed_wdt()
    try:
        body = ujson.dumps(payload)
        try:
            response = urequests.post(url, headers=headers, data=body, timeout=6)
        except TypeError:
            response = urequests.post(url, headers=headers, data=body)

        status_code = response.status_code
        if status_code in (200, 201):
            success = True
        else:
            err_text = response.text
    except Exception as e:
        print("Request Exception:", e)
        status_code = -1
    finally:
        # 1. Close socket FIRST while Wi-Fi is still active
        if response:
            try:
                response.close()
            except Exception:
                pass
        gc.collect()

    # 2. Power down Wi-Fi cleanly (without wlan.deinit()) BEFORE drawing final modal
    if ENABLE_CPU_UNDERCLOCK:
        disable_wifi()

    # 3. Show result modal after Wi-Fi is safely asleep
    if success:
        draw_modal(
            title="FEEDING SAVED",
            big_line="SENT!",
            sub_line=f"{parent['name']} - {format_oz(amount_oz)} oz",
            progress=1.0,
        )
        time.sleep_ms(1500)
    elif status_code == -1:
        draw_modal("SERVER ERROR", "OFFLINE", "Cannot reach API")
        time.sleep_ms(2500)
    else:
        print("API Error:", status_code, err_text)
        halt_on_error("API ERROR", f"ERR {status_code}", "Check Tag/Config")

    return success


# =========================================================================
# 8. MAIN LOOP
# =========================================================================
def main():
    global encoder_delta, wlan_is_active, _wdt
    amount_oz = DEFAULT_OZ
    type_idx = 0
    start_epoch = 0
    selected_parent_key = "parent_1"
    wizard_state = "idle"
    last_parent = ""
    last_oz = 0.0
    last_epoch = None
    screen_awake = True

    sw_pressed = False
    sw_press_start_ms = 0
    sw_long_handled = False

    # Enable RP2040 Silicon Watchdog (8.3s timeout) so even a hard C-level
    # interrupt lockup automatically resets the board!
    _wdt = WDT(timeout=8300)

    # 1. Verify config & sync NTP (or local Baby Buddy HTTP Date) on boot
    verify_startup_config()

    # 2. Fetch latest feeding BEFORE disabling Wi-Fi
    latest_feeding = fetch_latest_feeding()
    if latest_feeding:
        last_oz, last_epoch, fetched_parent = latest_feeding
        if fetched_parent:
            last_parent = fetched_parent

    # 3. Power down Wi-Fi & sample battery voltage while radio is quiet
    if ENABLE_CPU_UNDERCLOCK:
        disable_wifi()
    else:
        wlan_is_active = False
        update_battery_status()

    # Start on the idle dashboard (shows latest feeding & battery %)
    draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
    last_activity_ms = time.ticks_ms()
    last_footer_refresh_ms = time.ticks_ms()
    last_sleep_batt_check_epoch = now_epoch()

    while True:
        now = time.ticks_ms()
        cur_epoch = now_epoch()
        feed_wdt()

        # 1. Sleep after 20s of inactivity on ANY screen (prevents battery drain)
        if screen_awake and time.ticks_diff(now, last_activity_ms) >= SLEEP_TIMEOUT_MS:
            enter_sleep_mode()
            screen_awake = False
            wizard_state = "idle"
            sw_pressed = False
            sw_long_handled = False
            last_sleep_batt_check_epoch = now_epoch()

        # 2. Asleep loop: wake INSTANTLY using the crystal-locked clock
        if not screen_awake:
            if encoder_delta != 0 or any_button_pressed():
                encoder_delta = 0
                wake_from_sleep_mode()
                screen_awake = True
                wizard_state = "idle"
                draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
                wait_for_all_released()
                encoder_delta = 0
                sw_pressed = False
                sw_long_handled = False
                last_activity_ms = time.ticks_ms()
                last_footer_refresh_ms = time.ticks_ms()
            else:
                if (cur_epoch - last_sleep_batt_check_epoch) >= SLEEP_BATT_CHECK_SEC:
                    last_sleep_batt_check_epoch = cur_epoch
                    update_battery_status()
                    if last_vsys_volts <= LOW_BATT_CUTOFF_VOLTS:
                        enter_low_battery_cutoff(show_warning=False)
                time.sleep_ms(100)
            continue

        # 3. Refresh the "Xm ago" footer & battery % every 15 seconds while idle
        if (
            wizard_state == "idle"
            and time.ticks_diff(now, last_footer_refresh_ms) >= 15000
        ):
            update_battery_status()
            if last_vsys_volts <= LOW_BATT_CUTOFF_VOLTS:
                enter_low_battery_cutoff(show_warning=True)
                draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
                last_activity_ms = time.ticks_ms()
            else:
                draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
            last_footer_refresh_ms = time.ticks_ms()

        # 4. Rotary Encoder Turning
        if encoder_delta != 0:
            steps = encoder_delta
            encoder_delta = 0
            if wizard_state == "idle":
                wizard_state = "type"
                draw_type_menu(type_idx)
            elif wizard_state == "type":
                type_idx = (type_idx + steps) % len(FEED_TYPES)
                draw_type_menu(type_idx)
            elif wizard_state == "amount":
                amount_oz = round((amount_oz + steps * STEP_OZ) * 4) / 4
                if amount_oz < MIN_OZ:
                    amount_oz = MIN_OZ
                elif amount_oz > MAX_OZ:
                    amount_oz = MAX_OZ
                draw_amount_menu(amount_oz)
            elif wizard_state == "start":
                candidate_epoch = start_epoch + steps * 15 * 60
                if candidate_epoch <= now_epoch():
                    start_epoch = candidate_epoch
                draw_start_menu(start_epoch)
            elif wizard_state == "parent":
                parent_keys = list(PARENTS.keys())
                parent_idx = parent_keys.index(selected_parent_key)
                parent_idx = (parent_idx + steps) % len(parent_keys)
                selected_parent_key = parent_keys[parent_idx]
                draw_parent_menu(selected_parent_key)
            last_activity_ms = time.ticks_ms()

        # 5. Encoder Push-Button (Short Click = Advance, Long Hold = Refresh on Main / Cancel in Menu)
        sw_is_pressed = sw_pin.value() == 0

        if sw_is_pressed:
            if not sw_pressed:
                sw_pressed = True
                sw_press_start_ms = now
                sw_long_handled = False
                last_activity_ms = now
            elif not sw_long_handled and time.ticks_diff(now, sw_press_start_ms) >= LONG_PRESS_MS:
                sw_long_handled = True
                if wizard_state != "idle":
                    draw_modal("CANCELLED", "EXIT", "Back to main", progress=None)
                    time.sleep_ms(600)
                else:
                    last_parent, last_oz, last_epoch = refresh_from_server(
                        last_parent, last_oz, last_epoch, show_toast=True
                    )
                wizard_state = "idle"
                draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
                wait_for_all_released()
                encoder_delta = 0
                sw_pressed = False
                sw_long_handled = False
                last_activity_ms = time.ticks_ms()
                last_footer_refresh_ms = time.ticks_ms()

        elif not sw_is_pressed and sw_pressed:
            hold_ms = time.ticks_diff(now, sw_press_start_ms)
            sw_pressed = False

            if not sw_long_handled and hold_ms >= 30:  # 30ms glitch filter
                if wizard_state == "idle":
                    wizard_state = "type"
                    draw_type_menu(type_idx)
                elif wizard_state == "type":
                    wizard_state = "amount"
                    draw_amount_menu(amount_oz)
                elif wizard_state == "amount":
                    start_epoch = now_epoch()
                    local_epoch = start_epoch + TIMEZONE_OFFSET_MINUTES * 60
                    start_time = time.localtime(local_epoch)
                    local_epoch -= (start_time[4] % 15) * 60 + start_time[5]
                    start_epoch = local_epoch - TIMEZONE_OFFSET_MINUTES * 60
                    wizard_state = "start"
                    draw_start_menu(start_epoch)
                elif wizard_state == "start":
                    wizard_state = "parent"
                    draw_parent_menu(selected_parent_key)
                elif wizard_state == "parent":
                    wizard_state = "confirm"
                    draw_summary(type_idx, amount_oz, start_epoch, selected_parent_key)
                elif wizard_state == "confirm":
                    selected_type = FEED_TYPES[type_idx]
                    success = submit_bottle_feeding(
                        selected_parent_key, amount_oz, selected_type, start_epoch
                    )

                    if success:
                        last_parent = PARENTS[selected_parent_key]["name"]
                        last_oz = amount_oz
                        last_epoch = now_epoch()

                    wizard_state = "idle"
                    draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)

                last_activity_ms = time.ticks_ms()

        time.sleep_ms(20)


if __name__ == "__main__":
    main()
    