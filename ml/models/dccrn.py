"""
DCCRN (Deep Complex Convolution Recurrent Network) for speech enhancement.

Reference: Hu et al., "DCCRN: Deep Complex Convolution Recurrent Network for
Phase-Aware Speech Enhancement", Interspeech 2020.

The network operates directly on the complex STFT of the noisy waveform.
A complex-valued U-Net (complex conv encoder + complex conv decoder with skip
connections) with a complex LSTM bottleneck predicts a complex ratio mask
(bounded with tanh), which is applied to the noisy spectrogram. The masked
spectrogram is inverted back to the time domain with ISTFT and trained with
an SI-SNR loss, so phase is preserved and no separate phase estimator is
needed.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Complex building blocks
# ---------------------------------------------------------------------------
class ComplexConv2d(nn.Module):
    """Complex 2D convolution implemented with two real convolutions.

    (a + ib) * (c + id) = (ac - bd) + i(ad + bc)
    """

    def __init__(self, in_ch, out_ch, kernel_size, stride=1, padding=0):
        super().__init__()
        self.real_conv = nn.Conv2d(in_ch, out_ch, kernel_size, stride, padding)
        self.imag_conv = nn.Conv2d(in_ch, out_ch, kernel_size, stride, padding)
        nn.init.xavier_uniform_(self.real_conv.weight)
        nn.init.xavier_uniform_(self.imag_conv.weight)
        nn.init.zeros_(self.real_conv.bias)
        nn.init.zeros_(self.imag_conv.bias)

    def forward(self, x_r, x_i):
        real = self.real_conv(x_r) - self.imag_conv(x_i)
        imag = self.real_conv(x_i) + self.imag_conv(x_r)
        return real, imag


class ComplexConvTranspose2d(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size, stride=1, padding=0, output_padding=0):
        super().__init__()
        self.real_conv = nn.ConvTranspose2d(
            in_ch, out_ch, kernel_size, stride, padding, output_padding=output_padding
        )
        self.imag_conv = nn.ConvTranspose2d(
            in_ch, out_ch, kernel_size, stride, padding, output_padding=output_padding
        )
        nn.init.xavier_uniform_(self.real_conv.weight)
        nn.init.xavier_uniform_(self.imag_conv.weight)
        nn.init.zeros_(self.real_conv.bias)
        nn.init.zeros_(self.imag_conv.bias)

    def forward(self, x_r, x_i):
        real = self.real_conv(x_r) - self.imag_conv(x_i)
        imag = self.real_conv(x_i) + self.imag_conv(x_r)
        return real, imag


class ComplexBatchNorm2d(nn.Module):
    """Naive complex batch-norm: independent BN on real/imag streams."""

    def __init__(self, num_features):
        super().__init__()
        self.bn_r = nn.BatchNorm2d(num_features)
        self.bn_i = nn.BatchNorm2d(num_features)

    def forward(self, x_r, x_i):
        return self.bn_r(x_r), self.bn_i(x_i)


class ComplexPReLU(nn.Module):
    def __init__(self, num_parameters=1):
        super().__init__()
        self.act_r = nn.PReLU(num_parameters)
        self.act_i = nn.PReLU(num_parameters)

    def forward(self, x_r, x_i):
        return self.act_r(x_r), self.act_i(x_i)


class ComplexLSTM(nn.Module):
    """Complex LSTM built from real LSTMs following complex multiplication
    rules for the linear projections. Operates on (B, T, F) real/imag pairs.
    """

    def __init__(self, input_size, hidden_size, num_layers=2, bidirectional=False):
        super().__init__()
        self.lstm_r = nn.LSTM(
            input_size, hidden_size, num_layers=num_layers,
            batch_first=True, bidirectional=bidirectional,
        )
        self.lstm_i = nn.LSTM(
            input_size, hidden_size, num_layers=num_layers,
            batch_first=True, bidirectional=bidirectional,
        )
        out_mul = 2 if bidirectional else 1
        self.hidden_size = hidden_size * out_mul

    def forward(self, x_r, x_i):
        # F_rr = LSTM_r(real), F_ir = LSTM_r(imag) etc. Approximate complex
        # matmul by running each real LSTM on both streams and combining.
        r2r, _ = self.lstm_r(x_r)
        r2i, _ = self.lstm_i(x_r)
        i2r, _ = self.lstm_r(x_i)
        i2i, _ = self.lstm_i(x_i)
        real = r2r - i2i
        imag = r2i + i2r
        return real, imag


# ---------------------------------------------------------------------------
# DCCRN model
# ---------------------------------------------------------------------------
class DCCRN(nn.Module):
    def __init__(
        self,
        n_fft=512,
        hop_length=100,
        win_length=400,
        channels=(16, 32, 64, 64, 128, 128),
        kernel_size=(5, 2),
        stride=(2, 1),
        lstm_hidden=128,
        lstm_layers=2,
        masking_mode="E",  # "E" = complex ratio mask, "R" = direct mapping
    ):
        super().__init__()
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.win_length = win_length
        self.masking_mode = masking_mode
        self.register_buffer("window", torch.hann_window(win_length), persistent=False)

        ch = [2] + list(channels)  # input has 1 complex channel -> real/imag split into 2 "features" but we keep 1 channel complex pair
        ch[0] = 1
        pad_f = (kernel_size[0] - 1) // 2

        self.encoders = nn.ModuleList()
        self.enc_bns = nn.ModuleList()
        self.enc_acts = nn.ModuleList()
        for i in range(len(channels)):
            self.encoders.append(
                ComplexConv2d(ch[i], ch[i + 1], kernel_size, stride, padding=(pad_f, 0))
            )
            self.enc_bns.append(ComplexBatchNorm2d(ch[i + 1]))
            self.enc_acts.append(ComplexPReLU())

        # Compute frequency dimension after the encoder stack to size the LSTM.
        # The DC bin is dropped before the encoder (see forward()), so the
        # encoder sees n_fft // 2 frequency bins, not n_fft // 2 + 1.
        freq_dim = n_fft // 2
        for _ in channels:
            freq_dim = (freq_dim + 2 * pad_f - kernel_size[0]) // stride[0] + 1
        self.freq_dim = freq_dim
        lstm_input = freq_dim * channels[-1]

        self.lstm = ComplexLSTM(lstm_input, lstm_hidden, num_layers=lstm_layers)
        self.lstm_proj_r = nn.Linear(self.lstm.hidden_size, lstm_input)
        self.lstm_proj_i = nn.Linear(self.lstm.hidden_size, lstm_input)

        dec_channels = list(reversed(channels)) + [1]
        self.decoders = nn.ModuleList()
        self.dec_bns = nn.ModuleList()
        self.dec_acts = nn.ModuleList()
        for i in range(len(channels)):
            in_ch = dec_channels[i] * 2  # skip connection concat (real&imag each doubled channel-wise)
            out_ch = dec_channels[i + 1]
            last = i == len(channels) - 1
            self.decoders.append(
                ComplexConvTranspose2d(
                    in_ch, out_ch, kernel_size, stride,
                    padding=(pad_f, 0), output_padding=(stride[0] - 1, 0),
                )
            )
            if not last:
                self.dec_bns.append(ComplexBatchNorm2d(out_ch))
                self.dec_acts.append(ComplexPReLU())
            else:
                self.dec_bns.append(None)
                self.dec_acts.append(None)

    # --------------------------- STFT helpers ---------------------------
    def stft(self, wav):
        spec = torch.stft(
            wav, n_fft=self.n_fft, hop_length=self.hop_length, win_length=self.win_length,
            window=self.window, return_complex=True, center=True,
        )
        return spec.real, spec.imag

    def istft(self, real, imag, length=None):
        spec = torch.complex(real, imag)
        wav = torch.istft(
            spec, n_fft=self.n_fft, hop_length=self.hop_length, win_length=self.win_length,
            window=self.window, center=True, length=length,
        )
        return wav

    # ----------------------------- forward -------------------------------
    def forward(self, noisy_wav):
        """noisy_wav: (B, T) float tensor in [-1, 1]. Returns enhanced wav (B, T)."""
        length = noisy_wav.shape[-1]
        spec_r, spec_i = self.stft(noisy_wav)  # (B, F, Tf)
        x_r = spec_r.unsqueeze(1)  # (B, 1, F, Tf)
        x_i = spec_i.unsqueeze(1)

        # drop the Nyquist bin so freq dim is even/tidy for strided convs
        x_r = x_r[:, :, 1:, :]
        x_i = x_i[:, :, 1:, :]

        skips = []
        for conv, bn, act in zip(self.encoders, self.enc_bns, self.enc_acts):
            x_r, x_i = conv(x_r, x_i)
            x_r, x_i = bn(x_r, x_i)
            x_r, x_i = act(x_r, x_i)
            skips.append((x_r, x_i))

        B, C, Fq, Tf = x_r.shape
        seq_r = x_r.permute(0, 3, 1, 2).reshape(B, Tf, C * Fq)
        seq_i = x_i.permute(0, 3, 1, 2).reshape(B, Tf, C * Fq)
        h_r, h_i = self.lstm(seq_r, seq_i)
        proj_r = self.lstm_proj_r(h_r) - self.lstm_proj_i(h_i)
        proj_i = self.lstm_proj_r(h_i) + self.lstm_proj_i(h_r)
        x_r = proj_r.reshape(B, Tf, C, Fq).permute(0, 2, 3, 1)
        x_i = proj_i.reshape(B, Tf, C, Fq).permute(0, 2, 3, 1)

        for idx, (deconv, bn, act) in enumerate(zip(self.decoders, self.dec_bns, self.dec_acts)):
            skip_r, skip_i = skips[-(idx + 1)]
            x_r = torch.cat([x_r, skip_r], dim=1)
            x_i = torch.cat([x_i, skip_i], dim=1)
            x_r, x_i = deconv(x_r, x_i)
            if bn is not None:
                x_r, x_i = bn(x_r, x_i)
                x_r, x_i = act(x_r, x_i)

        mask_r = x_r.squeeze(1)  # (B, F-1, Tf)
        mask_i = x_i.squeeze(1)

        # pad back the Nyquist bin (mask = 1, i.e. pass-through) that we dropped earlier
        pad = torch.zeros_like(mask_r[:, :1, :])
        mask_r = torch.cat([pad, mask_r], dim=1)
        mask_i = torch.cat([pad, mask_i], dim=1)

        if self.masking_mode == "E":
            mask_r = torch.tanh(mask_r)
            mask_i = torch.tanh(mask_i)
            enh_r = spec_r * mask_r - spec_i * mask_i
            enh_i = spec_r * mask_i + spec_i * mask_r
        else:  # direct complex spectral mapping
            enh_r, enh_i = mask_r, mask_i

        enhanced = self.istft(enh_r, enh_i, length=length)
        return enhanced
