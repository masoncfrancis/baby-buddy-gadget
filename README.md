# Baby Buddy Gadget

## Time zone configuration

Set `TIMEZONE_OFFSET_MINUTES` in `.env`. Values are minutes east or west of
UTC. The device uses a fixed offset, so update it when daylight saving time
changes.

| Time zone | Standard | Daylight saving |
| --- | ---: | ---: |
| Eastern | `-300` | `-240` |
| Central | `-360` | `-300` |
| Mountain | `-420` | `-360` |
| Pacific | `-480` | `-420` |
| Alaska | `-540` | `-480` |
| Hawaii | `-600` | `-600` |

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
