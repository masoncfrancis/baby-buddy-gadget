# Baby Buddy Pico W — Handoff

## Source of truth

`main.py`, `app_config.py`, `http_client.py`, and `ssd1306.py` are firmware source. This document records intent, hardware facts, and empirically observed constraints; it is not a copy of production code.

## Device and wiring

Raspberry Pi Pico W, MicroPython, SSD1306 128x64 I2C display, and KY-040-style encoder.

| Function | GPIO | Physical pin |
| --- | ---: | ---: |
| OLED SDA | GP4 | 6 |
| OLED SCL | GP5 | 7 |
| OLED GND | GND | 8 |
| OLED and encoder VCC | 3V3(OUT) | 36 |
| Encoder CLK | GP16 | 21 |
| Encoder DT | GP17 | 22 |
| Encoder GND | GND | 23 |
| Encoder switch | GP18 | 24 |
| VSYS sense | GP29 / ADC3 | Internal |

`schematic.md` is the detailed wiring reference. Confirm any hardware edits against the Pico W board revision and official schematic before assembly.

## GP29 / CYW43 notes

The Pico W datasheet identifies GP29 as shared wireless SPI **clock / ADC3**, used to measure VSYS/3. GP25 is wireless SPI chip select; its high state also enables the GP29 ADC path. Avoid describing GP29 as data/IRQ or GP25 as a MOSFET gate unless board-specific schematic evidence supports those terms.

| Guidance | Basis |
| --- | --- |
| Do not sample ADC3 while WLAN may own GP29. | Conservative firmware policy based on shared pin; datasheet says ADC is usable only when no wireless SPI transaction is in progress. |
| Current firmware shuts WLAN down with `active(False)` and `deinit()` before sampling. | Empirically chosen project sequence. Re-test before changing; exact behavior may depend on MicroPython version. |
| Restore GP29 with `Pin(29, Pin.ALT, pull=Pin.PULL_DOWN, alt=7)` before WLAN activation. | Current project sequence; test on target hardware after firmware or pin-mux changes. |
| Do not drive GP25 directly from application code. | Conservative project rule based on observed CYW43 failures; not a general claim that GP25 can never be controlled. |
| Do not toggle Pico W onboard LED while manipulating WLAN/shared pins. | Onboard LED is controlled by CYW43 on Pico W; avoid adding LED operations to radio/ADC transitions. |

If shutdown cannot be confirmed, firmware must skip ADC(29). Record Pico board revision, MicroPython build, test steps, and observed outcome when revising these policies.

## Runtime behavior to preserve

- Wi-Fi use: startup validation/fetch, explicit long-press refresh on idle screen, and confirmed feeding submission.
- Wake from sleep renders cached dashboard; it does not refresh from server.
- Encoder wizard: `idle → type → amount → start → parent → confirm`.
- Short press advances; long press cancels wizard or refreshes from idle.
- 7-second hold is independent emergency reset; do not add other automatic resets.
- Clock values are UTC internally and rendered in 12-hour local time using fixed `TIMEZONE_OFFSET_MINUTES`.
- Battery cutoff and recovery thresholds live in `main.py`; validate on hardware before changing.

## Runtime settings

Treat values below as current firmware defaults; `main.py` is authoritative.

| Setting | Current value |
| --- | ---: |
| Feeding amount | Default 4.00 oz; 0.25 oz steps; range 0.25–12.00 oz |
| Long press | 700 ms |
| Emergency reset | 28 × 250 ms ticks = 7 seconds |
| Idle display timeout | 20 seconds |
| Error-screen display timeout | 60 seconds |
| Battery check while asleep | Every 30 minutes |
| Low-battery cutoff / recovery | 3.22 V / 3.50 V |
| Active / idle CPU frequency | 125 MHz / 24 MHz |
| Start-time selection | Round down on entry; 15-minute steps; no future times |

Start-time selection currently has no lower time bound. Confirm intended history range before adding one.

## Clock and Baby Buddy API

- Clock sync tries `pool.ntp.org` twice with `ntptime.timeout = 2`, then uses the local Baby Buddy HTTP `Date` header. Clock validity threshold is Jan 1, 2025 UTC.
- Epoch is tracked from `time.ticks_ms()` through `now_epoch()` / `set_accurate_epoch()`; preserve this path when changing CPU scaling or sleeps.
- Startup GETs `/api/children/{CHILD_SLUG}/` with each parent token and confirms returned `id` equals `CHILD_ID`.
- Latest-feed GET uses `/api/feedings/?child={CHILD_ID}&ordering=-end&limit=1`, authenticated with parent 1 token. Parent display name is inferred from configured tags.
- Submission POSTs `/api/feedings/` with child, start/end UTC timestamps, type, bottle method, amount, notes, and selected parent tag.
- A POST timeout or ambiguous server response may still mean feeding was saved. Check Baby Buddy before retrying to avoid duplicate entries.
- Startup checks that tags are configured, but does not confirm each tag exists on Baby Buddy.

## Configuration and networking

Copy `.env.example` to `.env` on the device. `.env` is ignored by Git; never commit credentials.

| Key | Validation / behavior |
| --- | --- |
| `WIFI_SSID` | Required. `WIFI_PASSWORD` may be empty for open networks. |
| `BABY_BUDDY_BASE_URL` | Required; `http://` or `https://`, no trailing slash, query, fragment, or URL credentials. Prefer stable LAN IPv4. |
| `CHILD_SLUG`, `CHILD_ID` | Required; startup verifies slug resolves to configured positive numeric ID. |
| `TIMEZONE_OFFSET_MINUTES` | Defaults to `0` if omitted; accepted range is -720 to +840. Fixed offset; update manually for DST. |
| Parent names | Optional; defaults are used if omitted. |
| Parent tokens and tags | Both parents require non-empty token and tag. Tokens are checked against child endpoint at startup; tag existence is not checked. |

`http_client.py` applies socket timeouts to connect/read operations, not an absolute whole-request deadline. MicroPython `getaddrinfo()` has no portable timeout; NTP also resolves `pool.ntp.org`, so DNS can still delay startup or refresh. HTTP sends API tokens and feeding data in cleartext; use only on a trusted network. The bundled transport does not validate TLS certificates; do not rely on HTTPS as secure until verified TLS is implemented and tested on target firmware.

## Checks and deployment

Run host-side tests with:

```bash
python3 -m unittest discover -s tests -v
```

Host tests cover configuration parsing/validation, child ID matching, HTTP response parsing, and socket timeout cleanup. They do not import hardware-dependent `main.py` and do not replace MicroPython or Pico W testing.

### Hardware validation record

Record actual results here; do not treat untested behavior as verified.

| Item | Record |
| --- | --- |
| Pico W board revision | Not yet recorded |
| MicroPython version/build | Not yet recorded |
| Last on-device validation | Not yet recorded |
| WLAN shutdown / `deinit()` and reconnect | Not yet recorded |
| GP29 ADC sample after confirmed shutdown | Not yet recorded |
| Startup with valid and mismatched child slug/ID | Not yet recorded |
| Baby Buddy GET and safe test submission | Not yet recorded |
| Timeout/error cleanup and wake without Wi-Fi | Not yet recorded |

Before normal use, verify boot/config checks, WLAN shutdown/reconnect, battery readings, cached wake behavior, server refresh, and one controlled feeding submission. Test ambiguous POST failures carefully to avoid duplicate records.

Upload `main.py`, `app_config.py`, `http_client.py`, and `ssd1306.py` to the Pico W, plus device-local `.env`.
