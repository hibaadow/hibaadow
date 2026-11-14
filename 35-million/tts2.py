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
TARGET_WPM = float(os.environ.get("WPM", 155))
VOICE = {"narr": os.environ.get("NARR", "am_puck"), "agent": "am_onyx"}
ELLIPSIS_PAUSE = 0.38
REVEAL_PAUSE = 0.55            # lines whose "..." leads into a reveal
REVEALS = {20, 28}
# delivery per line: (speed multiplier, pitch in semitones, gain in dB)
MOODS = {
    0: (0.96, 0.0, 0), 1: (0.97, -0.3, 0), 2: (1.03, 0.4, 0.5), 3: (1.06, 1.3, 2.0), 4: (0.97, -0.4, 0),
    5: (1.07, 0.6, 1.0), 6: (0.94, -0.6, 0.5), 7: (1.05, 0.3, 0.5), 8: (0.94, -0.6, 0.5), 9: (1.0, 0.0, 0.5),
    10: (0.94, -0.6, 0.5), 11: (1.0, 0.2, 0.5), 12: (1.06, 0.9, 1.0), 13: (1.05, 0.6, 0.5), 14: (1.1, 1.2, 2.0),
    15: (1.12, 0.9, 1.5), 16: (1.02, 0.2, 0.5), 17: (0.97, -0.3, 0), 18: (1.0, 0.0, 0), 19: (0.96, -0.2, 0),
    20: (0.95, -0.6, 0), 21: (1.05, 0.5, 1.0), 22: (1.0, 0.0, 0), 23: (1.0, 0.6, 0.5), 24: (0.98, -0.2, 0),
    25: (0.95, 0.0, 0.5), 26: (0.95, -0.2, 0), 27: (1.03, 0.3, 0.5), 28: (0.9, -0.9, 0.5), 29: (1.0, 0.4, 0.5),
}
EMPH_PITCH, EMPH_GAIN = 1.0, 2.5      # lift on the chunk holding the lime-highlighted key word
QUESTION_RISE = 1.6                   # last chunk of a question
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


def shift(seg, semis):
    """pitch-shift a segment, same length (Rubber Band via ffmpeg, formants preserved)"""
    if abs(semis) < 0.05 or len(seg) < 400:
        return seg
    r = 2 ** (semis / 12)
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                        "-af", f"rubberband=pitch={r:.4f}:formant=preserved:pitchq=quality", "-f", "f32le", "-"],
                       input=seg.astype(np.float32).tobytes(), capture_output=True, check=True)
    out = np.frombuffer(p.stdout, np.float32)
    if len(out) < len(seg):
        out = np.pad(out, (0, len(seg) - len(out)))
    return out[:len(seg)]


def perform(a, times, i):
    """give the line its mood: pitch/level per chunk, lift on the key word, rise on questions"""
    _, semis, gain = MOODS.get(i, (1, 0, 0))
    out = a.copy()
    for k, (c0, c1, cap) in enumerate(times):
        s0, s1 = int(c0 * SR), int(c1 * SR)
        seg = a[s0:s1]
        p, g = semis, gain
        if cap and "*" in cap:
            p += EMPH_PITCH
            g += EMPH_GAIN
        is_last = k == len(times) - 1
        if is_last and LINES[i][1][-1][0].rstrip().endswith("?"):
            p += QUESTION_RISE
        seg = shift(seg, p) * (10 ** (g / 20))
        f = min(len(seg) // 4, int(0.008 * SR))
        if f > 0:
            seg[:f] *= np.linspace(0, 1, f)
            seg[-f:] *= np.linspace(1, 0, f)
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
            d += len(a) / SR
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
    return g if g <= 0.6 else 0.6 + (g - 0.6) * 0.55


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
