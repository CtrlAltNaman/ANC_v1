# DhvaniKavach - adaptive noise-cancellation capture node

SIH Problem Statement 26052, phase 1. DhvaniKavach is an ESP32-S3 capture
prototype for defence-noise speech enhancement: two INMP441 microphones share
one I2S bus, with one microphone acting as the primary speech channel and the
other as a noise reference.

The device keeps the microphones running, gates transmission with a PTT
button, sends interleaved stereo PCM to a wired host over native USB, and
serves the latest clip through an onboard web player. The host dashboard then
applies a two-microphone NLMS filter and reports signal-quality metrics.

The repository name and GitHub remote remain `CtrlAltNaman/ANC_v1`.

## System at a glance

```text
INMP441 primary --+
                  +-- I2S -- ESP32-S3 -- native USB -- tools/audio/receive.py -- WAV
INMP441 reference-+              |
                                 +-- Wi-Fi AP -- onboard web player

WAV -- tools/audio/dashboard.py -- NLMS analysis -- self-contained HTML report
```

## Repository layout

```text
firmware/esp32/ ESP32-S3 application, board configuration, and ESP-IDF files
ml/             DCCRN data pipeline, model code, training, evaluation, reports
tools/audio/    USB receiver and standard-library analysis dashboard
tests/          host, audio, integration, and golden regression-test areas
docs/           architecture, hardware, protocol, benchmarking, and decisions
tools/          repeatable firmware and analysis utilities
```

## Quick start

### Firmware

The firmware uses ESP-IDF 5.5.2 and targets `esp32s3`.

```text
cd firmware/esp32
idf.py set-target esp32s3
idf.py build
idf.py -p COM21 flash
idf.py -p COM21 monitor
```

PowerShell helpers are available from the repository root:

```powershell
.\tools\build_firmware.ps1
.\tools\flash_esp32.ps1 -Port COM21
.\tools\monitor_esp32.ps1 -Port COM21
```

### Host tools

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r tools/audio/requirements.txt
python tools/audio/receive.py --port COM21 --out recordings/
python tools/audio/dashboard.py recordings/
```

The native USB port is separate from the UART console. The receiver writes one
16-bit, 16 kHz stereo WAV per PTT transmission. The dashboard accepts a WAV
path, a recordings directory, or the node URL such as
`http://192.168.4.1/both.wav`.

### Tests

```powershell
python -m unittest discover -s tests/unit -v
python -m compileall firmware/esp32/main ml tools tests
```

## Documentation

- [Architecture](docs/architecture.md) - runtime components and data flow
- [Hardware](docs/hardware.md) - board wiring, microphone straps, and LEDs
- [Streaming protocol](docs/streaming-protocol.md) - ANC0 packet format
- [Audio pipeline](docs/audio-pipeline.md) - capture, transport, NLMS, and DCCRN
- [Benchmarking](docs/benchmarking.md) - quality and latency measurements
- [Development](docs/development.md) - setup, build, test, and troubleshooting
- [Host tools](tools/audio/README.md) - receiver and dashboard usage
- [ML pipeline](ml/README.md) - dataset generation, training, and inference
- [Contributing](CONTRIBUTING.md) - branch, commit, and review conventions

## Speech enhancement (DCCRN)

The NLMS filter handles cases where the reference microphone is correlated with
noise but not speech. The DCCRN pipeline handles learned spectral-temporal
enhancement for defence-relevant noise such as gunshots, artillery, rotor,
engines, sirens, and wind.

```text
ml/scripts/dataset_mixer.py          clean speech + noise -> mixed pairs
ml/scripts/prepare_dccrn_dataset.py  splits pairs into train / validation / test
ml/scripts/train.py                  trains DCCRN locally (CPU or CUDA)
ml/scripts/evaluate.py               scores a trained checkpoint
ml/scripts/infer.py                  runs a trained checkpoint on new audio
```

```text
python -m ml.scripts.train --data_root ml/data/dccrn_dataset --epochs 30
python -m ml.scripts.evaluate --checkpoint ml/checkpoints/best.pt --data_root ml/data/dccrn_dataset
python -m ml.scripts.infer --checkpoint ml/checkpoints/best.pt --input noisy.wav --output enhanced.wav
```

DCCRN operates on the complex STFT and predicts a complex ratio mask, allowing
phase correction as well as magnitude enhancement. Results are dataset- and
checkpoint-dependent; use the evaluation script and retain the generated report
before making performance claims.

## Protocol summary

USB carries `ANC0` packets: a 12-byte header (`magic`, `seq`, `frames`,
`flags`) followed by interleaved 16-bit stereo PCM at 16 kHz. Channel 0 is the
primary microphone and channel 1 is the reference. Flag bit 0 marks the 500 ms
pre-roll that opens a transmission; a gap in `seq` means the host missed a
packet. See [the complete protocol](docs/streaming-protocol.md).
