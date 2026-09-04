#!/usr/bin/env python3
"""Bench dashboard for one PTT recording.

Takes a stereo capture - channel 0 the primary mic, channel 1 the reference -
runs the two-mic noise canceller over it, and writes a self-contained HTML page
showing all three signals with the numbers that matter for tuning.

    python3 dashboard.py                             # newest wav in recordings/
    python3 dashboard.py recordings/ptt_1204.wav
    python3 dashboard.py --url http://192.168.4.1/both.wav
    python3 dashboard.py capture.wav --taps 64 --mu 0.5

The page is sized to one viewport. The waveforms take whatever vertical space
is left after the header and the table, so it fits a laptop or a projector
without scrolling - and if a window really is too short for the table, it
scrolls rather than quietly hiding the last rows.

Standard library only: no numpy, no plotting library, no web framework. The
waveforms are inline SVG and the players are data URIs, so the page is one file
that opens anywhere - including on the Pi with no display packages installed.
"""

import argparse
import base64
import io
import math
import pathlib
import sys
import time
import wave
import webbrowser
from array import array
from operator import mul
from urllib.request import urlopen

FULL = 32768.0          # 16-bit full scale
FRAME_MS = 20           # analysis frame for the noise-floor / SNR estimates


# --------------------------------------------------------------------- input

def load(source):
    """Returns (rate, primary, reference). Accepts a path or an http URL."""
    if source.startswith("http://") or source.startswith("https://"):
        with urlopen(source, timeout=10) as r:
            blob = io.BytesIO(r.read())
        name, size = source, len(blob.getvalue())
        handle = wave.open(blob, "rb")
    else:
        p = pathlib.Path(source)
        name, size = str(p), p.stat().st_size
        handle = wave.open(str(p), "rb")

    with handle as w:
        if w.getsampwidth() != 2:
            sys.exit(f"{name}: expected 16-bit samples, got {w.getsampwidth() * 8}-bit")
        rate, channels, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)

    if channels != 2:
        sys.exit(f"{name}: this is a {channels}-channel file. The canceller needs "
                 "both mics - use the stereo capture (both.wav, or receive.py's "
                 "output), not a single-channel export.")

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":          # wav is little-endian, array is native
        samples.byteswap()

    return {
        "name": name, "size": size, "rate": rate, "frames": n,
        "primary": samples[0::2], "reference": samples[1::2],
    }


# ----------------------------------------------------------------- canceller

def nlms(desired, reference, taps, mu, eps=1e-6):
    """Normalised LMS. The reference mic hears the noise but (ideally) not the
    speech, so whatever the filter can predict from it is noise and what is left
    over is the wanted signal. That leftover error signal IS the output.

    Written with map/zip rather than index loops - it keeps the per-sample work
    down in C and makes a 10 s clip take about a second in plain CPython.
    """
    w = [0.0] * taps
    buf = [0.0] * taps
    out = array("h", bytes(2 * len(desired)))
    power = 0.0

    for i, d in enumerate(desired):
        x = reference[i]
        # Sliding-window power, refreshed periodically so the running update
        # cannot drift after a hundred thousand additions.
        if i % 4096 == 0:
            power = sum(map(mul, buf, buf))
        else:
            power += x * x - buf[-1] * buf[-1]
        buf = [x] + buf[:-1]

        e = d - sum(map(mul, w, buf))
        g = mu * e / (power + x * x + eps)
        w = [wk + g * bk for wk, bk in zip(w, buf)]

        out[i] = 32767 if e > 32767 else (-32768 if e < -32768 else int(e))

    return out


# ------------------------------------------------------------------- metrics

def db(x):
    return -120.0 if x <= 1e-9 else 20.0 * math.log10(x)


def frame_rms(sig, rate):
    """RMS of every FRAME_MS block, sorted. The quiet end is the noise floor,
    the loud end is the signal - the gap between them is the usable SNR."""
    step = max(1, rate * FRAME_MS // 1000)
    vals = []
    for a in range(0, len(sig) - step + 1, step):
        chunk = sig[a:a + step]
        vals.append(math.sqrt(sum(map(mul, chunk, chunk)) / step))
    vals.sort()
    return vals


def metrics(sig, rate):
    n = len(sig)
    if n == 0:
        return {}

    peak = max(max(sig), -min(sig))
    rms = math.sqrt(sum(map(mul, sig, sig)) / n)
    dc = sum(sig) / n
    clipped = sum(1 for v in sig if v >= 32767 or v <= -32768)

    crossings = sum(1 for a, b in zip(sig, sig[1:]) if (a < 0) != (b < 0))

    q = frame_rms(sig, rate)
    floor = q[len(q) // 10] if q else 0.0            # 10th percentile
    loud = q[len(q) * 9 // 10] if q else 0.0         # 90th percentile

    return {
        "peak": peak,
        "peak_db": db(peak / FULL),
        "rms_db": db(rms / FULL),
        "crest_db": db(peak / rms) if rms > 0 else 0.0,
        "dc_pct": 100.0 * dc / FULL,
        "clipped": clipped,
        "zcr": crossings * rate / n if n else 0.0,
        "floor_db": db(floor / FULL),
        "snr_db": db(loud / floor) if floor > 0 else 0.0,
        "rms": rms,
    }


# --------------------------------------------------------------------- render

def envelope(sig, cols):
    """Min/max per pixel column - the only honest way to draw 160k samples in
    1000 pixels. Averaging would hide exactly the transients we care about."""
    n = len(sig)
    out = []
    for c in range(cols):
        a = n * c // cols
        b = max(a + 1, n * (c + 1) // cols)
        chunk = sig[a:b]
        out.append((min(chunk), max(chunk)))
    return out


def svg(sig, colour, w=1000, h=100):
    """viewBox coordinates only - CSS decides the drawn height, so the same
    markup fills whatever the viewport has left over."""
    mid = h / 2
    scale = (h / 2 - 2) / FULL
    d = []
    for x, (lo, hi) in enumerate(envelope(sig, w)):
        y1 = mid - hi * scale
        y2 = mid - lo * scale
        if y2 - y1 < 0.7:
            y2 = y1 + 0.7
        d.append(f"M{x} {y1:.1f}V{y2:.1f}")
    return (f"<svg viewBox='0 0 {w} {h}' preserveAspectRatio='none' class='wave'>"
            f"<line x1='0' y1='{mid}' x2='{w}' y2='{mid}' class='axis'/>"
            f"<path d='{''.join(d)}' stroke='{colour}' fill='none' stroke-width='1'/>"
            f"</svg>")


def wav_uri(sig, rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        data = array("h", sig)
        if sys.byteorder == "big":
            data.byteswap()
        w.writeframes(data.tobytes())
    return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode()


ROW = """<div class='row'>
 <div class='lbl'><b>{title}</b><em>{sub}</em>
  <button class='mini' onclick="p('{aid}')">play</button></div>
 {svg}<audio id='{aid}' src='{uri}'></audio></div>"""

# label, metrics key, value format, delta format, and whether a rise in that
# delta is unambiguously an improvement. Only SNR qualifies: a lower peak or a
# lower zero-crossing rate might be the canceller working or the canceller
# eating the speech, so those deltas stay neutral rather than reassuring green.
ROWS = [
    ("peak",            "peak",     "{:.0f}",       "{:+.0f}",     ""),
    ("peak level",      "peak_db",  "{:+.1f} dBFS", "{:+.1f} dB",  ""),
    ("rms level",       "rms_db",   "{:+.1f} dBFS", "{:+.1f} dB",  ""),
    ("crest factor",    "crest_db", "{:.1f} dB",    "{:+.1f} dB",  ""),
    ("noise floor",     "floor_db", "{:+.1f} dBFS", "{:+.1f} dB",  ""),
    ("snr",             "snr_db",   "{:.1f} dB",    "{:+.1f} dB",  " good"),
    ("dc offset",       "dc_pct",   "{:+.2f} %",    "{:+.2f} %",   ""),
    ("zero crossings",  "zcr",      "{:.0f} /s",    "{:+.0f} /s",  ""),
    ("clipped samples", "clipped",  "{:.0f}",       "{:+.0f}",     ""),
]


def table(pri, ref, out):
    body = []
    for label, key, fmt, dfmt, cls in ROWS:
        delta = out[key] - pri[key]
        good = cls if delta > 0 else ""
        body.append(
            f"<tr><td>{label}</td>"
            f"<td class='n'>{fmt.format(pri[key])}</td>"
            f"<td class='n dim'>{fmt.format(ref[key])}</td>"
            f"<td class='n'>{fmt.format(out[key])}</td>"
            f"<td class='n d{good}'>{dfmt.format(delta)}</td></tr>")
    return "".join(body)


PAGE = """<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>MicRelay - {short}</title><style>
*{{box-sizing:border-box}}
html,body{{height:100%}}
body{{background:#14161a;color:#e6e6e6;font:13px/1.45 system-ui,sans-serif;
 margin:0;padding:12px 16px;display:flex;flex-direction:column;gap:9px;overflow:auto}}
header{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex:none}}
h1{{font-size:15px;margin:0;font-weight:600}}
.facts{{color:#8b93a0;font-size:11.5px}}
.play{{background:#3d7dff;color:#fff;border:0;border-radius:7px;padding:9px 16px;
 font-size:13px;cursor:pointer;white-space:nowrap;flex:none}}
.play:hover{{background:#2f6ae8}}
.waves{{flex:1 1 auto;display:flex;flex-direction:column;gap:8px;min-height:186px}}
.row{{flex:1 1 0;min-height:56px;display:flex;align-items:stretch;gap:10px;
 background:#1c1f26;border:1px solid #2a2f39;border-radius:8px;padding:7px 9px}}
.lbl{{width:132px;flex:none;display:flex;flex-direction:column;justify-content:center;gap:1px}}
.lbl b{{font-size:12.5px}}
em{{color:#8b93a0;font-style:normal;font-size:10.5px;line-height:1.3}}
.mini{{background:#2a3140;color:#c9d1de;border:0;border-radius:5px;padding:3px 9px;
 font-size:10.5px;cursor:pointer;margin-top:4px;align-self:flex-start}}
.mini:hover{{background:#39424f}}
.wave{{flex:1 1 auto;min-width:0;height:100%;background:#111318;border-radius:5px}}
.axis{{stroke:#2a2f39;stroke-width:1}}
table{{flex:none;width:100%;border-collapse:collapse;font-size:11.5px}}
td,th{{text-align:right;padding:3px 8px;border-bottom:1px solid #23272f;white-space:nowrap}}
td:first-child,th:first-child{{text-align:left;color:#8b93a0}}
th{{color:#8b93a0;font-weight:500;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}}
td.n{{font-variant-numeric:tabular-nums}}
td.dim{{color:#8b93a0}}
td.d{{color:#c9d1de}}
td.d.good{{color:#5ddc9a}}
tr:last-child td{{border-bottom:0}}
</style></head><body>
<header>
 <div><h1>{short}</h1><div class='facts'>{facts}</div></div>
 <button class='play' onclick="p('out')">&#9654;&nbsp; Play speaker output</button>
</header>
<div class='waves'>{rows}</div>
<table>
<tr><th>measure</th><th>original</th><th>reference</th><th>cleaned</th><th>change</th></tr>
{cells}
</table>
<script>
function p(id){{
 var a=document.getElementById(id);
 document.querySelectorAll('audio').forEach(function(x){{if(x!==a){{x.pause();x.currentTime=0}}}});
 if(a.paused){{a.play()}}else{{a.pause();a.currentTime=0}}
}}
</script></body></html>"""


# ---------------------------------------------------------------------- main

def newest_wav(folder):
    wavs = sorted(pathlib.Path(folder).glob("*.wav"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not wavs:
        sys.exit(f"no .wav files in {folder}/ - record one first")
    return str(wavs[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="wav file, or a folder to take the newest from")
    ap.add_argument("--url", help="pull the clip straight off the node, e.g. http://192.168.4.1/both.wav")
    ap.add_argument("--taps", type=int, default=48, help="canceller length (default 48)")
    ap.add_argument("--mu", type=float, default=0.3, help="adaptation rate 0..1 (default 0.3)")
    ap.add_argument("--out", help="where to write the page (default alongside the wav)")
    ap.add_argument("--no-open", action="store_true", help="do not launch a browser")
    args = ap.parse_args()

    source = args.url or args.source or "recordings"
    if not source.startswith("http") and pathlib.Path(source).is_dir():
        source = newest_wav(source)

    cap = load(source)
    rate, primary, reference = cap["rate"], cap["primary"], cap["reference"]
    if not primary:
        sys.exit(f"{cap['name']}: no audio frames in the file")
    seconds = len(primary) / rate
    print(f"{cap['name']}: {seconds:.2f} s, {rate} Hz, {len(primary)} frames")

    t0 = time.time()
    cleaned = nlms(primary, reference, args.taps, args.mu)
    print(f"nlms: {args.taps} taps, mu {args.mu}, {time.time() - t0:.1f} s")

    m_pri = metrics(primary, rate)
    m_ref = metrics(reference, rate)
    m_out = metrics(cleaned, rate)

    # Positive means the output is quieter than what came in, i.e. the filter
    # removed something. Negative means it is diverging - say so plainly.
    erle = db(m_pri["rms"] / m_out["rms"]) if m_out["rms"] > 0 else 0.0
    verdict = (f"{erle:.1f} dB below the original" if erle >= 0 else
               f"{abs(erle):.1f} dB ABOVE the original - not converging, lower --mu")
    print(f"noise reduction: {erle:.1f} dB rms, "
          f"snr {m_pri['snr_db']:.1f} -> {m_out['snr_db']:.1f} dB")

    rows = "".join([
        ROW.format(title="Original", sub="primary mic, ch 0", aid="orig",
                   svg=svg(primary, "#6ea8ff"), uri=wav_uri(primary, rate)),
        ROW.format(title="Noise", sub="reference mic, ch 1", aid="noise",
                   svg=svg(reference, "#ff9f5a"), uri=wav_uri(reference, rate)),
        ROW.format(title="Cleaned", sub="speaker output", aid="out",
                   svg=svg(cleaned, "#5ddc9a"), uri=wav_uri(cleaned, rate)),
    ])

    short = pathlib.Path(cap["name"]).name
    facts = (f"{seconds:.2f} s &middot; {rate} Hz &middot; 16-bit stereo &middot; "
             f"{cap['size'] / 1024:.0f} KB &middot; NLMS {args.taps} taps, "
             f"mu {args.mu} &middot; output {verdict}")

    html = PAGE.format(short=short, facts=facts, rows=rows,
                       cells=table(m_pri, m_ref, m_out))

    out = pathlib.Path(args.out) if args.out else pathlib.Path(
        cap["name"] if not source.startswith("http") else "clip.wav").with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")

    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
