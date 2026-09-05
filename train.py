"""
Train a DCCRN speech-enhancement model on the dccrn_dataset noisy/clean pairs.

Usage:
    python train.py --data_root dccrn_dataset --epochs 30 --batch_size 8

Checkpoints go to ./checkpoints, TensorBoard logs to ./logs.
Run evaluate.py afterwards to compute SNR / SI-SNR / STOI / PESQ on the test set.
"""
import argparse
import os
import sys
import time

import torch
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from dccrn import DCCRN
from dataset import NoisyCleanDataset
from losses import combined_loss, si_snr


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--data_root", type=str, default="dccrn_dataset",
                    help="Folder containing train/validation/test subfolders")
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch_size", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--segment_seconds", type=float, default=2.0)
    p.add_argument("--sample_rate", type=int, default=16000)
    p.add_argument("--channels", type=str, default="8,16,32,32,64,64",
                    help="Comma-separated encoder channel sizes. Use "
                         "16,32,64,64,128,128 for the full paper-scale DCCRN (needs a GPU "
                         "for practical training time).")
    p.add_argument("--lstm_hidden", type=int, default=64)
    p.add_argument("--lstm_layers", type=int, default=2)
    p.add_argument("--num_workers", type=int, default=2)
    p.add_argument("--checkpoint_dir", type=str, default="checkpoints")
    p.add_argument("--log_dir", type=str, default="logs")
    p.add_argument("--resume", type=str, default=None, help="Path to checkpoint to resume from")
    p.add_argument("--stft_loss_weight", type=float, default=0.2)
    p.add_argument("--grad_clip", type=float, default=5.0)
    p.add_argument("--device", type=str, default=None, help="cuda / cpu (auto-detect if unset)")
    p.add_argument("--limit_train_batches", type=int, default=0,
                    help="If >0, cap batches per epoch (useful for a quick smoke test)")
    return p.parse_args()


def main():
    args = parse_args()
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    os.makedirs(args.checkpoint_dir, exist_ok=True)
    os.makedirs(args.log_dir, exist_ok=True)

    train_set = NoisyCleanDataset(args.data_root, "train", args.sample_rate,
                                   args.segment_seconds, train=True)
    val_set = NoisyCleanDataset(args.data_root, "validation", args.sample_rate,
                                 args.segment_seconds, train=True)
    print(f"Train utterances: {len(train_set)} | Validation utterances: {len(val_set)}")

    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True,
                               num_workers=args.num_workers, drop_last=True, pin_memory=(device == "cuda"))
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False,
                             num_workers=args.num_workers, pin_memory=(device == "cuda"))

    channels = tuple(int(c) for c in args.channels.split(","))
    model = DCCRN(n_fft=512, hop_length=100, win_length=400, channels=channels,
                  lstm_hidden=args.lstm_hidden, lstm_layers=args.lstm_layers).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {n_params / 1e6:.2f}M")

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=3
    )

    start_epoch = 0
    best_val_loss = float("inf")
    if args.resume and os.path.isfile(args.resume):
        ckpt = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt["model_state"])
        optimizer.load_state_dict(ckpt["optimizer_state"])
        start_epoch = ckpt["epoch"] + 1
        best_val_loss = ckpt.get("best_val_loss", float("inf"))
        print(f"Resumed from {args.resume} at epoch {start_epoch}")

    writer = SummaryWriter(args.log_dir)
    global_step = start_epoch * len(train_loader)

    for epoch in range(start_epoch, args.epochs):
        model.train()
        epoch_start = time.time()
        running_loss = 0.0
        n_batches = 0

        for i, (noisy, clean, _, _) in enumerate(train_loader):
            if args.limit_train_batches and i >= args.limit_train_batches:
                break
            noisy, clean = noisy.to(device), clean.to(device)

            estimate = model(noisy)
            estimate = estimate[..., :clean.shape[-1]]
            loss = combined_loss(estimate, clean, stft_weight=args.stft_loss_weight)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
            optimizer.step()

            running_loss += loss.item()
            n_batches += 1
            global_step += 1
            writer.add_scalar("train/loss_step", loss.item(), global_step)

            if i % 20 == 0:
                print(f"epoch {epoch} batch {i}/{len(train_loader)} loss {loss.item():.4f}")

        train_loss = running_loss / max(n_batches, 1)

        model.eval()
        val_loss = 0.0
        val_sisnr = 0.0
        n_val = 0
        with torch.no_grad():
            for noisy, clean, _, _ in val_loader:
                noisy, clean = noisy.to(device), clean.to(device)
                estimate = model(noisy)
                estimate = estimate[..., :clean.shape[-1]]
                loss = combined_loss(estimate, clean, stft_weight=args.stft_loss_weight)
                val_loss += loss.item()
                val_sisnr += si_snr(estimate, clean).mean().item()
                n_val += 1
        val_loss /= max(n_val, 1)
        val_sisnr /= max(n_val, 1)

        scheduler.step(val_loss)
        elapsed = time.time() - epoch_start
        print(f"== epoch {epoch} done in {elapsed:.1f}s | train_loss {train_loss:.4f} "
              f"| val_loss {val_loss:.4f} | val_SI-SNR {val_sisnr:.2f} dB ==")

        writer.add_scalar("train/loss_epoch", train_loss, epoch)
        writer.add_scalar("val/loss_epoch", val_loss, epoch)
        writer.add_scalar("val/si_snr", val_sisnr, epoch)
        writer.add_scalar("lr", optimizer.param_groups[0]["lr"], epoch)

        ckpt = {
            "epoch": epoch,
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict(),
            "val_loss": val_loss,
            "best_val_loss": best_val_loss,
            "args": vars(args),
        }
        torch.save(ckpt, os.path.join(args.checkpoint_dir, "last.pt"))
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            ckpt["best_val_loss"] = best_val_loss
            torch.save(ckpt, os.path.join(args.checkpoint_dir, "best.pt"))
            print(f"  -> new best model saved (val_loss={val_loss:.4f})")

    writer.close()
    print("Training complete. Run evaluate.py to score the test set.")


if __name__ == "__main__":
    main()
