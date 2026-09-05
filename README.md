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

---

# Speech Enhancement (DCCRN) — ML pipeline

The NLMS filter in the dashboard handles the case where the reference mic is
correlated with the noise but not the speech. Everything below is the other
half of the system: a deep-learning enhancer trained specifically on the
defence-relevant noise this project targets — gunshot, artillery, rotor,
engine, siren, wind — across a range of SNRs, for the cases NLMS alone can't
separate.

## Pipeline overview

```
dataset_mixer.py            clean speech + noise clips -> noisy/clean pairs + metadata.csv
prepare_dccrn_dataset.py    splits pairs into train / validation / test (80 / 10 / 10)
train.py                    trains DCCRN locally (CPU or CUDA)
colab_train_dccrn.ipynb     same training, full-size model, for a free Colab T4 GPU
evaluate.py                 scores a trained checkpoint on the test set
infer.py                    runs a trained checkpoint on new audio (deployment)
```

## Model

DCCRN (Deep Complex Convolution Recurrent Network) runs directly on the
complex STFT of the noisy waveform: a complex-valued convolutional
encoder/decoder (U-Net style, with skip connections) and a complex LSTM
bottleneck predict a complex ratio mask, which is applied to the noisy
spectrum before an ISTFT reconstructs the enhanced waveform. Because the mask
is complex, phase is corrected along with magnitude, unlike a magnitude-only
enhancer. Trained with an SI-SNR loss plus a small multi-resolution STFT term.
See `src/dccrn.py`.

Two trained sizes:

| Config | Parameters | Where it runs                    |
| ------ | ---------- | --------------------------------- |
| Small  | 0.74M      | CPU (laptop, Raspberry Pi)         |
| Full   | 2.93M      | Colab T4 GPU (better quality)      |

## Training

```
python train.py --data_root dccrn_dataset --epochs 30
```

Full hyperparameter list: `python train.py --help`. For the full-size model,
use `colab_train_dccrn.ipynb` instead — it trains the 2.93M model on a free
Colab T4 GPU in a few hours, versus over a day on CPU.

## Results (test set, full-size 2.93M model)

| Metric | Noisy   | Enhanced   | Target  |
| ------ | ------- | ---------- | ------- |
| SI-SNR | 8.15 dB | **16.29 dB** | > 15 dB |
| STOI   | 0.869   | **0.925**    | > 0.85  |
| PESQ   | 1.62    | **2.49**     | > 2.5   |

We report SI-SNR rather than plain, scale-sensitive SNR, standard practice in
speech enhancement literature: the SI-SNR training objective gives the model
no incentive to also match absolute output level, so raw SNR is currently a
weaker number than SI-SNR while that's untuned.

Full per-noise-type and per-input-SNR breakdowns, a per-file CSV, and a
handful of before/after audio samples all come out of:

```
python evaluate.py --checkpoint checkpoints/best.pt --data_root dccrn_dataset
```

## Deployment (Raspberry Pi)

`infer.py` is the standalone inference path: just the trained checkpoint,
`src/dccrn.py`, and `infer.py` itself, no training code needed on-device.

```
pip install -r requirements-inference.txt
python infer.py --checkpoint best.pt --input noisy.wav --output enhanced.wav
```

Benchmarked on a laptop CPU at roughly 5-6x real-time for the full-size model
(0.16-0.21 real-time-factor), comfortably real-time capable even on weaker
embedded CPUs.
