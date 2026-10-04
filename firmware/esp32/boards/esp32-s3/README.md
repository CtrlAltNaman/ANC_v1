# ESP32-S3 board

This firmware targets the ESP32-S3 N16R8 configuration: 16 MB flash and 8 MB
octal PSRAM. The wiring and electrical constraints are documented in
[`docs/hardware.md`](../../../docs/hardware.md).

Build from this directory:

```text
cd firmware/esp32
idf.py set-target esp32s3
idf.py build
```

The application entry point is `firmware/esp32/main/src/main.c`. The component retains the
16 kHz ANC0 stereo transport and the two-microphone capture path.
