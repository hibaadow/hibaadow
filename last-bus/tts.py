"""Synthesize each VO line with Kokoro (natural neural TTS), write timings JSON.

Narrator speed is calibrated so the narration averages TARGET_WPM.
"""
import json, os, subprocess, sys
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

sys.path.insert(0, os.path.dirname(__file__))
from script import LINES

SCR = os.environ["SCR"]
OUT = f"{SCR}/vo"
os.makedirs(OUT, exist_ok=True)
TARGET_WPM = 150
VOICE = {"narr": "am_michael", "whisper": "am_michael", "mum": "af_heart"}

kk = Kokoro(f"{SCR}/kokoro/kokoro-v1.0.onnx", f"{SCR}/kokoro/voices-v1.0.bin")


def trim(a, thr=0.01):
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    return a[max(0, idx[0] - 200): idx[-1] + 2400]


def synth(text, voice, speed):
    a, sr = kk.create(text, voice=VOICE[voice], speed=speed, lang="en-us")
    return trim(np.asarray(a, np.float32)), sr


# pass 1: measure natural narrator pace, then pick a speed for TARGET_WPM
words = dur = 0
for _, v, text, _ in LINES:
    if v == "narr":
        a, sr = synth(text, v, 1.0)
        words += len(text.split())
        dur += len(a) / sr
speed = TARGET_WPM / (words / dur * 60)
# pass 2: speed isn't perfectly linear, so measure again and correct
words = dur = 0
for _, v, text, _ in LINES:
    if v == "narr":
        a, sr = synth(text, v, speed)
        words += len(text.split())
        dur += len(a) / sr
speed = round(speed * TARGET_WPM / (words / dur * 60), 3)
print(f"narrator speed {speed}")

meta = []
for i, (start, voice, text, cap) in enumerate(LINES):
    sp = {"narr": speed, "whisper": speed * 1.2, "mum": 1.0}[voice]
    a, sr = synth(text, voice, sp)
    raw = f"{OUT}/raw_{i:02d}.wav"
    sf.write(raw, a, sr)
    fin = f"{OUT}/vo_{i:02d}.wav"
    if voice == "whisper":   # thin, breathy, close
        af = "aresample=44100,highpass=f=700,lowpass=f=6500,aecho=0.8:0.8:40|90:0.3|0.2"
    else:                    # natural voice, a touch of room
        af = "aresample=44100,aecho=0.8:0.5:40|80:0.06|0.03"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", af, "-ac", "1", fin], check=True)
    a, sr = sf.read(fin, dtype="float32")
    if voice == "whisper":
        env = np.convolve(np.abs(a), np.ones(400) / 400, mode="same")
        rng = np.random.default_rng(3)
        a = a * 0.6 + rng.normal(0, 1, len(a)).astype(np.float32) * env * 0.8
    np.save(f"{OUT}/vo_{i:02d}.npy", a)
    d = len(a) / sr
    meta.append({"i": i, "start": start, "dur": round(d, 3), "voice": voice, "text": text, "cap": cap})
    print(f"{i:02d} {start:5.1f} -> {start + d:5.2f}  ({d:.2f}s) {text}")

for a, b in zip(meta, meta[1:]):
    if a["start"] + a["dur"] > b["start"] - 0.1:
        print(f"  OVERLAP: line {a['i']} ends {a['start'] + a['dur']:.2f} next starts {b['start']}")
w = sum(len(m["text"].split()) for m in meta if m["voice"] == "narr")
d = sum(m["dur"] for m in meta if m["voice"] == "narr")
print(f"narrator: {w / d * 60:.0f} wpm")
json.dump(meta, open(f"{OUT}/vo.json", "w"), indent=1)
