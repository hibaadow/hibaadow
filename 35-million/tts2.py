"""Voiceover v2: Kokoro neural TTS at a natural ~155 wpm, pauses only at "...", captions synced
to the audio, and a time map that tightens the edit to the faster read.

Outputs in $SCR/vo35n/: vo_XX.npy (44.1 kHz), vo.json (new starts + caption chunk times), timemap.json
"""
import json, os, subprocess, sys
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

sys.path.insert(0, os.path.dirname(__file__))
from script2 import LINES

SCR = os.environ["SCR"]
OLD = json.load(open(f"{SCR}/vo35/vo.json"))
OUT = f"{SCR}/vo35n"
os.makedirs(OUT, exist_ok=True)
TARGET_WPM = float(os.environ.get("WPM", 180))
VOICE = {"narr": os.environ.get("NARR", "am_puck"), "agent": "am_onyx"}
ELLIPSIS_PAUSE = 0.28
REVEAL_PAUSE = 0.42            # lines whose "..." leads into a reveal
REVEALS = {20, 28}
OLD_END = 132.0

kk = Kokoro(f"{SCR}/kokoro/kokoro-v1.0.onnx", f"{SCR}/kokoro/voices-v1.0.bin")
SR = 24000


def trim(a, thr=0.008, pad_in=0.02, pad_out=0.06):
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    return a[max(0, idx[0] - int(pad_in * SR)): idx[-1] + int(pad_out * SR)]


def phon_len(text, voice):
    _, ph, _ = kk._prepare(text, VOICE[voice], 1.0, "en-us", False, 0.25, 0.1)
    return max(1, len(ph.replace(" ", "")))


def gaps(a, min_len=0.05):
    """silent stretches (start, end) in seconds"""
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


def synth_line(voice, chunks, speed, reveal):
    # phrases split at "..."
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
        text = " ".join(sp for sp, _ in ph).replace("!...", "!").replace("...", ",")
        a, sr = kk.create(text, voice=VOICE[voice], speed=speed, lang="en-us",
                          sentence_pause=0.14, clause_pause=0.04)
        a = trim(np.asarray(a, np.float32))
        d = len(a) / SR
        # chunk boundaries: by phoneme share, snapped to real pauses in the audio
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



# delivery per line: (speed multiplier, gain dB). No pitch processing: Puck's own voice, untouched.
# Pace follows what the character is going through: uneasy -> rushed -> sprinting -> slowing on the dark reveals.
MOODS = {i: (1.0, 1.0) for i in range(30)}          # the escape-scene delivery, everywhere
MOODS.update({6: (0.96, 0.5), 8: (0.96, 0.5), 10: (0.96, 0.5),   # rules: a hair more deliberate
              14: (1.04, 1.5), 15: (1.04, 1.5),                    # the run itself
              20: (0.93, 0.5), 28: (0.92, 0.5)})                   # the two big reveals
EMPH_GAIN = 2.0                 # key-word phrase a touch louder (volume only)
BREATH_BEFORE = {2, 3, 5, 7, 9, 11, 12, 13, 14, 15, 16, 17, 21, 22, 23, 27}     # quick inhale before the panicked lines


def breath(dur=0.24, seed=0):
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    x = r.normal(0, 1, n).astype(np.float32)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X *= ((f > 500) & (f < 3500)) * (1 - np.abs(f - 1500) / 2500).clip(0, 1)
    x = np.fft.irfft(X, n).astype(np.float32)
    x /= np.max(np.abs(x)) + 1e-9
    e = np.sin(np.linspace(0, np.pi, n)) ** 1.5
    return x * e * 0.05


def perform(a, times, i):
    """volume-only shaping: line level + slightly louder key-word phrase"""
    _, gain = MOODS.get(i, (1, 0))
    out = a * (10 ** (gain / 20))
    for c0, c1, cap in times:
        if cap and "*" in cap:
            s0, s1 = int(c0 * SR), int(c1 * SR)
            seg = out[s0:s1] * (10 ** (EMPH_GAIN / 20))
            f = min(len(seg) // 4, int(0.01 * SR))
            if f > 0:
                ramp = np.ones(len(seg))
                ramp[:f] = np.linspace(1 / (10 ** (EMPH_GAIN / 20)), 1, f)
                ramp[-f:] = np.linspace(1, 1 / (10 ** (EMPH_GAIN / 20)), f)
                seg = out[s0:s1] * (10 ** (EMPH_GAIN / 20)) * ramp
            out[s0:s1] = seg
    return out


def words(chunks):
    return sum(len(sp.split()) for sp, _ in chunks)


# ---- calibrate narrator speed to TARGET_WPM (pauses included)
speed = 0.95
for _ in range(3):
    w = d = 0
    for i, (v, ch) in enumerate(LINES):
        if v == "narr":
            a, _ = synth_line(v, ch, speed * MOODS.get(i, (1,))[0], i in REVEALS)
            w += words(ch)
            d += len(a) / SR + (0.28 if i in BREATH_BEFORE else 0)
    wpm = w / d * 60
    speed *= TARGET_WPM / wpm
    print(f"wpm {wpm:.0f} -> speed {speed:.3f}")
agent_speed = 0.765   # agent (Onyx) keeps the delivery from the approved sample

# ---- synthesize
meta = []
for i, (v, ch) in enumerate(LINES):
    a, times = synth_line(v, ch, agent_speed if v == "agent" else speed * MOODS.get(i, (1,))[0], i in REVEALS)
    if v == "narr":
        a = perform(a, times, i)
        if i in BREATH_BEFORE:
            b = breath(0.24, i)
            pad = int(0.04 * SR)
            a = np.concatenate([b, np.zeros(pad, np.float32), a])
            times = [[round(c0 + 0.28, 3), round(c1 + 0.28, 3), cap] for c0, c1, cap in times]
    raw = f"{OUT}/raw_{i:02d}.wav"
    sf.write(raw, a, SR)
    fin = f"{OUT}/vo_{i:02d}.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", "aresample=44100,aecho=0.8:0.5:40|80:0.06|0.03",
                    "-ac", "1", fin], check=True)
    b, _ = sf.read(fin, dtype="float32")
    np.save(f"{OUT}/vo_{i:02d}.npy", b)
    meta.append({"i": i, "voice": v, "dur": round(len(a) / SR, 3), "chunks": times,
                 "text": " ".join(sp for sp, _ in ch)})

# ---- new timeline: lines keep their order and the scene they sit in; gaps between lines tighten
def new_gap(g):
    return g if g <= 0.5 else 0.5 + (g - 0.5) * 0.5


anchors = [(0.0, 0.0)]
S = OLD[0]["start"]
anchors.append((OLD[0]["start"], S))
for i, m in enumerate(meta):
    o = OLD[i]
    m["start"] = round(S, 3)
    o_end = o["start"] + o["dur"]
    n_end = S + m["dur"]
    anchors.append((o_end, n_end))
    if i + 1 < len(meta):
        g = OLD[i + 1]["start"] - o_end
        S = n_end + new_gap(max(g, 0.08))
        anchors.append((OLD[i + 1]["start"], S))
tail = OLD_END - (OLD[-1]["start"] + OLD[-1]["dur"])
anchors.append((OLD_END, n_end + tail))
anchors = sorted(set(anchors))
json.dump(meta, open(f"{OUT}/vo.json", "w"), indent=1)
json.dump(anchors, open(f"{OUT}/timemap.json", "w"))
nw = sum(words(ch) for v, ch in LINES if v == "narr")
nd = sum(m["dur"] for m in meta if m["voice"] == "narr")
print(f"narrator {nw / nd * 60:.0f} wpm (pauses included); agent speed {agent_speed:.3f}")
print(f"new length {anchors[-1][1]:.1f}s (was {OLD_END:.0f}s)")
for m in meta:
    print(f"{m['i']:02d} {m['start']:6.2f} +{m['dur']:.2f}  {m['text']}")
