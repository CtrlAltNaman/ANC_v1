# ANC0 USB protocol

## Transport

The ESP32-S3 sends one ANC0 packet at a time over native USB. The USB console
and UART logs are separate from this stream. A host may begin reading at any
byte offset because the receiver is expected to resynchronize on the packet
magic.

## Header

Each packet begins with a 12-byte little-endian header:

| Offset | Size | Field | Meaning |
| ---: | ---: | --- | --- |
| 0 | 4 | `magic` | ASCII `ANC0` stored as little-endian `0x30434E41` |
| 4 | 4 | `seq` | Monotonically increasing packet sequence number, wrapping at `uint32_t` |
| 8 | 2 | `frames` | Number of stereo frames in the payload |
| 10 | 2 | `flags` | Packet state flags |

The payload contains `frames` interleaved signed 16-bit PCM samples:

```text
primary[0], reference[0], primary[1], reference[1], ...
```

The nominal format is 16 kHz, 16-bit, stereo. Channel 0 is the primary
microphone and channel 1 is the noise reference.

## Flags

`flags & 0x0001` (`FLAG_PREROLL`) marks packets belonging to the 500 ms history
that opens a PTT transmission. The first flagged packet starts a new recording
in `tools/audio/receive.py`; later packets continue that transmission.

## Integrity and recovery

- Hosts must reject frame counts outside the configured sanity bound.
- A sequence gap means one or more packets were missed. The receiver records
  the count and continues writing the capture at the next packet boundary.
- A partial header or payload is discarded until the next valid ANC0 header can
  be read.
- The host closes an open WAV after the configured idle interval with no packet.

The format has no checksum. USB packet boundaries and sequence numbers provide
the current lightweight recovery mechanism.
