# Decision 001: ESP32-S3 capture target

## Decision

Use the ESP32-S3 as the phase-1 microphone capture and transport target.

## Rationale

It provides I2S support for the two-microphone front end, native USB for a
simple host transport, and PSRAM for the pre-roll and clip buffers. Keeping
capture deterministic on the microcontroller leaves learned enhancement free to
iterate on the host or a stronger edge processor.

## Consequences

The firmware owns capture, buffering, packet framing, and the web player. Model
inference is a separate stage until measured hardware capacity justifies moving
it onto the device.
