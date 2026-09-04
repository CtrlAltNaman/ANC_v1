# MicRelay — two-mic capture node

SIH 26052, phase 1. An ESP32-S3 with two INMP441 microphones on one I2S bus:
one primary mic and one noise reference, captured together so the pair can be
used for adaptive noise cancellation downstream.

A press of the PTT button streams audio to a wired host over USB. Releasing it
publishes the clip to a small web player on the board itself, so the capture can
be checked from a phone with nothing else connected.

## Hardware

ESP32-S3 (N16R8: 16 MB flash, 8 MB octal PSRAM) and two INMP441 modules sharing
the clock lines.

| Pin     | Signal                                                    |
| ------- | --------------------------------------------------------- |
| GPIO 4  | SCK → both mics (68R at the ESP end)                      |
| GPIO 5  | WS  → both mics (68R at the ESP end)                      |
| GPIO 6  | SD  ← both mics                                           |
| GPIO 7  | red LED, cathode; anode via 330R to 3V3 — clocks running  |
| GPIO 15 | green LED, same wiring — transmitting                     |
| GPIO 16 | PTT button to GND, internal pull-up, 100nF to GND         |

Mic A straps L/R to **GND** → left slot → primary.
Mic B straps L/R to **3V3** → right slot → reference.

The console is UART0 on GPIO 43/44. Audio leaves over the ESP32-S3's *native*
USB (GPIO 19/20) — a separate port from the console, so logs never land inside
the PCM stream.

## Build and flash

```
idf.py -p COM21 flash monitor
```

ESP-IDF 5.5.2, target `esp32s3`. `sdkconfig` is generated from
`sdkconfig.defaults`; the app needs the 3 MB partition in `partitions.csv`
because Wi-Fi and the HTTP server do not fit the stock 1 MB table.

## Reading the boot log

Bring-up runs in five stages and each reports its own result. The one worth
watching is the I2S probe, which does not trust the registers — it times real
traffic on the bus and analyses it:

```
anc: i2s: read 16000 frames in 1000 ms -> 16000 Hz on the wire (configured 16000 Hz)
anc: i2s: left  (mic A): audio +-412000 (4% FS), DC +1200 (0% FS), 0% of samples zero
anc: i2s: right (mic B): audio +-388000 (4% FS), DC +900 (0% FS), 0% of samples zero
anc: i2s: PROBE OK - both slots carrying audio
```

Each failure names the pin to check: no data at all means SCK/WS are not
clocking, all-zero samples mean SD is not arriving or the mics are unpowered,
and one flat slot means that mic's L/R strap. If the probe fails the web server
is not started at all — the red LED blinks instead of the board pretending to
be a working capture node.

## Web player

The node brings up a SoftAP: join **MicRelay** / **micrelay123** and open
<http://192.168.4.1/>. To put it on an existing network instead, set
`WEB_SOFT_AP` to 0 in `main/web.c` and fill in the SSID and password below it.

Press **Record 5 s** on the page, or just hold PTT — up to 10 s. The page holds
a WebSocket, so a clip recorded with the button appears the moment you release
it, with no reload. Three players: left mic, right mic, and both as stereo.

## Wired host

`host/receive.py` reads the USB stream and writes one stereo WAV per PTT press:

```
pip install pyserial
python host/receive.py --port /dev/ttyACM0 --out recordings/
```

The port is the native-USB one (VID `303A`), not the console UART.

## Dashboard

`host/dashboard.py` runs the two-mic noise canceller over a capture and writes a
self-contained HTML page: three waveforms — primary, reference, and the cleaned
output — with peak, RMS, crest factor, noise floor, SNR, DC offset,
zero-crossing rate and clipping for each, plus a before/after table.

```
python host/dashboard.py                            # newest wav in recordings/
python host/dashboard.py --url http://192.168.4.1/both.wav
python host/dashboard.py capture.wav --taps 64 --mu 0.5
```

Standard library only — no numpy, no plotting library, no web framework — so it
runs on the Pi as-is.

NLMS only helps where the reference is correlated with the noise but not with
the speech. Mics close together hear nearly the same thing, and the filter will
cancel the speech along with the noise: watch the SNR row rather than the raw
reduction figure.

## Layout

```
main/main.c    capture loop, bring-up logging, I2S probe, PTT
main/clip.c    the recorded clip in PSRAM, WAV assembly
main/web.c     SoftAP, HTTP server, the player page, WebSocket push
host/receive.py    USB stream → one WAV per transmission
host/dashboard.py  noise canceller + analysis page
```

## Protocol

USB carries `ANC0` packets: a 12-byte header (magic, `seq`, `frames`, `flags`)
then interleaved 16-bit stereo PCM at 16 kHz, channel 0 primary and channel 1
reference. `flags` bit 0 marks the 500 ms pre-roll that opens a transmission —
the buffer that lets a recording start before the thumb did. A gap in `seq`
means the host missed a packet.
