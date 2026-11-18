# Baby Buddy Gadget

## Time zone configuration

Set `TIMEZONE_OFFSET_MINUTES` in `.env`. Values are minutes east or west of
UTC. The device uses a fixed offset, so update it when daylight saving time
changes.

| Time zone | Standard | Daylight saving |
| --------- | -------: | --------------: |
| Eastern   |   `-300` |          `-240` |
| Central   |   `-360` |          `-300` |
| Mountain  |   `-420` |          `-360` |
| Pacific   |   `-480` |          `-420` |
| Alaska    |   `-540` |          `-480` |
| Hawaii    |   `-600` |          `-600` |

Examples:

```env
# Eastern Standard Time
TIMEZONE_OFFSET_MINUTES=-300

# Eastern Daylight Time
TIMEZONE_OFFSET_MINUTES=-240
```

Upload updated configuration to Pico:

```bash
ampy --port /dev/tty.usbmodem114401 put .env
```

## Interactive device configuration

Install `gum`, `ampy`, and Python 3, then connect the Pico and run:

```bash
./scripts/configure-device.sh
```

The menu can display current settings or edit one section at a time. Edits stay
staged while you choose more sections; review before saving and uploading, or
discard staged changes. Passwords and API tokens stay hidden unless explicitly
revealed. Saved changes create a timestamped `.env` backup before upload.

Preview selected changes without saving or uploading:

```bash
./scripts/configure-device.sh --dry-run
```

## Firmware deployment

Keep `.env` on the device only; it contains Wi-Fi and API credentials and is
ignored by Git. Upload these firmware files to the Pico W:

- `main.py`
- `app_config.py`
- `http_client.py`
- `ssd1306.py`

Use a stable LAN IPv4 address for `BABY_BUDDY_BASE_URL` where possible. Socket
connect/read operations have timeouts, but MicroPython DNS lookup through
`getaddrinfo()` has no portable timeout. Plain HTTP sends API tokens in
cleartext; use only on a trusted network. The bundled MicroPython transport
does not validate TLS certificates by itself, so do not rely on HTTPS until
verified TLS is implemented and tested for the device firmware.

## Host-side checks

Run hardware-independent checks with:

```bash
python3 -m unittest discover -s tests -v
```

Host tests do not replace Pico W validation. Test wireless shutdown/reconnect,
GP29 battery sampling, and API failure cleanup on the actual board before
deploying firmware changes.

## Hard Reboot

To perform a hard reboot of the device, press and hold the knob for 7 seconds. The device will restart.
