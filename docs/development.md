# Development

## Firmware prerequisites

- ESP-IDF 5.5.2
- ESP32-S3 toolchain and Python environment installed by ESP-IDF
- A board with the wiring described in [hardware.md](hardware.md)

After installing ESP-IDF, export its environment in the current shell so
`idf.py` is available.

## Firmware workflow

```text
cd firmware/esp32
idf.py set-target esp32s3
idf.py build
idf.py -p COM21 flash
idf.py -p COM21 monitor
```

Or use the PowerShell wrappers:

```powershell
.\tools\build_firmware.ps1
.\tools\flash_esp32.ps1 -Port COM21
.\tools\monitor_esp32.ps1 -Port COM21
```

`firmware/esp32/CMakeLists.txt` is the ESP-IDF project entry point. The
component source list lives in `firmware/esp32/main/CMakeLists.txt`.

## Host workflow

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r tools/audio/requirements.txt
python -m unittest discover -s tests/unit -v
python tools/audio/receive.py --port COM21 --out recordings/
python tools/audio/dashboard.py recordings/
```

The dashboard and its tests use the standard library. Only the receiver needs
`pyserial` for the USB serial device.

## Generated files

Do not commit build output, local `sdkconfig`, Python virtual environments,
recordings, WAV files, or generated HTML dashboards. The repository's
`.gitignore` already covers these artifacts.

## Troubleshooting

- If the firmware does not build, confirm the ESP-IDF export script ran in the
  same shell and that the target is `esp32s3`.
- If the I2S probe reports no data, check SCK, WS, SD, 3V3, and common ground.
- If only one slot is flat, check that microphone's L/R strap.
- If the host sees no audio, verify it uses the native USB port rather than
  UART0 and check for sequence-gap messages.
- If NLMS removes speech, increase physical separation or revisit the reference
  microphone placement; the reference must correlate with noise more than with
  wanted speech.
