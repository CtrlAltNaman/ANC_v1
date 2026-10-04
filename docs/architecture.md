# Architecture

## Runtime data flow

The ESP32-S3 runs one continuous capture path:

1. The I2S peripheral clocks both INMP441 microphones at 16 kHz using 32-bit
   stereo slots.
2. The capture loop converts the microphone slots to signed 16-bit primary and
   reference samples.
3. A circular PSRAM buffer retains up to 500 ms of pre-roll.
4. PTT starts an ANC0 transmission, including the pre-roll, over native USB.
5. While PTT is held, packets continue to carry interleaved stereo PCM. A short
   hangover keeps the tail of the utterance after button release.
6. The same frames can be copied into a PSRAM clip buffer for the onboard web
   player.

The I2S probe runs before Wi-Fi and HTTP startup. If the probe cannot confirm
real traffic from both slots, the firmware leaves the web server disabled and
signals the fault through the red LED and console.

## Firmware boundaries

| Unit | Responsibility |
| --- | --- |
| `main/src/main.c` | GPIO, I2S, USB packet emission, PTT state, pre-roll, capture loop |
| `main/src/clip.c` | PSRAM clip lifecycle, peak tracking, WAV assembly |
| `main/src/web.c` | SoftAP/station setup, HTTP routes, WebSocket notification, player page |
| `main/include/clip.h` | Clip data model and clip API |
| `main/include/web.h` | Web-server startup and capture-task notification API |

The capture loop owns writes to the clip buffer. The HTTP task reads a copied
WAV representation and never holds the clip lock while sending socket data, so
a slow browser cannot block I2S servicing.

## Host boundaries

`host/receive.py` is a transport adapter. It resynchronizes on the ANC0 magic,
validates packet sizes, detects sequence gaps, and writes stereo WAV files.

`host/dashboard.py` is an offline analysis tool. It loads the primary and
reference channels, runs NLMS, calculates signal metrics, and embeds waveforms
and playable WAV data into one HTML report. It deliberately has no plotting
package, web framework, or runtime service dependency.

## Extension points

The capture format is intentionally stable so later DCCRN or other edge-model
work can consume the same primary/reference recordings. New enhancement stages
should operate after capture or behind a clearly documented host/edge inference
boundary rather than changing the ESP32 transport without a protocol revision.
