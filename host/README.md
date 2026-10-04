# Host tools

The host tools receive the ESP32-S3's native USB stream and inspect captured
stereo audio. They are intended to run on a Raspberry Pi, Linux workstation,
or Windows development machine.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r host/requirements.txt
```

The receiver needs `pyserial`. The dashboard uses only the Python standard
library and does not require NumPy, a plotting package, or a web framework.

## Receive a capture

Use the ESP32-S3 native USB port, not the UART console:

```text
python host/receive.py --port COM21 --out recordings/
```

On Linux, replace the port with `/dev/ttyACM0` or the device assigned by the
operating system. The receiver writes one 16-bit, 16 kHz stereo WAV per PTT
transmission. Channel 0 is the primary microphone and channel 1 is the noise
reference microphone.

## Generate an analysis dashboard

```text
python host/dashboard.py recordings/ptt_20261004_120000.wav
```

The dashboard runs the two-microphone NLMS filter and creates a self-contained
HTML report with waveforms, playback controls, signal metrics, and before/after
values. To analyze the newest capture in a directory:

```text
python host/dashboard.py recordings/
```

The dashboard can also load a clip directly from the device web player:

```text
python host/dashboard.py --url http://192.168.4.1/both.wav
```

## Tests

Run the host regression tests from the repository root:

```powershell
python -m unittest discover -s host/tests -v
```

The tests do not require an ESP32 board or a serial connection.
