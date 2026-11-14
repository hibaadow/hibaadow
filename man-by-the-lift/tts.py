"""Voiceover for THE MAN BY THE LIFT, using the house delivery from voice/VOICE.md
(Kokoro, hurried ~180 wpm, quick breaths, pauses only at "...", no pitch effects), with a female narrator.

Writes $SCR/vo_lift/: vo_XX.npy (44.1 kHz), vo.json (start, dur, caption chunk times, shot).
"""
import json, os, subprocess, sys
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

sys.path.insert(0, os.path.dirname(__file__))
from script import ITEMS

SCR = os.environ["SCR"]
OUT = f"{SCR}/vo_lift"
os.makedirs(OUT, exist_ok=True)
TARGET_WPM = 180
VOICE = {"her": os.environ.get("HER", "af_heart"), "him": "am_onyx", "neigh": "am_puck", "recep": "af_sarah"}
FIXED_SPEED = {"him": 0.84, "neigh": 0.95, "recep": 0.98}
ELLIPSIS_PAUSE, REVEAL_PAUSE = 0.28, 0.55
BREATH = 0.24
DEFAULT_GAP = 0.22
SR = 24000
kk = Kokoro(f"{SCR}/kokoro/kokoro-v1.0.onnx", f"{SCR}/kokoro/voices-v1.0.bin")


def trim(a, thr=0.008, pad_in=0.02, pad_out=0.06):
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    return a[max(0, idx[0] - int(pad_in * SR)): idx[-1] + int(pad_out * SR)]


def phon_len(text, voice):
    _, ph, _ = kk._prepare(text, VOICE[voice], 1.0, "en-us", False, 0.25, 0.1)
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


def breath(seed):
    r = np.random.default_rng(seed)
    n = int(BREATH * SR)
    x = r.normal(0, 1, n).astype(np.float32)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X *= ((f > 500) & (f < 4000)) * (1 - np.abs(f - 1700) / 2600).clip(0, 1)
    x = np.fft.irfft(X, n).astype(np.float32)
    x /= np.max(np.abs(x)) + 1e-9
    return x * np.sin(np.linspace(0, np.pi, n)) ** 1.5 * 0.05


def synth(voice, chunks, speed, reveal):
    phrases, cur = [], []
    for sp, cap in chunks:
        cur.append((sp, cap))
        if sp.rstrip().endswith("..."):
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)
    audio, times, t = [], [], 0.0
    for pi, ph in enumerate(phrases):
        text = " ".join(sp for sp, _ in ph).replace("...", ",")
        a, _ = kk.create(text, voice=VOICE[voice], speed=speed, lang="en-us", sentence_pause=0.14, clause_pause=0.04)
        a = trim(np.asarray(a, np.float32))
        d = len(a) / SR
        w = [phon_len(sp, voice) for sp, _ in ph]
        cum = np.cumsum(w) / sum(w)
        g = gaps(a)
        bounds = [0.0]
        for c in cum[:-1]:
            est = c * d
            near = [(abs((g0 + g1) / 2 - est), (g0 + g1) / 2) for g0, g1 in g if abs((g0 + g1) / 2 - est) < 0.3]
            bounds.append(min(near)[1] if near else est)
        bounds.append(d)
        for k, (sp, cap) in enumerate(ph):
            times.append([round(t + bounds[k], 3), round(t + bounds[k + 1], 3), cap])
        audio.append(a)
        t += d
        if pi < len(phrases) - 1:
            p = REVEAL_PAUSE if reveal else ELLIPSIS_PAUSE
            audio.append(np.zeros(int(p * SR), np.float32))
            t += p
    return np.concatenate(audio), times


def nwords(chunks):
    return sum(len(sp.split()) for sp, _ in chunks)


# calibrate narrator to ~180 wpm, breaths and pauses included
speed = 0.95
for _ in range(3):
    w = d = 0
    for shot, v, ch, opt in ITEMS:
        if v == "her":
            a, _ = synth(v, ch, speed, opt.get("reveal"))
            w += nwords(ch)
            d += len(a) / SR + (BREATH + 0.04 if opt.get("breath") else 0)
    wpm = w / d * 60
    speed *= TARGET_WPM / wpm
    print(f"wpm {wpm:.0f} -> speed {speed:.3f}")

meta, t = [], 0.3
for i, (shot, v, ch, opt) in enumerate(ITEMS):
    sp = speed if v == "her" else FIXED_SPEED[v]
    a, times = synth(v, ch, sp, opt.get("reveal"))
    if opt.get("breath"):
        pre = int((BREATH + 0.04) * SR)
        a = np.concatenate([breath(i), np.zeros(pre - int(BREATH * SR), np.float32), a])
        times = [[round(c0 + BREATH + 0.04, 3), round(c1 + BREATH + 0.04, 3), cap] for c0, c1, cap in times]
    raw = f"{OUT}/raw_{i:02d}.wav"
    sf.write(raw, a, SR)
    fin = f"{OUT}/vo_{i:02d}.wav"
    af = "aresample=44100,aecho=0.8:0.5:40|80:0.06|0.03"
    if v == "him":   # slightly closer, darker room on the man
        af = "aresample=44100,lowpass=f=6500,aecho=0.8:0.6:50|110:0.12|0.07"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", af, "-ac", "1", fin], check=True)
    b, _ = sf.read(fin, dtype="float32")
    np.save(f"{OUT}/vo_{i:02d}.npy", b)
    if i > 0:
        t += opt.get("pre", 0.35 if opt.get("chapter") else DEFAULT_GAP)
    dur = len(a) / SR
    meta.append({"i": i, "shot": shot, "voice": v, "start": round(t, 3), "dur": round(dur, 3), "chunks": times,
                 "chapter": opt.get("chapter"),
                 "text": " ".join(s for s, _ in ch)})
    t += dur
json.dump(meta, open(f"{OUT}/vo.json", "w"), indent=1)
hw = sum(nwords(c) for s, v, c, o in ITEMS if v == "her")
hd = sum(m["dur"] for m in meta if m["voice"] == "her")
print(f"narrator {hw / hd * 60:.0f} wpm; total VO ends {t:.1f}s")
for m in meta:
    print(f"{m['i']:02d} {m['start']:6.2f} +{m['dur']:.2f} [{m['shot']}] {m['voice']}: {m['text']}")
