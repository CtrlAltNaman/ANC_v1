# DhvaniKavach — adaptive noise-cancellation capture node

SIH Problem Statement 26052, phase 1. DhvaniKavach is an ESP32-S3 capture
prototype for defence-noise speech enhancement: two INMP441 microphones share
one I2S bus, with one microphone acting as the primary speech channel and the
other as a noise reference.

The device keeps the microphones running, gates transmission with a PTT
button, sends interleaved stereo PCM to a wired host over native USB, and
serves the latest clip through a small onboard web player. The host dashboard
then applies a two-microphone NLMS filter and reports signal-quality metrics.

This repository identity and Git remote are unchanged by the project cleanup.

## System at a glance

```text
INMP441 primary ─┐
                 ├─ I2S ─ ESP32-S3 ── native USB ── host/receive.py ── WAV
INMP441 reference┘              │
                                └─ Wi-Fi AP ── onboard web player

WAV ── host/dashboard.py ── NLMS analysis ── self-contained HTML report
```

## Repository layout

```text
main/src/       ESP32 capture loop, clip buffer, Wi-Fi/web player
main/include/   public firmware interfaces
host/           USB receiver and standard-library analysis dashboard
docs/           architecture, hardware, protocol, and development guides
scripts/        Windows helpers for ESP-IDF build/flash/monitor commands
```

## Quick start

### Firmware

The firmware uses ESP-IDF 5.5.2 and targets `esp32s3`.

```text
idf.py set-target esp32s3
idf.py build
idf.py -p COM21 flash monitor
```

PowerShell helpers are also available:

```powershell
.\scripts\build.ps1
.\scripts\flash.ps1 -Port COM21
.\scripts\monitor.ps1 -Port COM21
```

### Host tools

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r host/requirements.txt
python host/receive.py --port COM21 --out recordings/
python host/dashboard.py recordings/
```

The native USB port is separate from the UART console. The receiver writes one
16-bit, 16 kHz stereo WAV per PTT transmission. The dashboard accepts a WAV
path, a recordings directory, or the node URL such as
`http://192.168.4.1/both.wav`.

### Host tests

```powershell
python -m unittest discover -s host/tests -v
```

## Documentation

- [Architecture](docs/architecture.md) — runtime components and data flow
- [Hardware](docs/hardware.md) — board wiring, microphone straps, and LEDs
- [Protocol](docs/protocol.md) — ANC0 USB packet format and stream semantics
- [Development](docs/development.md) — setup, build, test, and troubleshooting
- [Host tools](host/README.md) — receiver and dashboard usage

## Current scope

This branch contains the phase-1 embedded capture node, onboard clip player,
USB receiver, NLMS analysis dashboard, and the DCCRN speech-enhancement
pipeline. The embedded capture protocol remains the stable handoff between
the hardware and ML stages.

## Protocol

USB carries `ANC0` packets: a 12-byte header (`magic`, `seq`, `frames`,
`flags`) followed by interleaved 16-bit stereo PCM at 16 kHz. Channel 0 is the
primary microphone and channel 1 is the reference. Flag bit 0 marks the 500 ms
pre-roll that opens a transmission; a gap in `seq` means the host missed a
packet. See the complete format in [Protocol](docs/protocol.md).

## Speech enhancement (DCCRN)

The NLMS filter handles cases where the reference mic is correlated with noise
but not speech. The DCCRN pipeline handles cases that require a learned
spectral-temporal enhancer trained on defence-relevant noise such as gunshots,
artillery, rotor, engines, sirens, and wind.

### Pipeline

```
dataset_mixer.py            clean speech + noise clips -> noisy/clean pairs + metadata.csv
prepare_dccrn_dataset.py    splits pairs into train / validation / test (80 / 10 / 10)
train.py                    trains DCCRN locally (CPU or CUDA)
colab_train_dccrn.ipynb     same training, full-size model, for a free Colab T4 GPU
evaluate.py                 scores a trained checkpoint on the test set
infer.py                    runs a trained checkpoint on new audio
```

DCCRN operates on the complex STFT and predicts a complex ratio mask, allowing
phase correction as well as magnitude enhancement. Training uses SI-SNR plus a
multi-resolution STFT term. The model implementation is in `src/dccrn.py`.

| Config | Parameters | Where it runs |
| --- | ---: | --- |
| Small | 0.74M | CPU laptop or Raspberry Pi |
| Full | 2.93M | Colab T4 GPU |

### Training and inference

```text
python train.py --data_root dccrn_dataset --epochs 30
python evaluate.py --checkpoint checkpoints/best.pt --data_root dccrn_dataset
python infer.py --checkpoint best.pt --input noisy.wav --output enhanced.wav
```

The full-size test result currently reports SI-SNR 16.29 dB, STOI 0.925, and
PESQ 2.49. SI-SNR is not identical to plain SNR, and PESQ remains just below
the problem-statement target of 2.5; use the evaluation script for the full
breakdown.
