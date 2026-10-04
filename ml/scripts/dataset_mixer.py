#!/usr/bin/env python3
"""
dataset_mixer.py
-----------------
Stage 1 (Dataset Generation & Curation) for the ANC (Adaptive Noise
Cancellation) hackathon pipeline.

Mixes clean speech clips (LibriSpeech / VCTK / in-house recordings) with
defence-relevant noise clips (gunshots, artillery, drone/rotor, armored
vehicle engines, sirens, wind — from AudioSet/ESC-50 or recorded/simulated
sources) at controllable SNR levels, and writes out:

  1. Mixed (noisy) wav files
  2. A metadata CSV with: filename, speech_source, noise_source,
     noise_type, stationary_or_impulsive, snr_db

Directory layout expected:

    speech_dir/
        speaker1_001.wav
        speaker1_002.wav
        ...
    noise_dir/
        gunshot/          <- folder name == noise_type
            clip1.wav
        artillery/
            clip1.wav
        rotor/
            clip1.wav
        engine/
            clip1.wav
        siren/
            clip1.wav
        wind/
            clip1.wav

Each noise_type folder is tagged as stationary or impulsive via the
NOISE_TAGS dict below — edit this if your taxonomy differs.

Usage:
    pip install numpy scipy soundfile librosa --break-system-packages

    python dataset_mixer.py \
        --speech_dir ./data/speech \
        --noise_dir ./data/noise \
        --output_dir ./data/mixed \
        --snr_min -5 --snr_max 20 --snr_step 5 \
        --mixes_per_pair 1 \
        --seed 42
"""

import argparse
import csv
import os
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

try:
    import librosa
except ImportError:
    librosa = None  # only needed for resampling mismatched sample rates


# ---------------------------------------------------------------------------
# Noise taxonomy: stationary vs impulsive tagging per PS scope.
# Edit / extend this if your noise folder names differ.
# ---------------------------------------------------------------------------
NOISE_TAGS = {
    "gunshot": "impulsive",
    "artillery": "impulsive",
    "rotor": "stationary",       # drone / rotor noise, quasi-stationary
    "engine": "stationary",      # armored vehicle engine
    "siren": "non-stationary",   # tonal sweep, neither purely stationary nor impulsive
    "wind": "stationary",
}


def rms(x: np.ndarray) -> float:
    """Root-mean-square energy of a signal, with a floor to avoid div-by-zero."""
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))


def load_audio(path: Path, target_sr: int = 16000) -> np.ndarray:
    """Load a mono wav file, resampling to target_sr if needed."""
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)  # downmix to mono
    if sr != target_sr:
        if librosa is None:
            raise RuntimeError(
                f"{path} is at {sr} Hz but target is {target_sr} Hz; "
                "install librosa to allow resampling."
            )
        data = librosa.resample(data, orig_sr=sr, target_sr=target_sr)
    return data.astype(np.float32)


def fit_noise_to_length(noise: np.ndarray, length: int, rng: random.Random) -> np.ndarray:
    """Loop (tile) or randomly crop a noise clip so it matches `length` samples."""
    if len(noise) == 0:
        return np.zeros(length, dtype=np.float32)
    if len(noise) < length:
        reps = int(np.ceil(length / len(noise)))
        noise = np.tile(noise, reps)
    start = rng.randint(0, max(0, len(noise) - length))
    return noise[start:start + length]


def mix_at_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """Scale noise to hit the target SNR (dB) relative to speech, then mix."""
    speech_rms = rms(speech)
    noise_rms = rms(noise)
    if noise_rms == 0:
        return speech.copy()
    target_noise_rms = speech_rms / (10 ** (snr_db / 20))
    scale = target_noise_rms / noise_rms
    mixed = speech + noise * scale
    # Peak-normalize to avoid clipping while preserving relative SNR.
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak
    return mixed.astype(np.float32)


def gather_noise_files(noise_dir: Path):
    """Return list of (path, noise_type) for every wav under noise_dir/<type>/."""
    files = []
    for type_dir in sorted(p for p in noise_dir.iterdir() if p.is_dir()):
        noise_type = type_dir.name.lower()
        for wav in sorted(type_dir.glob("*.wav")):
            files.append((wav, noise_type))
    return files


def build_dataset(
    speech_dir: Path,
    noise_dir: Path,
    output_dir: Path,
    snr_levels,
    mixes_per_pair: int,
    sample_rate: int,
    seed: int,
):
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_out_dir = output_dir / "audio"
    audio_out_dir.mkdir(exist_ok=True)

    speech_files = sorted(speech_dir.rglob("*.wav"))
    noise_files = gather_noise_files(noise_dir)

    if not speech_files:
        sys.exit(f"No .wav files found in speech_dir: {speech_dir}")
    if not noise_files:
        sys.exit(f"No noise .wav files found under noise_dir/<type>/: {noise_dir}")

    metadata_path = output_dir / "metadata.csv"
    n_written = 0

    with open(metadata_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "filename", "speech_source", "noise_source",
            "noise_type", "stationary_or_impulsive", "snr_db",
        ])

        for speech_path in speech_files:
            speech = load_audio(speech_path, sample_rate)

            for _ in range(mixes_per_pair):
                noise_path, noise_type = rng.choice(noise_files)
                noise_raw = load_audio(noise_path, sample_rate)
                noise = fit_noise_to_length(noise_raw, len(speech), rng)
                snr_db = rng.choice(snr_levels)

                mixed = mix_at_snr(speech, noise, snr_db)

                out_name = (
                    f"{speech_path.stem}__{noise_type}__"
                    f"{snr_db:+.0f}dB__{n_written:06d}.wav"
                )
                out_path = audio_out_dir / out_name
                sf.write(str(out_path), mixed, sample_rate)

                tag = NOISE_TAGS.get(noise_type, "unknown")
                writer.writerow([
                    out_name, speech_path.name, noise_path.name,
                    noise_type, tag, snr_db,
                ])
                n_written += 1

    print(f"Done. Wrote {n_written} mixed clips to {audio_out_dir}")
    print(f"Metadata: {metadata_path}")


def parse_args():
    p = argparse.ArgumentParser(description="Mix speech + defence noise at varying SNR.")
    p.add_argument("--speech_dir", required=True, type=Path)
    p.add_argument("--noise_dir", required=True, type=Path)
    p.add_argument("--output_dir", required=True, type=Path)
    p.add_argument("--snr_min", type=float, default=-5)
    p.add_argument("--snr_max", type=float, default=20)
    p.add_argument("--snr_step", type=float, default=5)
    p.add_argument("--mixes_per_pair", type=int, default=1,
                   help="How many random noise mixes to generate per speech file.")
    p.add_argument("--sample_rate", type=int, default=16000)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    args = parse_args()
    snr_levels = list(np.arange(args.snr_min, args.snr_max + 1e-6, args.snr_step))
    build_dataset(
        speech_dir=args.speech_dir,
        noise_dir=args.noise_dir,
        output_dir=args.output_dir,
        snr_levels=snr_levels,
        mixes_per_pair=args.mixes_per_pair,
        sample_rate=args.sample_rate,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
