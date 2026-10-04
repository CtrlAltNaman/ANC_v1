# Audio pipeline

## Runtime stages

1. Two INMP441 microphones share the ESP32-S3 I2S bus at 16 kHz.
2. Firmware converts the two slots into signed 16-bit primary/reference PCM.
3. A PSRAM pre-roll buffer preserves the preceding 500 ms when PTT starts.
4. ANC0 packets carry interleaved stereo frames over native USB.
5. `tools/audio/receive.py` validates and records each transmission as WAV.
6. `tools/audio/dashboard.py` applies NLMS using the reference channel.
7. The ML pipeline can apply DCCRN enhancement for residual, non-stationary,
   or impulsive noise.

The reference channel is useful only when its noise is sufficiently correlated
with the primary channel and contains less wanted speech.

## Data contracts

- Capture format: 16-bit little-endian stereo PCM, 16 kHz.
- Channel 0: primary microphone.
- Channel 1: reference microphone.
- Transport: ANC0 packets documented in
  [streaming-protocol.md](streaming-protocol.md).
- Training pairs: matching clean/noisy WAV files under `ml/data/`.

Keep transport and training contracts stable so firmware, host tools, and model
experiments can evolve independently.
