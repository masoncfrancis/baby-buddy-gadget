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
# 1. NETWORK & BABY BUDDY CONFIGURATION
# =========================================================================
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
BABY_BUDDY_BASE_URL = "http://192.168.1.100:8000"  # No trailing slash
CHILD_ID = 1

# Set to False while running on USB power (keeps Thonny USB connection alive).
# Change to True once you run on battery power for multi-week battery life!
ENABLE_CPU_UNDERCLOCK = False

# =========================================================================
# 2. HARDWARE PINOUT (MATCHING YOUR CORNER WIRING TABLE)
# =========================================================================
# Bottom-Left (Pins 18-20): Parent 1 & Parent 2 Pushbuttons (sharing GND Pin 18)
PARENTS = {
    "parent_1": {
        "name": "Mason",
        "pin": 14,          # Physical Pin 19 (GP14)
        "api_token": "YOUR_PARENT_1_API_TOKEN",
        "tag": "fed-by-mason"
    },
    "parent_2": {
        "name": "Brenda",
        "pin": 15,          # Physical Pin 20 (GP15)
        "api_token": "YOUR_PARENT_2_API_TOKEN",
        "tag": "fed-by-brenda"
    }
}

# Bottom-Right (Pins 21-24): Rotary Encoder (with GND on Pin 23, + on Pin 36)
ENC_CLK_PIN = 16            # Physical Pin 21 (GP16)
ENC_DT_PIN  = 17            # Physical Pin 22 (GP17)
ENC_SW_PIN  = 18            # Physical Pin 24 (GP18)

# Top-Left (Pins 6-8): OLED Display (with GND on Pin 8, VCC on Pin 36)
OLED_SDA_PIN = 4            # Physical Pin 6 (GP4)
OLED_SCL_PIN = 5            # Physical Pin 7 (GP5)

# =========================================================================
# 3. FEEDING & UI SETTINGS
# =========================================================================
STEP_OZ = 0.25              # 0.25 oz per click of the knob
MIN_OZ  = 0.25
MAX_OZ  = 12.00
DEFAULT_OZ = 4.00
DEFAULT_DURATION_MIN = 10   # Logs feeding start as 10 mins prior to submit

DEBOUNCE_MS = 200
SLEEP_TIMEOUT_MS = 30000    # Screen turns off after 30 seconds of inactivity

FREQ_ACTIVE = 125_000_000
FREQ_IDLE   = 24_000_000

FEED_TYPES = [
    {"label": "BREAST MILK", "api_value": "breast milk"},
    {"label": "FORMULA",     "api_value": "formula"},
    {"label": "FORTIFIED",   "api_value": "fortified breast milk"},
]

# =========================================================================
# 4. HARDWARE INITIALIZATION
# =========================================================================
led = Pin("LED", Pin.OUT)

i2c = I2C(0, sda=Pin(OLED_SDA_PIN), scl=Pin(OLED_SCL_PIN), freq=400000)
oled = SSD1306_I2C(128, 64, i2c)
oled.contrast(15)

clk_pin = Pin(ENC_CLK_PIN, Pin.IN, Pin.PULL_UP)
dt_pin  = Pin(ENC_DT_PIN, Pin.IN, Pin.PULL_UP)
sw_pin  = Pin(ENC_SW_PIN, Pin.IN, Pin.PULL_UP)

parent_btns = {
    key: Pin(cfg["pin"], Pin.IN, Pin.PULL_UP)
    for key, cfg in PARENTS.items()
}

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
                    oled.fill_rect(x + col * scale, y + row * scale, scale, scale, color)
        x += 8 * scale


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
        # "4.25" at 3x (96px) + "oz" at 1x (16px) = 114px total
        num_scale = 3
        unit_scale = 1
        unit_y = 33
    else:
        # "10.25" at 2x (80px) + "oz" at 2x (32px) = 114px total
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
        footer = f"{last_parent[0]}:{format_oz(last_oz)} {elapsed_str}"
        oled.text(footer[:16], 2, 56, 1)

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


# =========================================================================
# 6. POWER MANAGEMENT & WIFI
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


def connect_wifi(parent_name="", amount_oz=0.0):
    global ntp_synced
    if ENABLE_CPU_UNDERCLOCK:
        machine.freq(FREQ_ACTIVE)
    wlan.active(True)
    if wlan.isconnected():
        led.on()
        return True

    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    timeout = 24
    step = 0
    while not wlan.isconnected() and timeout > 0:
        led.toggle()
        step += 1
        draw_modal(
            title="CONNECTING WIFI",
            big_line=f"{format_oz(amount_oz)} oz",
            sub_line=f"Parent: {parent_name}",
            progress=(step / 12.0) % 1.0
        )
        time.sleep(0.4)
        timeout -= 1

    if wlan.isconnected():
        led.on()
        if not ntp_synced:
            try:
                ntptime.settime()
                ntp_synced = True
            except Exception:
                pass
        return True
    else:
        if ENABLE_CPU_UNDERCLOCK:
            disable_wifi()
        return False


def any_button_pressed():
    if sw_pin.value() == 0:
        return True
    for btn in parent_btns.values():
        if btn.value() == 0:
            return True
    return False


def wait_for_all_released():
    while any_button_pressed():
        time.sleep_ms(20)
    time.sleep_ms(DEBOUNCE_MS)


# =========================================================================
# 7. API SUBMISSION
# =========================================================================
def format_iso_time(epoch_secs):
    t = time.localtime(epoch_secs)
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}T{t[3]:02d}:{t[4]:02d}:{t[5]:02d}Z"


def submit_bottle_feeding(parent_key, amount_oz, feed_type):
    parent = PARENTS[parent_key]

    if not connect_wifi(parent["name"], amount_oz):
        draw_modal("WIFI FAILED", "NO NET", "Check Router", progress=0.0)
        time.sleep(3)
        return False

    draw_modal(
        title=f"LOGGING ({parent['name'].upper()})",
        big_line=f"{format_oz(amount_oz)} oz",
        sub_line=feed_type["label"],
        progress=0.75
    )

    end_epoch = time.time()
    start_epoch = end_epoch - (DEFAULT_DURATION_MIN * 60)

    url = f"{BABY_BUDDY_BASE_URL}/api/feedings/"
    headers = {
        "Authorization": f"Token {parent['api_token']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "child": CHILD_ID,
        "start": format_iso_time(start_epoch),
        "end": format_iso_time(end_epoch),
        "type": feed_type["api_value"],
        "method": "bottle",
        "amount": amount_oz,
        "notes": f"Logged {format_oz(amount_oz)} oz via Pico by {parent['name']}",
        "tags": [parent["tag"]]
    }

    response = None
    success = False
    try:
        response = urequests.post(url, headers=headers, data=ujson.dumps(payload))
        if response.status_code in (200, 201):
            draw_modal(
                title="BABY BUDDY SAVED",
                big_line="SENT!",
                sub_line=f"{parent['name']} - {format_oz(amount_oz)} oz",
                progress=1.0
            )
            success = True
            time.sleep(2.0)
        else:
            print("API Error:", response.status_code, response.text)
            draw_modal("API ERROR", f"ERR {response.status_code}", "Check API Token")
            time.sleep(3)
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
    last_parent = ""
    last_oz = 0.0
    last_epoch = None
    screen_awake = True

    draw_modal("STARTING UP", "SYNC...", "Connecting WiFi", progress=0.4)
    connect_wifi("System", DEFAULT_OZ)
    if ENABLE_CPU_UNDERCLOCK:
        disable_wifi()

    draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
    last_activity_ms = time.ticks_ms()
    last_footer_refresh_ms = time.ticks_ms()

    while True:
        now = time.ticks_ms()

        # 1. Turn off OLED after 30s of inactivity
        if screen_awake and time.ticks_diff(now, last_activity_ms) >= SLEEP_TIMEOUT_MS:
            enter_sleep_mode()
            screen_awake = False

        # 2. Asleep loop: wake on knob turn or any button press without acting
        if not screen_awake:
            if encoder_delta != 0 or any_button_pressed():
                encoder_delta = 0
                wake_from_sleep_mode()
                screen_awake = True
                draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
                wait_for_all_released()
                last_activity_ms = time.ticks_ms()
            else:
                if ENABLE_CPU_UNDERCLOCK:
                    machine.lightsleep(50)
                else:
                    time.sleep_ms(50)
            continue

        # 3. Refresh the "Xm ago" footer every 15 seconds while awake
        if time.ticks_diff(now, last_footer_refresh_ms) >= 15000:
            draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
            last_footer_refresh_ms = now

        # 4. Rotary Encoder Turning (0.25 oz steps)
        if encoder_delta != 0:
            steps = encoder_delta
            encoder_delta = 0
            amount_oz = round((amount_oz + steps * STEP_OZ) * 4) / 4
            if amount_oz < MIN_OZ:
                amount_oz = MIN_OZ
            elif amount_oz > MAX_OZ:
                amount_oz = MAX_OZ

            draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
            last_activity_ms = time.ticks_ms()

        # 5. Encoder Push-Button (Cycle Milk Type)
        if sw_pin.value() == 0:
            type_idx = (type_idx + 1) % len(FEED_TYPES)
            draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
            wait_for_all_released()
            last_activity_ms = time.ticks_ms()

        # 6. Parent Submit Buttons
        for parent_key, btn in parent_btns.items():
            if btn.value() == 0:
                selected_type = FEED_TYPES[type_idx]
                success = submit_bottle_feeding(parent_key, amount_oz, selected_type)

                if success:
                    last_parent = PARENTS[parent_key]["name"]
                    last_oz = amount_oz
                    last_epoch = time.time()

                draw_dashboard(amount_oz, type_idx, last_parent, last_oz, last_epoch)
                wait_for_all_released()
                last_activity_ms = time.ticks_ms()

        time.sleep_ms(20)


if __name__ == "__main__":
    main()
