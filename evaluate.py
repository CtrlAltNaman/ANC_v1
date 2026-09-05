"""
Evaluate a trained DCCRN checkpoint on the test split: computes SNR, SI-SNR,
STOI and PESQ for the noisy input and the enhanced output, prints the
overall improvement, and breaks results down per noise type and per input
SNR level. Also writes a few enhanced .wav files for listening.

Usage:
    python evaluate.py --checkpoint checkpoints/best.pt --data_root dccrn_dataset
"""
import argparse
import collections
import csv
import os
import sys

import numpy as np
import soundfile as sf
import torch
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from dccrn import DCCRN
from dataset import NoisyCleanDataset, collate_eval
from metrics import evaluate_pair


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", type=str, default="checkpoints/best.pt")
    p.add_argument("--data_root", type=str, default="dccrn_dataset")
    p.add_argument("--split", type=str, default="test")
    p.add_argument("--sample_rate", type=int, default=16000)
    p.add_argument("--device", type=str, default=None)
    p.add_argument("--save_samples", type=int, default=5,
                    help="Number of enhanced wavs to save for listening")
    p.add_argument("--output_dir", type=str, default="results")
    p.add_argument("--max_utts", type=int, default=0, help="0 = evaluate all")
    return p.parse_args()


def main():
    args = parse_args()
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    os.makedirs(args.output_dir, exist_ok=True)
    samples_dir = os.path.join(args.output_dir, "enhanced_samples")
    os.makedirs(samples_dir, exist_ok=True)

    ckpt = torch.load(args.checkpoint, map_location=device)
    train_args = ckpt.get("args", {})
    channels = tuple(int(c) for c in train_args.get("channels", "16,32,64,64,128,128").split(","))
    model = DCCRN(
        n_fft=512, hop_length=100, win_length=400, channels=channels,
        lstm_hidden=train_args.get("lstm_hidden", 128),
        lstm_layers=train_args.get("lstm_layers", 2),
    ).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    print(f"Loaded checkpoint {args.checkpoint} (epoch {ckpt.get('epoch', '?')})")

    dataset = NoisyCleanDataset(args.data_root, args.split, args.sample_rate, train=False)
    n_utts = len(dataset) if not args.max_utts else min(args.max_utts, len(dataset))

    rows = []
    saved = 0
    with torch.no_grad():
        for idx in tqdm(range(n_utts), desc=f"Evaluating {args.split}"):
            noisy, clean, fname, meta = dataset[idx]
            noisy_t = noisy.unsqueeze(0).to(device)
            estimate = model(noisy_t).squeeze(0).cpu().numpy()

            clean_np = clean.numpy()
            noisy_np = noisy.numpy()
            n = min(len(estimate), len(clean_np), len(noisy_np))
            estimate, clean_np, noisy_np = estimate[:n], clean_np[:n], noisy_np[:n]

            noisy_metrics = evaluate_pair(noisy_np, clean_np, args.sample_rate)
            enh_metrics = evaluate_pair(estimate, clean_np, args.sample_rate)

            row = {
                "file": fname,
                "noise_type": meta["noise"],
                "input_snr_db": meta["snr"],
                "noisy_snr": noisy_metrics["snr"],
                "enh_snr": enh_metrics["snr"],
                "noisy_si_snr": noisy_metrics["si_snr"],
                "enh_si_snr": enh_metrics["si_snr"],
                "noisy_stoi": noisy_metrics["stoi"],
                "enh_stoi": enh_metrics["stoi"],
                "noisy_pesq": noisy_metrics["pesq"],
                "enh_pesq": enh_metrics["pesq"],
            }
            rows.append(row)

            if saved < args.save_samples:
                sf.write(os.path.join(samples_dir, f"enhanced_{fname}"), estimate, args.sample_rate)
                sf.write(os.path.join(samples_dir, f"noisy_{fname}"), noisy_np, args.sample_rate)
                sf.write(os.path.join(samples_dir, f"clean_{fname}"), clean_np, args.sample_rate)
                saved += 1

    csv_path = os.path.join(args.output_dir, f"{args.split}_metrics.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Per-file metrics written to {csv_path}")

    def mean(key, source=rows):
        vals = [r[key] for r in source if not np.isnan(r[key])]
        return float(np.mean(vals)) if vals else float("nan")

    print("\n===== Overall test-set results (mean over {} utterances) =====".format(len(rows)))
    print(f"{'Metric':<10}{'Noisy':>10}{'Enhanced':>10}{'Delta':>10}")
    for label, noisy_key, enh_key in [
        ("SNR (dB)", "noisy_snr", "enh_snr"),
        ("SI-SNR", "noisy_si_snr", "enh_si_snr"),
        ("STOI", "noisy_stoi", "enh_stoi"),
        ("PESQ", "noisy_pesq", "enh_pesq"),
    ]:
        n_val, e_val = mean(noisy_key), mean(enh_key)
        print(f"{label:<10}{n_val:>10.3f}{e_val:>10.3f}{e_val - n_val:>+10.3f}")

    target_check = {
        "SNR > 15 dB": mean("enh_snr") > 15,
        "STOI > 0.85": mean("enh_stoi") > 0.85,
        "PESQ > 2.5": mean("enh_pesq") > 2.5,
    }
    print("\n===== Target spec check =====")
    for k, v in target_check.items():
        print(f"{k}: {'PASS' if v else 'FAIL'}")

    print("\n===== Breakdown by noise type (enhanced PESQ / STOI / SNR) =====")
    by_noise = collections.defaultdict(list)
    for r in rows:
        by_noise[r["noise_type"]].append(r)
    for noise, group in sorted(by_noise.items()):
        print(f"{noise:<12} n={len(group):<5} "
              f"PESQ={mean('enh_pesq', group):.2f}  STOI={mean('enh_stoi', group):.3f}  "
              f"SNR={mean('enh_snr', group):.2f} dB")

    print("\n===== Breakdown by input SNR level (enhanced PESQ / STOI / SNR) =====")
    by_snr = collections.defaultdict(list)
    for r in rows:
        by_snr[r["input_snr_db"]].append(r)
    for snr_level, group in sorted(by_snr.items(), key=lambda kv: (kv[0] is None, kv[0])):
        print(f"{snr_level}dB{'':<8} n={len(group):<5} "
              f"PESQ={mean('enh_pesq', group):.2f}  STOI={mean('enh_stoi', group):.3f}  "
              f"SNR={mean('enh_snr', group):.2f} dB")

    print(f"\nA few enhanced/noisy/clean wav samples were saved to {samples_dir} for listening.")


if __name__ == "__main__":
    main()
