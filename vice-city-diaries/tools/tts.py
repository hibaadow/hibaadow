"""Dialogue for Episode 1 (Kokoro neural TTS, local). Writes:
  $SCR/vo_vc/line_XX.npy           44.1 kHz mono audio per line
  data/timeline.json               lines (speaker, text, start, dur, subtitle) + per-speaker mouth envelopes @30fps
"""
import json, os, subprocess
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

SCR = os.environ["SCR"]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{SCR}/vo_vc" + ("2" if os.environ.get("EP", "1") == "2" else "")
os.makedirs(OUT, exist_ok=True)
FPS, DUR = 30, 90.0

# speaker, start (s), text. Starts follow the scene plan in the brief.
EP = os.environ.get("EP", "1")
LINES1 = [
    ("lucia_vo", 1.4, "Everybody in Vice City wants to be somebody."),
    ("lucia_vo", 5.0, "But nobody talks about what it costs."),
    ("caller", 15.3, "You still owe me."),
    ("lucia", 17.3, "I thought we were done."),
    ("caller", 19.4, "We were. Until you disappeared with something that wasn't yours."),
    ("lucia", 24.4, "Then I guess you should come find me."),
    ("jason", 35.7, "Please tell me you didn't just make another enemy."),
    ("lucia", 38.8, "I didn't make him. He was already one."),
    ("jason", 41.3, "What did you do?"),
    ("lucia", 42.5, "Something we need to talk about somewhere else."),
    ("jason", 47.6, "Lucia, what's in the bag?"),
    ("jason", 51.3, "Lucia."),
    ("jason", 55.7, "Where did you get that?"),
    ("lucia", 57.4, "Let's just say somebody made a very expensive mistake."),
    ("jason", 66.6, "Lucia... we're being followed."),
    ("lucia", 82.4, "Keep driving."),
]
LINES2 = [
    ("lucia", 5.0, "Next exit. Take it."),
    ("jason", 8.2, "That's not an exit. That's a construction zone."),
    ("lucia", 10.9, "Take it."),
    ("jason", 22.0, "Who are they?"),
    ("lucia", 25.4, "People who don't forget."),
    ("caller", 36.8, "You can keep running, Lucia. But he can't."),
    ("lucia", 43.7, "Leave him out of this."),
    ("caller", 46.2, "Midnight. The old marina. Bring the bag, and he walks away."),
    ("jason", 52.6, "Lucia. What is really in that bag?"),
    ("lucia", 57.0, "It was never about the money."),
    ("jason", 60.8, "Then what is it?"),
    ("lucia", 63.8, "Every name they ever paid. Cops. Judges. Everyone."),
    ("jason", 68.3, "Then they're never letting us go."),
    ("jason", 75.8, "This is a bad idea."),
    ("lucia", 77.6, "It's the only one we've got."),
    ("man", 84.0, "Hello, Lucia."),
]
LINES = LINES2 if EP == "2" else LINES1
VOICE = {"man": "am_onyx", "lucia": "af_heart", "lucia_vo": "af_heart", "jason": "am_fenrir", "caller": "am_onyx"}
SPEED = {"man": 0.8, "lucia": 0.95, "lucia_vo": 0.9, "jason": 0.95, "caller": 0.84}
NAME = {"man": "???", "lucia": "LUCIA", "lucia_vo": "LUCIA", "jason": "JASON", "caller": "UNKNOWN NUMBER"}
POST = {
    "man": "aresample=44100,aecho=0.8:0.7:90|180:0.12|0.07",      # open air, the pier
    "lucia": "aresample=44100,aecho=0.8:0.4:30|60:0.05|0.03",
    "lucia_vo": "aresample=44100,lowpass=f=9000,aecho=0.8:0.6:60|120:0.10|0.06",      # inner voice, a little roomier
    "jason": "aresample=44100,aecho=0.8:0.4:30|60:0.05|0.03",
    "caller": "aresample=44100,highpass=f=320,lowpass=f=3300,acrusher=bits=10:mix=0.25,volume=1.2",   # phone line
}

kk = Kokoro(f"{SCR}/kokoro/kokoro-v1.0.onnx", f"{SCR}/kokoro/voices-v1.0.bin")


def trim(a, sr, thr=0.008):
    idx = np.where(np.abs(a) > thr)[0]
    return a if len(idx) == 0 else a[max(0, idx[0] - int(0.02 * sr)): idx[-1] + int(0.08 * sr)]


lines, mouth = [], {"lucia": np.zeros(int(DUR * FPS)), "jason": np.zeros(int(DUR * FPS))}
for i, (spk, start, text) in enumerate(LINES):
    # "Lucia" is said loo-SEE-ah (not LOO-sha): phonemize, then swap in the right pronunciation
    ph = kk.tokenizer.phonemize(text.replace("...", ","), "en-us").replace("lˈuːʃə", "luːsˈiːə")
    a, sr = kk.create(ph, voice=VOICE[spk], speed=SPEED[spk], lang="en-us", is_phonemes=True,
                      sentence_pause=0.18, clause_pause=0.06)
    a = trim(np.asarray(a, np.float32), sr)
    raw = f"{OUT}/raw_{i:02d}.wav"
    sf.write(raw, a, sr)
    fin = f"{OUT}/line_{i:02d}.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", POST[spk], "-ac", "1", fin], check=True)
    b, _ = sf.read(fin, dtype="float32")
    np.save(f"{OUT}/line_{i:02d}.npy", b)
    dur = len(a) / sr
    lines.append({"i": i, "speaker": spk, "name": NAME[spk], "text": text, "start": start, "dur": round(dur, 3)})
    # mouth envelope (only for on-screen speech)
    who = {"lucia": "lucia", "jason": "jason"}.get(spk)
    if who:
        hop = sr // FPS
        for k in range(0, len(a) // hop):
            rms = float(np.sqrt(np.mean(a[k * hop:(k + 1) * hop] ** 2)))
            f = int((start + k / FPS) * FPS)
            if 0 <= f < len(mouth[who]):
                mouth[who][f] = rms
for k in mouth:
    m = mouth[k]
    m = np.convolve(m, [0.25, 0.5, 0.25], mode="same")
    mouth[k] = np.clip(m / (np.percentile(m[m > 0], 90) + 1e-9), 0, 1)

for a, b in zip(lines, lines[1:]):
    if a["start"] + a["dur"] > b["start"] - 0.1:
        print(f"OVERLAP {a['i']} ends {a['start'] + a['dur']:.2f} > next {b['start']}")
json.dump({"fps": FPS, "duration": DUR, "lines": lines,
           "mouth": {k: [round(float(x), 2) for x in v] for k, v in mouth.items()}},
          open(os.path.join(HERE, "..", "data", "timeline.json" if EP == "1" else "timeline_ep2.json"), "w"))
for l in lines:
    print(f"{l['i']:02d} {l['start']:5.1f} -> {l['start'] + l['dur']:5.2f}  {l['speaker']:9s} {l['text']}")
