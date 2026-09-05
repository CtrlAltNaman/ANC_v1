"""
Standalone inference script for deployment (e.g. Raspberry Pi).

Loads a trained DCCRN checkpoint and enhances one or more noisy wav files.
Only needs: this file, src/dccrn.py, the checkpoint (.pt), and the packages
in requirements-inference.txt (torch, soundfile) -- none of the training
code (dataset.py, losses.py, train.py) is required on the deployment device.

Usage:
    python infer.py --checkpoint best.pt --input noisy.wav --output enhanced.wav
    python infer.py --checkpoint best.pt --input_dir noisy_folder --output_dir enhanced_folder
"""
import argparse
import os
import sys
import time

import soundfile as sf
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from dccrn import DCCRN


def load_model(checkpoint_path, device="cpu"):
    ckpt = torch.load(checkpoint_path, map_location=device)
    train_args = ckpt.get("args", {})
    channels = tuple(int(c) for c in train_args.get("channels", "16,32,64,64,128,128").split(","))
    model = DCCRN(
        n_fft=512, hop_length=100, win_length=400, channels=channels,
        lstm_hidden=train_args.get("lstm_hidden", 128),
        lstm_layers=train_args.get("lstm_layers", 2),
    ).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model


def enhance_file(model, in_path, out_path, sample_rate=16000, device="cpu"):
    wav, sr = sf.read(in_path, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != sample_rate:
        raise ValueError(f"{in_path}: expected {sample_rate} Hz, got {sr} Hz")

    x = torch.from_numpy(wav).unsqueeze(0).to(device)
    t0 = time.time()
    with torch.no_grad():
        enhanced = model(x).squeeze(0).cpu().numpy()
    elapsed = time.time() - t0

    sf.write(out_path, enhanced, sample_rate)
    duration = len(wav) / sample_rate
    print(f"{os.path.basename(in_path)}: {duration:.2f}s audio processed in "
          f"{elapsed*1000:.0f} ms (RTF={elapsed/duration:.3f}) -> {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", type=str, required=True)
    p.add_argument("--input", type=str, help="Single input wav file")
    p.add_argument("--output", type=str, help="Single output wav file")
    p.add_argument("--input_dir", type=str, help="Folder of input wav files")
    p.add_argument("--output_dir", type=str, help="Folder to write enhanced wav files")
    p.add_argument("--sample_rate", type=int, default=16000)
    p.add_argument("--device", type=str, default="cpu")
    args = p.parse_args()

    model = load_model(args.checkpoint, args.device)

    if args.input:
        out_path = args.output or "enhanced.wav"
        enhance_file(model, args.input, out_path, args.sample_rate, args.device)
    elif args.input_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        for fname in sorted(os.listdir(args.input_dir)):
            if fname.lower().endswith(".wav"):
                enhance_file(
                    model, os.path.join(args.input_dir, fname),
                    os.path.join(args.output_dir, fname), args.sample_rate, args.device,
                )
    else:
        p.error("Provide either --input/--output or --input_dir/--output_dir")


if __name__ == "__main__":
    main()
