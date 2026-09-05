"""Evaluation metrics: SNR, STOI, PESQ, SI-SNR — all on numpy arrays at 16 kHz."""
import numpy as np
from pesq import pesq as pesq_fn
from pystoi import stoi as stoi_fn


def snr(estimate, target, eps=1e-8):
    noise = estimate - target
    return 10 * np.log10((np.sum(target ** 2) + eps) / (np.sum(noise ** 2) + eps))


def si_snr_np(estimate, target, eps=1e-8):
    estimate = estimate - estimate.mean()
    target = target - target.mean()
    s_target = (np.sum(estimate * target) / (np.sum(target ** 2) + eps)) * target
    e_noise = estimate - s_target
    return 10 * np.log10((np.sum(s_target ** 2) + eps) / (np.sum(e_noise ** 2) + eps))


def stoi_score(estimate, target, sr=16000):
    return stoi_fn(target, estimate, sr, extended=False)


def pesq_score(estimate, target, sr=16000):
    mode = "wb" if sr == 16000 else "nb"
    try:
        return pesq_fn(sr, target, estimate, mode)
    except Exception:
        return float("nan")


def evaluate_pair(estimate, target, sr=16000):
    n = min(len(estimate), len(target))
    estimate, target = estimate[:n], target[:n]
    return {
        "snr": snr(estimate, target),
        "si_snr": si_snr_np(estimate, target),
        "stoi": stoi_score(estimate, target, sr),
        "pesq": pesq_score(estimate, target, sr),
    }
