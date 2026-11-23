"""Voiceover for THE AGENCY: house girl voice (Kokoro af_heart). Each line read in one continuous
pass (no stitched phrases, no added breaths or gain jumps) at a natural ~168 wpm; Daniel = am_onyx. Captions synced by phoneme share,
snapped to real silences. Writes $SCR/vo2am/vo_XX.npy and timeline.json (line starts, caption chunk times)."""
import json, os, subprocess, sys
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from script import LINES

SCR = os.environ["SCR"]
OUT = f"{SCR}/voagency"
os.makedirs(OUT, exist_ok=True)
TARGET_WPM = 185
SR = 24000
kk = Kokoro(f"{SCR}/kokoro/kokoro-v1.0.onnx", f"{SCR}/kokoro/voices-v1.0.bin")
VOICE = "af_heart"
MOODS = {10: (0.94, 0), 12: (0.95, 0), 17: (0.92, 0)}   # slower on the reveals


def trim(a, thr=0.008):
    idx = np.where(np.abs(a) > thr)[0]
    return a if len(idx) == 0 else a[max(0, idx[0] - int(0.02 * SR)): idx[-1] + int(0.06 * SR)]


def phon_len(text):
    _, ph, _ = kk._prepare(text, VOICE, 1.0, "en-us", False, 0.25, 0.1)
    return max(1, len(ph.replace(" ", "")))


def gaps(a, min_len=0.05):
    env = np.convolve(np.abs(a), np.ones(240) / 240, mode="same")
    quiet = env < 0.012
    out, i, n = [], 0, len(a)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) / SR >= min_len:
                out.append((i / SR, j / SR))
            i = j
        else:
            i += 1
    return out


def synth_line(chunks, speed, reveal, voice=VOICE):
    """one continuous read per line (no stitching): Kokoro handles the flow; "..." becomes a comma pause"""
    text = " ".join(sp for sp, _ in chunks).replace("!...", "!").replace("...", ",")
    a, _ = kk.create(text, voice=voice, speed=speed, lang="en-us", sentence_pause=0.24, clause_pause=0.1)
    a = trim(np.asarray(a, np.float32)); d = len(a) / SR
    w = [phon_len(sp) for sp, _ in chunks]; cum = np.cumsum(w) / sum(w); g = gaps(a)
    bounds = [0.0]
    for c in cum[:-1]:
        est = c * d
        near = [(abs((g0 + g1) / 2 - est), (g0 + g1) / 2) for g0, g1 in g if abs((g0 + g1) / 2 - est) < 0.35]
        bounds.append(min(near)[1] if near else est)
    bounds.append(d)
    return a, [[round(bounds[k], 3), round(bounds[k + 1], 3), cap] for k, (sp, cap) in enumerate(chunks)]


def breath(dur=0.24, seed=0):
    r = np.random.default_rng(seed); n = int(dur * SR)
    X = np.fft.rfft(r.normal(0, 1, n)); f = np.fft.rfftfreq(n, 1 / SR)
    X *= ((f > 500) & (f < 3500)) * (1 - np.abs(f - 1500) / 2500).clip(0, 1)
    x = np.fft.irfft(X, n).astype(np.float32); x /= np.max(np.abs(x)) + 1e-9
    return x * np.sin(np.linspace(0, np.pi, n)) ** 1.5 * 0.05


def emphasize(a, times, gain_db):
    out = a * (10 ** (gain_db / 20))
    for c0, c1, cap in times:
        if cap and ("*" in cap or "_" in cap):
            s0, s1 = int(c0 * SR), min(len(out), int(c1 * SR)); g = 10 ** (2.0 / 20); n = s1 - s0
            if n > 8:
                f = min(n // 4, int(0.01 * SR)); ramp = np.full(n, g); ramp[:f] = np.linspace(1, g, f); ramp[-f:] = np.linspace(g, 1, f)
                out[s0:s1] *= ramp
    return out


words = lambda ch: sum(len(sp.split()) for sp, _ in ch)
speed = 1.0
for _ in range(5):
    w = d = 0
    for i, ln in enumerate(LINES):
        if len(ln) > 2: continue
        a, _t = synth_line(ln[1], speed * MOODS.get(i, (1, 0))[0], False)
        w += words(ln[1]); d += len(a) / SR
    wpm = w / d * 60; speed *= (TARGET_WPM / wpm) ** 0.6
    print(f"wpm {wpm:.0f} -> speed {speed:.3f}")

meta, S = [], 0.5
for i, ln in enumerate(LINES):
    scene, ch = ln[0], ln[1]
    if len(ln) > 2:
        a, times = synth_line(ch, 1.08, False, voice="am_onyx")
    else:
        a, times = synth_line(ch, speed * MOODS.get(i, (1, 0))[0], False)
    sf.write(f"{OUT}/raw_{i:02d}.wav", a, SR)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", f"{OUT}/raw_{i:02d}.wav", "-af", "aresample=44100,aecho=0.8:0.5:40|80:0.06|0.03",
                    "-ac", "1", f"{OUT}/vo_{i:02d}.wav"], check=True)
    b, _ = sf.read(f"{OUT}/vo_{i:02d}.wav", dtype="float32"); np.save(f"{OUT}/vo_{i:02d}.npy", b)
    dur = len(a) / SR
    meta.append({"i": i, "scene": scene, "start": round(S, 3), "dur": round(dur, 3),
                 "chunks": [[round(S + c0, 3), round(S + c1, 3), cap] for c0, c1, cap in times],
                 "text": " ".join(sp for sp, _ in ch), "voice": "daniel" if len(ln) > 2 else "narr"})
    nxt = LINES[i + 1][0] if i + 1 < len(LINES) else None
    S += dur + (0.5 if nxt in ("broke", "noshow", "dm", "dig", "police", "arrest", "end") else 0.25)
end = meta[-1]["start"] + meta[-1]["dur"] + 4.0
json.dump({"lines": meta, "duration": round(end, 2)}, open(os.path.join(HERE, "timeline.json"), "w"), indent=1)
print(f"narrator {sum(words(l[1]) for l in LINES) / sum(m['dur'] for m in meta) * 60:.0f} wpm; total {end:.1f}s")
for m in meta:
    print(f"{m['i']:02d} {m['start']:6.2f} +{m['dur']:.2f} {m['scene']:8s} {m['text']}")
