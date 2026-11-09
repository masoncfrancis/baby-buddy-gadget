import network
import urequests
import ujson
import time
import ntptime
import machine
import framebuf
from machine import Pin, I2C
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

ENABLE_CPU_UNDERCLOCK = False

WIFI_SSID = env.get("WIFI_SSID", "")
WIFI_PASSWORD = env.get("WIFI_PASSWORD", "")
BABY_BUDDY_BASE_URL = env.get("BABY_BUDDY_BASE_URL", "http://192.168.1.100:8000")
CHILD_SLUG = env.get("CHILD_SLUG", "")

try:
    TIMEZONE_OFFSET_MINUTES = int(env.get("TIMEZONE_OFFSET_MINUTES", "0"))
except ValueError:
    TIMEZONE_OFFSET_MINUTES = 0

# Safely convert integer fields from strings
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
ENC_DT_PIN = 17  # Physical Pin 22 (GP17)
ENC_SW_PIN = 18  # Physical Pin 24 (GP18)

# Top-Left (Pins 6-8): OLED Display (with GND on Pin 8, VCC on Pin 36)
OLED_SDA_PIN = 4  # Physical Pin 6 (GP4)
OLED_SCL_PIN = 5  # Physical Pin 7 (GP5)

# =========================================================================
# 3. FEEDING & UI SETTINGS
# =========================================================================
STEP_OZ = 0.25  # 0.25 oz per click of the knob
MIN_OZ = 0.25
MAX_OZ = 12.00
DEFAULT_OZ = 4.00
DEFAULT_DURATION_MIN = 10  # Logs feeding start as 10 mins prior to submit

DEBOUNCE_MS = 200
SLEEP_TIMEOUT_MS = 30000  # Screen turns off after 30 seconds of inactivity

FREQ_ACTIVE = 125_000_000
FREQ_IDLE = 24_000_000

FEED_TYPES = [
    {"label": "BREAST MILK", "api_value": "breast milk"},
    {"label": "FORMULA", "api_value": "formula"},
    {"label": "FORTIFIED", "api_value": "fortified breast milk"},
]

# =========================================================================
# 4. HARDWARE INITIALIZATION
# =========================================================================
led = Pin("LED", Pin.OUT)

i2c = I2C(0, sda=Pin(OLED_SDA_PIN), scl=Pin(OLED_SCL_PIN), freq=400000)
oled = SSD1306_I2C(128, 64, i2c)
oled.contrast(15)

clk_pin = Pin(ENC_CLK_PIN, Pin.IN, Pin.PULL_UP)
dt_pin = Pin(ENC_DT_PIN, Pin.IN, Pin.PULL_UP)
sw_pin = Pin(ENC_SW_PIN, Pin.IN, Pin.PULL_UP)

wlan = network.WLAN(network.STA_IF)
ntp_synced = False

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


# =========================================================================
# 5. GRAPHICAL UI HELPERS
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
    """Always shows 2 decimals (e.g. 4.00, 4.25) so numbers stay rock-steady."""
    return f"{val:.2f}"


def format_elapsed(last_epoch):
    """Returns a friendly elapsed string like '2h 14m ago' or 'Just now'."""
    if last_epoch is None:
        return "No logs yet"
    diff_min = max(0, int((time.time() - last_epoch) // 60))
    if diff_min < 1:
        return "Just now"
    elif diff_min < 60:
        return f"{diff_min}m ago"
    else:
        return f"{diff_min // 60}h {diff_min % 60}m ago"


def draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch):
    oled.poweron()
    oled.fill(0)

    # 1. Top Inverted Header Bar (Milk Type + PUSH hint)
    feed_label = FEED_TYPES[type_idx]["label"]
    oled.fill_rect(0, 0, 128, 12, 1)
    oled.text(feed_label, 3, 2, 0)
    oled.fill_rect(98, 1, 29, 10, 0)
    oled.text("PUSH", 101, 2, 1)

    # 2. Center Giant Ounces Readout
    oz_str = format_oz(amount_oz)
    if len(oz_str) <= 4:
        num_scale = 3
        unit_scale = 1
        unit_y = 33
    else:
        num_scale = 2
        unit_scale = 2
        unit_y = 22

    num_width = len(oz_str) * (8 * num_scale)
    unit_width = 2 * (8 * unit_scale)
    total_w = num_width + 2 + unit_width
    start_x = (128 - total_w) // 2

    if amount_oz > MIN_OZ:
        oled.text("<", 0, 26, 1)
    if amount_oz < MAX_OZ:
        oled.text(">", 120, 26, 1)

    draw_scaled_text(oz_str, start_x, 18, scale=num_scale, color=1)
    draw_scaled_text("oz", start_x + num_width + 2, unit_y, scale=unit_scale, color=1)

    # 3. Slim Progress / Fill Bar
    oled.rect(10, 46, 108, 4, 1)
    fill_ratio = (amount_oz - MIN_OZ) / (MAX_OZ - MIN_OZ)
    fill_w = int(104 * max(0.0, min(1.0, fill_ratio)))
    if fill_w > 0:
        oled.fill_rect(12, 47, fill_w, 2, 1)

    # 4. Bottom Footer (Last Feeding + Live Elapsed Time)
    oled.hline(0, 53, 128, 1)
    if last_epoch is None:
        oled.text("Last: None yet", 8, 56, 1)
    else:
        elapsed_str = format_elapsed(last_epoch)
        if last_parent:
            footer = f"{last_parent[0]}:{format_oz(last_oz)} {elapsed_str}"
        else:
            footer = f"Last:{format_oz(last_oz)} {elapsed_str}"
        oled.text(footer[:16], 2, 56, 1)

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


def format_clock(epoch_secs):
    t = time.localtime(epoch_secs + TIMEZONE_OFFSET_MINUTES * 60)
    return f"{t[3]:02d}:{t[4]:02d}"


def format_date(epoch_secs):
    t = time.localtime(epoch_secs + TIMEZONE_OFFSET_MINUTES * 60)
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"


def draw_start_menu(start_epoch):
    """Shows the feeding start-time selection step."""
    oled.poweron()
    oled.fill(0)
    oled.fill_rect(0, 0, 128, 13, 1)
    draw_centered_text("START TIME", 3, 0)
    draw_centered_text(format_date(start_epoch), 17)
    draw_centered_scaled_text(format_clock(start_epoch), 28, scale=2, color=1)
    draw_centered_text("TURN + PUSH", 55)
    oled.show()


def draw_summary(type_idx, amount_oz, start_epoch, selected_parent_key):
    """Shows feeding details before submission."""
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
        oled.fill_rect(16, 55, fill_w, 2, 1)

    oled.show()


def halt_on_error(title, big_line, sub_line):
    """Locks the device on an error screen so it will not proceed to the main screen."""
    print(f"FATAL CONFIG ERROR: {title} | {big_line} | {sub_line}")
    draw_modal(title, big_line, sub_line, progress=None)
    while True:
        led.toggle()
        time.sleep(0.3)


# =========================================================================
# 6. POWER MANAGEMENT, WIFI & STARTUP CONFIG CHECK
# =========================================================================
def disable_wifi():
    try:
        led.off()
        if wlan.isconnected():
            wlan.disconnect()
        wlan.active(False)
        wlan.deinit()
    except Exception:
        pass


def enter_sleep_mode():
    oled.poweroff()
    if ENABLE_CPU_UNDERCLOCK:
        disable_wifi()
        machine.freq(FREQ_IDLE)
    else:
        led.off()


def wake_from_sleep_mode():
    if ENABLE_CPU_UNDERCLOCK:
        machine.freq(FREQ_ACTIVE)
    oled.poweron()


def sync_clock():
    """Synchronizes Pico clock with NTP when Wi-Fi is available."""
    global ntp_synced
    if not wlan.isconnected():
        return False
    try:
        ntptime.settime()
        ntp_synced = True
        return True
    except Exception as e:
        print("NTP sync failed:", e)
        return False


def connect_wifi():
    """Connects to Wi-Fi without displaying any ounce numbers."""
    global ntp_synced
    if ENABLE_CPU_UNDERCLOCK:
        machine.freq(FREQ_ACTIVE)
    wlan.active(True)
    if wlan.isconnected():
        led.on()
        if not ntp_synced:
            sync_clock()
        return True

    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    timeout = 24
    step = 0
    while not wlan.isconnected() and timeout > 0:
        led.toggle()
        step += 1
        draw_modal(
            title="CONNECTING",
            big_line="WIFI...",
            sub_line=WIFI_SSID[:16],
            progress=(step / 12.0) % 1.0,
        )
        time.sleep(0.4)
        timeout -= 1

    if wlan.isconnected():
        led.on()
        if not ntp_synced:
            sync_clock()
        return True
    else:
        if ENABLE_CPU_UNDERCLOCK:
            disable_wifi()
        return False


def verify_startup_config():
    """
    Tests Wi-Fi, Server URL, Child ID, and both Parent API tokens on boot.
    If any check fails (400, 401, 403, 404, or unreachable), halts on error screen.
    """
    if not connect_wifi():
        halt_on_error("WIFI ERROR", "NO WIFI", "Check Config")

    draw_modal("STARTUP CHECK", "API...", "Checking config", progress=0.5)

    # Baby Buddy child detail endpoints use the child's slug, while feeding
    # payloads use the numeric child ID.
    if not CHILD_SLUG:
        halt_on_error("CONFIG ERROR", "NO CHILD SLUG", "Set CHILD_SLUG")
    url = f"{BABY_BUDDY_BASE_URL}/api/children/{CHILD_SLUG}/"

    for key, parent in PARENTS.items():
        headers = {
            "Authorization": f"Token {parent['api_token']}",
            "Accept": "application/json",
        }
        response = None
        try:
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
                response.close()

    draw_modal("STARTUP CHECK", "OK!", "Config Verified", progress=1.0)
    time.sleep(1.2)


def fetch_latest_feeding():
    """Returns latest feeding amount and epoch, or None if unavailable."""
    parent = PARENTS["parent_1"]
    url = (
        f"{BABY_BUDDY_BASE_URL}/api/feedings/"
        f"?child={CHILD_ID}&ordering=-end&limit=1"
    )
    headers = {
        "Authorization": f"Token {parent['api_token']}",
        "Accept": "application/json",
    }
    response = None
    try:
        response = urequests.get(url, headers=headers)
        if response.status_code != 200:
            print("Latest feeding lookup failed:", response.status_code)
            return None

        results = ujson.loads(response.text).get("results", [])
        if not results:
            return None

        feeding = results[0]
        end_text = feeding.get("end", "")
        # Ignore fractional seconds and timezone suffix; device clock is UTC.
        date_part, time_part = end_text[:19].split("T")
        date_values = [int(value) for value in date_part.split("-")]
        time_values = [int(value) for value in time_part.split(":")[:3]]
        epoch = time.mktime(tuple(date_values + time_values + [0, 0]))
        return float(feeding.get("amount", 0)), epoch
    except Exception as e:
        print("Latest feeding lookup error:", e)
        return None
    finally:
        if response:
            response.close()


def any_button_pressed():
    return sw_pin.value() == 0


def wait_for_all_released():
    while any_button_pressed():
        time.sleep_ms(20)
    time.sleep_ms(DEBOUNCE_MS)


# =========================================================================
# 7. API SUBMISSION
# =========================================================================
def format_iso_time(epoch_secs):
    # Baby Buddy expects UTC timestamps marked with Z.
    t = time.gmtime(epoch_secs)
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}T{t[3]:02d}:{t[4]:02d}:{t[5]:02d}Z"


def submit_bottle_feeding(parent_key, amount_oz, feed_type, start_epoch):
    parent = PARENTS[parent_key]

    if not connect_wifi():
        draw_modal("WIFI FAILED", "NO NET", "Check Router", progress=0.0)
        time.sleep(3)
        return False

    draw_modal(
        title=f"LOGGING ({parent['name'].upper()})",
        big_line=f"{format_oz(amount_oz)} oz",
        sub_line=feed_type["label"],
        progress=0.75,
    )

    end_epoch = time.time()
    # Never submit a start time in the future if submission is delayed.
    if start_epoch > end_epoch:
        start_epoch = end_epoch

    url = f"{BABY_BUDDY_BASE_URL}/api/feedings/"
    headers = {
        "Authorization": f"Token {parent['api_token']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
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
    try:
        response = urequests.post(url, headers=headers, data=ujson.dumps(payload))
        if response.status_code in (200, 201):
            draw_modal(
                title="FEEDING SAVED",
                big_line="SENT!",
                sub_line=f"{parent['name']} - {format_oz(amount_oz)} oz",
                progress=1.0,
            )
            success = True
            time.sleep(2.0)
        else:
            print("API Error:", response.status_code, response.text)
            # Halt on 400/error so you can see the failure rather than returning to main screen
            halt_on_error(
                "API ERROR", f"ERR {response.status_code}", "Check Tag/Config"
            )
    except Exception as e:
        print("Request Exception:", e)
        draw_modal("SERVER ERROR", "OFFLINE", "Cannot reach API")
        time.sleep(3)
    finally:
        if response:
            response.close()
        if ENABLE_CPU_UNDERCLOCK:
            disable_wifi()

    return success


# =========================================================================
# 8. MAIN LOOP
# =========================================================================
def main():
    global encoder_delta
    amount_oz = DEFAULT_OZ
    type_idx = 0
    start_epoch = 0
    selected_parent_key = "parent_1"
    wizard_state = "type"
    last_parent = ""
    last_oz = 0.0
    last_epoch = None
    screen_awake = True
    sw_pressed = False

    # Run startup verification (halts here if Wi-Fi, URL, Child ID, or Tokens fail)
    verify_startup_config()
    sync_clock()
    if ENABLE_CPU_UNDERCLOCK:
        disable_wifi()

    latest_feeding = fetch_latest_feeding()
    if latest_feeding:
        last_oz, last_epoch = latest_feeding
        draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
        time.sleep(3)

    draw_type_menu(type_idx)
    last_activity_ms = time.ticks_ms()
    last_footer_refresh_ms = time.ticks_ms()

    while True:
        now = time.ticks_ms()

        # 1. Turn off OLED after 30s of inactivity while idle
        if (
            wizard_state == "idle"
            and screen_awake
            and time.ticks_diff(now, last_activity_ms) >= SLEEP_TIMEOUT_MS
        ):
            enter_sleep_mode()
            screen_awake = False

        # 2. Asleep loop: wake on knob turn or encoder press without acting
        if not screen_awake:
            if encoder_delta != 0 or any_button_pressed():
                encoder_delta = 0
                wake_from_sleep_mode()
                connect_wifi()
                sync_clock()
                screen_awake = True
                draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
                last_activity_ms = time.ticks_ms()
            else:
                if ENABLE_CPU_UNDERCLOCK:
                    machine.lightsleep(50)
                else:
                    time.sleep_ms(50)
            continue

        # 3. Refresh the "Xm ago" footer every 15 seconds while awake
        if (
            wizard_state == "idle"
            and time.ticks_diff(now, last_footer_refresh_ms) >= 15000
        ):
            draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
            last_footer_refresh_ms = now

        # 4. Rotary Encoder Turning
        if encoder_delta != 0:
            steps = encoder_delta
            encoder_delta = 0
            if wizard_state == "type":
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
                # Accept either direction only when resulting timestamp is
                # not in the future. This lets clockwise catch up as time
                # advances, while still preventing future start times.
                candidate_epoch = start_epoch + steps * 15 * 60
                if candidate_epoch <= time.time():
                    start_epoch = candidate_epoch
                draw_start_menu(start_epoch)
            elif wizard_state == "parent":
                parent_keys = list(PARENTS.keys())
                parent_idx = parent_keys.index(selected_parent_key)
                parent_idx = (parent_idx + steps) % len(parent_keys)
                selected_parent_key = parent_keys[parent_idx]
                draw_parent_menu(selected_parent_key)
            last_activity_ms = time.ticks_ms()

        # 5. Encoder Push-Button
        sw_is_pressed = sw_pin.value() == 0
        if sw_is_pressed and not sw_pressed:
            sw_pressed = True

            # Process press immediately. Waiting for release caused the
            # menu to appear frozen on hardware with a noisy switch.
            if wizard_state == "idle":
                wizard_state = "type"
                draw_type_menu(type_idx)
            elif wizard_state == "type":
                wizard_state = "amount"
                draw_amount_menu(amount_oz)
            elif wizard_state == "amount":
                connect_wifi()
                sync_clock()
                start_epoch = time.time()
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
                    last_epoch = time.time()

                wizard_state = "type"
                draw_type_menu(type_idx)

            last_activity_ms = time.ticks_ms()
        elif not sw_is_pressed and sw_pressed:
            sw_pressed = False

        time.sleep_ms(20)


if __name__ == "__main__":
    main()
