"""Synthesize each VO line with Piper, post-process (low, ominous), write timings JSON."""
import json, os, subprocess, sys, wave
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from script import LINES

SCR = os.environ["SCR"]
VOICES = {
    "alan": f"{SCR}/voices/vits-piper-en_GB-alan-medium/en_GB-alan-medium.onnx",
    "jenny": f"{SCR}/voices/vits-piper-en_GB-jenny_dioco-medium/en_GB-jenny_dioco-medium.onnx",
}
OUT = f"{SCR}/vo"
os.makedirs(OUT, exist_ok=True)
PIPER = f"{SCR}/venv/bin/piper"


def read_wav(p):
    with wave.open(p) as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    return a, sr


def trim(a, thr=0.01):
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    return a[max(0, idx[0] - 200): idx[-1] + 2000]


meta = []
for i, (start, voice, text, cap) in enumerate(LINES):
    raw = f"{OUT}/raw_{i:02d}.wav"
    fin = f"{OUT}/vo_{i:02d}.wav"
    model = VOICES["jenny" if voice == "jenny" else "alan"]
    ls = {"alan": "1.22", "jenny": "1.12", "whisper": "1.35"}[voice]
    subprocess.run([PIPER, "-m", model, "-f", raw, "--length-scale", ls,
                    "--noise-scale", "0.55", "--noise-w-scale", "0.7"],
                   input=text.encode(), check=True, capture_output=True)
    # low + slightly ominous: drop pitch ~9% keeping tempo, light room reverb
    if voice == "alan":
        af = "asetrate=22050*0.91,aresample=44100,atempo=1/0.91,lowpass=f=7000,aecho=0.8:0.6:70|130:0.18|0.10"
    elif voice == "jenny":
        af = "asetrate=22050*0.97,aresample=44100,atempo=1/0.97,highpass=f=180,aecho=0.8:0.7:90|160:0.25|0.15"
    else:  # whisper: breathy, thin, close
        af = "asetrate=22050*0.86,aresample=44100,atempo=1/0.86,highpass=f=900,lowpass=f=6000,aecho=0.8:0.8:40|90:0.35|0.25"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", af, "-ac", "1", "-ar", "44100", fin], check=True)
    a, sr = read_wav(fin)
    a = trim(a)
    if voice == "whisper":
        # add breath noise shaped by the speech envelope -> whisper feel
        env = np.convolve(np.abs(a), np.ones(400) / 400, mode="same")
        rng = np.random.default_rng(3)
        a = a * 0.55 + rng.normal(0, 1, len(a)).astype(np.float32) * env * 0.9
    np.save(f"{OUT}/vo_{i:02d}.npy", a)
    dur = len(a) / sr
    meta.append({"i": i, "start": start, "dur": round(dur, 3), "voice": voice, "text": text, "cap": cap})
    print(f"{i:02d} {start:5.1f} -> {start + dur:5.2f}  ({dur:.2f}s) {text}")

for a, b in zip(meta, meta[1:]):
    if a["start"] + a["dur"] > b["start"] - 0.1:
        print(f"  OVERLAP: line {a['i']} ends {a['start'] + a['dur']:.2f} next starts {b['start']}")
json.dump(meta, open(f"{OUT}/vo.json", "w"), indent=1)
