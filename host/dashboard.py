#!/usr/bin/env python3
"""Bench dashboard for one PTT recording.

Takes a stereo capture - channel 0 the primary mic, channel 1 the reference -
runs the two-mic noise canceller over it, and writes a self-contained HTML page
showing all three signals with the numbers that matter for tuning.

    python3 dashboard.py                             # newest wav in recordings/
    python3 dashboard.py recordings/ptt_1204.wav
    python3 dashboard.py --url http://192.168.4.1/both.wav
    python3 dashboard.py capture.wav --taps 64 --mu 0.5

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


def svg(sig, colour, w=1000, h=96):
    mid = h / 2
    scale = (h / 2 - 3) / FULL
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


CARD = """<section>
 <div class='hd'><div><h2>{title}</h2><em>{sub}</em></div>
  <button class='mini' onclick="p('{aid}')">play</button></div>
 {svg}
 <div class='grid'>{cells}</div>
 <audio id='{aid}' src='{uri}'></audio>
</section>"""


def cells(m):
    rows = [
        ("peak", f"{m['peak_db']:+.1f} dBFS", f"{m['peak']} / 32767"),
        ("rms", f"{m['rms_db']:+.1f} dBFS", "average level"),
        ("crest", f"{m['crest_db']:.1f} dB", "peak over rms"),
        ("noise floor", f"{m['floor_db']:+.1f} dBFS", "quietest 10% of frames"),
        ("snr", f"{m['snr_db']:.1f} dB", "loud frames over floor"),
        ("dc offset", f"{m['dc_pct']:+.2f} %", "of full scale"),
        ("zero crossings", f"{m['zcr']:.0f} /s", "rough brightness"),
        ("clipped", f"{m['clipped']}", "samples at the rail"),
    ]
    return "".join(f"<div><b>{v}</b><span>{k}</span><i>{note}</i></div>"
                   for k, v, note in rows)


PAGE = """<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>MicRelay - {short}</title><style>
body{{background:#14161a;color:#e6e6e6;font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px}}
main{{max-width:1060px;margin:0 auto}}
h1{{font-size:19px;margin:0 0 4px}}
p.sub{{color:#8b93a0;margin:0 0 18px;font-size:12px}}
.play{{background:#3d7dff;color:#fff;border:0;border-radius:8px;padding:13px 22px;font-size:15px;cursor:pointer;margin:0 0 20px}}
.play:hover{{background:#2f6ae8}}
section{{background:#1c1f26;border:1px solid #2a2f39;border-radius:10px;padding:14px 16px;margin:0 0 14px}}
.hd{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}}
h2{{font-size:14px;margin:0;font-weight:600}}
em{{color:#8b93a0;font-style:normal;font-size:12px}}
.mini{{background:#2a3140;color:#c9d1de;border:0;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer}}
.mini:hover{{background:#39424f}}
.wave{{width:100%;height:96px;display:block;margin:10px 0 4px;background:#111318;border-radius:6px}}
.axis{{stroke:#2a2f39;stroke-width:1}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin-top:8px}}
.grid div{{background:#171a20;border-radius:6px;padding:8px 10px}}
.grid b{{display:block;font-size:14px;font-variant-numeric:tabular-nums}}
.grid span{{display:block;color:#8b93a0;font-size:11px}}
.grid i{{display:block;color:#5d6673;font-size:10px;font-style:normal}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
td,th{{text-align:left;padding:5px 8px;border-bottom:1px solid #2a2f39}}
th{{color:#8b93a0;font-weight:500}}
td.n{{font-variant-numeric:tabular-nums}}
</style></head><body><main>
<h1>{short}</h1>
<p class='sub'>{facts}</p>
<button class='play' onclick="p('out')">&#9654;&nbsp; Play speaker output</button>
{cards}
<section><h2>Cancellation</h2><em>NLMS, {taps} taps, mu {mu}</em>
<table><tr><th>measure</th><th>original</th><th>cleaned</th><th>change</th></tr>
{rows}</table></section>
</main><script>
function p(id){{
 var a=document.getElementById(id);
 document.querySelectorAll('audio').forEach(function(x){{if(x!==a){{x.pause();x.currentTime=0}}}});
 if(a.paused){{a.play()}}else{{a.pause();a.currentTime=0}}
}}
</script></body></html>"""


def compare(a, b):
    rows = [
        ("rms level", f"{a['rms_db']:+.1f} dBFS", f"{b['rms_db']:+.1f} dBFS",
         f"{b['rms_db'] - a['rms_db']:+.1f} dB"),
        ("noise floor", f"{a['floor_db']:+.1f} dBFS", f"{b['floor_db']:+.1f} dBFS",
         f"{b['floor_db'] - a['floor_db']:+.1f} dB"),
        ("snr", f"{a['snr_db']:.1f} dB", f"{b['snr_db']:.1f} dB",
         f"{b['snr_db'] - a['snr_db']:+.1f} dB"),
        ("peak", f"{a['peak_db']:+.1f} dBFS", f"{b['peak_db']:+.1f} dBFS",
         f"{b['peak_db'] - a['peak_db']:+.1f} dB"),
        ("crest factor", f"{a['crest_db']:.1f} dB", f"{b['crest_db']:.1f} dB",
         f"{b['crest_db'] - a['crest_db']:+.1f} dB"),
    ]
    return "".join(f"<tr><td>{k}</td><td class='n'>{x}</td><td class='n'>{y}</td>"
                   f"<td class='n'>{z}</td></tr>" for k, x, y, z in rows)


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
    verdict = (f"rms {erle:.1f} dB below the original" if erle >= 0 else
               f"rms {abs(erle):.1f} dB ABOVE the original - not converging, "
               "try a lower --mu")
    print(f"noise reduction: {erle:.1f} dB rms, "
          f"snr {m_pri['snr_db']:.1f} -> {m_out['snr_db']:.1f} dB")

    cards = "".join([
        CARD.format(title="Original - as received", aid="orig",
                    sub="primary mic, channel 0", svg=svg(primary, "#6ea8ff"),
                    cells=cells(m_pri), uri=wav_uri(primary, rate)),
        CARD.format(title="Noise - reference", aid="noise",
                    sub="reference mic, channel 1", svg=svg(reference, "#ff9f5a"),
                    cells=cells(m_ref), uri=wav_uri(reference, rate)),
        CARD.format(title="Cleaned - speaker output", aid="out",
                    sub=f"NLMS output, {verdict}",
                    svg=svg(cleaned, "#5ddc9a"),
                    cells=cells(m_out), uri=wav_uri(cleaned, rate)),
    ])

    short = pathlib.Path(cap["name"]).name
    facts = (f"{seconds:.2f} s &middot; {rate} Hz &middot; 16-bit stereo &middot; "
             f"{len(primary)} frames &middot; {cap['size'] / 1024:.0f} KB &middot; "
             f"noise reduction {erle:.1f} dB")

    html = PAGE.format(short=short, facts=facts, cards=cards, taps=args.taps,
                       mu=args.mu, rows=compare(m_pri, m_out))

    out = pathlib.Path(args.out) if args.out else pathlib.Path(
        cap["name"] if not source.startswith("http") else "clip.wav").with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")

    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
