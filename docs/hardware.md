# Hardware

## Board

- ESP32-S3 N16R8: 16 MB flash, 8 MB octal PSRAM
- Two INMP441 digital microphones on one shared I2S bus
- Native USB for audio transport
- UART0 for console logs

## Pinout

| GPIO | Signal |
| --- | --- |
| 4 | I2S SCK/BCLK to both microphones, with 68 Ω series resistance at the ESP end |
| 5 | I2S WS/LRCLK to both microphones, with 68 Ω series resistance at the ESP end |
| 6 | I2S SD/data from both microphones |
| 7 | Red LED cathode; anode through 330 Ω to 3V3; clocks/mics healthy |
| 15 | Green LED cathode; anode through 330 Ω to 3V3; transmitting |
| 16 | PTT button to GND; internal pull-up and 100 nF to GND |
| 43/44 | UART0 console |
| 19/20 | ESP32-S3 native USB audio transport |

## Microphone slot assignment

- Mic A: L/R strap to GND → I2S left slot → primary channel.
- Mic B: L/R strap to 3V3 → I2S right slot → reference channel.

Both microphones share SCK, WS, and SD. They must be powered from 3V3 with a
common ground. Keep the data line short and verify the series resistors are
placed at the ESP32-S3 end.

## Bring-up indicators

The red LED is enabled only after the I2S channel is configured, enabled, and
the timed probe has observed both slots. The green LED indicates an active PTT
transmission. If the probe fails, the firmware does not start the web server;
the console names the likely clock, data, power, or L/R strap fault.

## Network defaults

The onboard player defaults to a SoftAP:

- SSID: `MicRelay`
- Password: `micrelay123`
- URL: `http://192.168.4.1/`

The station-mode credentials are compile-time placeholders in
`firmware/esp32/main/src/web.c`; do not commit real credentials.
