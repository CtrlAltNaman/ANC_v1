#!/usr/bin/env python3
"""Pi 5 side of the Phase 1 capture link.

Reads the PTT-gated stream off the ESP32-S3 and writes one stereo WAV per
transmission: channel 0 is the primary mic, channel 1 the reference.

    python3 receive.py --port /dev/ttyACM0 --out recordings/
"""

import argparse
import pathlib
import struct
import sys
import time
import wave

import serial

MAGIC = b"ANC0"
HDR = struct.Struct("<4sIHH")          # magic, seq, frames, flags
FLAG_PREROLL = 0x0001
SAMPLE_RATE = 16000
MAX_FRAMES = 4096                      # sanity bound when resyncing
IDLE_CLOSE_S = 0.5                     # no packets for this long -> end of transmission


def resync(ser):
    """Scan byte by byte until MAGIC lines up. MAGIC can occur inside PCM data,
    so the caller still validates the frame count before trusting a header."""
    window = b""
    while len(window) < 4:
        b = ser.read(1)
        if not b:
            return False
        window += b
    while window != MAGIC:
        b = ser.read(1)
        if not b:
            return False
        window = window[1:] + b
    return True


def read_exact(ser, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def new_wav(outdir):
    path = outdir / time.strftime("ptt_%Y%m%d_%H%M%S.wav")
    w = wave.open(str(path), "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SAMPLE_RATE)
    return path, w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--out", default="recordings")
    args = ap.parse_args()

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # Baud is ignored by USB CDC but pyserial wants a number.
    ser = serial.Serial(args.port, 921600, timeout=0.2)
    print(f"listening on {args.port}", file=sys.stderr)

    wav = None
    path = None
    last_pkt = 0.0
    expect_seq = None
    dropped = 0

    try:
        while True:
            if not resync(ser):
                # Timed out with no data. Close an open transmission.
                if wav and time.time() - last_pkt > IDLE_CLOSE_S:
                    wav.close()
                    print(f"  wrote {path}" + (f"  ({dropped} packets dropped)" if dropped else ""),
                          file=sys.stderr)
                    wav, path, expect_seq, dropped = None, None, None, 0
                continue

            rest = read_exact(ser, HDR.size - 4)
            if rest is None:
                continue
            _, seq, frames, flags = HDR.unpack(MAGIC + rest)
            if not 0 < frames <= MAX_FRAMES:
                continue                       # false magic inside PCM, keep scanning

            payload = read_exact(ser, frames * 4)
            if payload is None:
                continue

            # A pre-roll packet is the first of a new transmission.
            if flags & FLAG_PREROLL and wav is None:
                path, wav = new_wav(outdir)
                expect_seq = seq
                dropped = 0
                print(f"PTT down -> {path.name}", file=sys.stderr)

            if wav is None:
                continue                       # mid-transmission start, wait for the next key-up

            if expect_seq is not None and seq != expect_seq:
                dropped += (seq - expect_seq) & 0xFFFFFFFF
            expect_seq = (seq + 1) & 0xFFFFFFFF

            wav.writeframes(payload)
            last_pkt = time.time()
    except KeyboardInterrupt:
        pass
    finally:
        if wav:
            wav.close()
            print(f"  wrote {path}", file=sys.stderr)
        ser.close()


if __name__ == "__main__":
    main()
