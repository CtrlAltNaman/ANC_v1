"""Loss functions for time-domain speech enhancement training."""
import torch


def si_snr(estimate, target, eps=1e-8):
    """Scale-invariant SNR (higher is better), computed per-item in the batch.

    estimate, target: (B, T)
    returns: (B,) SI-SNR in dB
    """
    estimate = estimate - estimate.mean(dim=-1, keepdim=True)
    target = target - target.mean(dim=-1, keepdim=True)

    s_target = (torch.sum(estimate * target, dim=-1, keepdim=True) /
                (torch.sum(target * target, dim=-1, keepdim=True) + eps)) * target
    e_noise = estimate - s_target

    ratio = torch.sum(s_target ** 2, dim=-1) / (torch.sum(e_noise ** 2, dim=-1) + eps)
    return 10 * torch.log10(ratio + eps)


def si_snr_loss(estimate, target):
    """Negative mean SI-SNR, suitable for minimization."""
    return -si_snr(estimate, target).mean()


def multi_resolution_stft_loss(estimate, target, fft_sizes=(512, 1024, 2048),
                                hop_sizes=(100, 200, 400), win_sizes=(400, 800, 1600)):
    """Auxiliary perceptual-ish loss: L1 on log-magnitude spectrograms at
    multiple resolutions, encouraging spectral detail beyond time-domain SI-SNR.
    """
    loss = 0.0
    for n_fft, hop, win in zip(fft_sizes, hop_sizes, win_sizes):
        window = torch.hann_window(win, device=estimate.device)
        est_spec = torch.stft(estimate, n_fft=n_fft, hop_length=hop, win_length=win,
                               window=window, return_complex=True, center=True)
        tgt_spec = torch.stft(target, n_fft=n_fft, hop_length=hop, win_length=win,
                               window=window, return_complex=True, center=True)
        est_mag = torch.log(torch.abs(est_spec) + 1e-5)
        tgt_mag = torch.log(torch.abs(tgt_spec) + 1e-5)
        loss = loss + torch.nn.functional.l1_loss(est_mag, tgt_mag)
    return loss / len(fft_sizes)


def combined_loss(estimate, target, stft_weight=0.2):
    """SI-SNR (primary, matches DCCRN's original training objective) plus a
    smaller multi-resolution log-STFT term for extra spectral sharpness."""
    return si_snr_loss(estimate, target) + stft_weight * multi_resolution_stft_loss(estimate, target)
