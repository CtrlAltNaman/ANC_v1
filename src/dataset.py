"""Paired clean/noisy speech dataset for DCCRN training.

Expects the layout produced by the dccrn_dataset generator:

    <root>/train/clean/*.wav       <root>/train/noisy/*.wav
    <root>/validation/clean/*.wav  <root>/validation/noisy/*.wav
    <root>/test/clean/*.wav        <root>/test/noisy/*.wav

with identical filenames in the clean/noisy pair, e.g.
"1272-128104-0000__engine__+20dB__000000.wav". The noise type and SNR are
encoded in the filename (speaker-utt__noisetype__SNRdB__index.wav) and are
parsed out for per-condition evaluation breakdowns.
"""
import os
import random
import re
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from torch.utils.data import Dataset

FNAME_RE = re.compile(r"^(?P<utt>.+)__(?P<noise>[^_]+)__(?P<snr>[+-]?\d+)dB__(?P<idx>\d+)$")


def parse_filename(path):
    stem = Path(path).stem
    m = FNAME_RE.match(stem)
    if m is None:
        return {"utt": stem, "noise": "unknown", "snr": None}
    return {"utt": m.group("utt"), "noise": m.group("noise"), "snr": int(m.group("snr"))}


class NoisyCleanDataset(Dataset):
    def __init__(self, root, split, sample_rate=16000, segment_seconds=4.0, train=True):
        self.clean_dir = os.path.join(root, split, "clean")
        self.noisy_dir = os.path.join(root, split, "noisy")
        self.files = sorted(
            f for f in os.listdir(self.clean_dir) if f.lower().endswith(".wav")
        )
        if not self.files:
            raise RuntimeError(f"No wav files found in {self.clean_dir}")
        self.sample_rate = sample_rate
        self.segment_len = int(segment_seconds * sample_rate)
        self.train = train

    def __len__(self):
        return len(self.files)

    def _load(self, path):
        wav, sr = sf.read(path, dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        if sr != self.sample_rate:
            raise ValueError(f"{path} has sample rate {sr}, expected {self.sample_rate}")
        return wav

    def __getitem__(self, idx):
        fname = self.files[idx]
        clean = self._load(os.path.join(self.clean_dir, fname))
        noisy = self._load(os.path.join(self.noisy_dir, fname))

        n = min(len(clean), len(noisy))
        clean, noisy = clean[:n], noisy[:n]

        if self.train:
            if n >= self.segment_len:
                start = random.randint(0, n - self.segment_len)
                clean = clean[start:start + self.segment_len]
                noisy = noisy[start:start + self.segment_len]
            else:
                pad = self.segment_len - n
                clean = np.pad(clean, (0, pad))
                noisy = np.pad(noisy, (0, pad))

        meta = parse_filename(fname)
        return (
            torch.from_numpy(noisy).float(),
            torch.from_numpy(clean).float(),
            fname,
            meta,
        )


def collate_eval(batch):
    """Keep variable-length items as a list for full-utterance evaluation."""
    noisy = [b[0] for b in batch]
    clean = [b[1] for b in batch]
    fnames = [b[2] for b in batch]
    metas = [b[3] for b in batch]
    return noisy, clean, fnames, metas
