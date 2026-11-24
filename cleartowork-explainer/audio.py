"""Soundtrack for the ClearToWork explainer: dark ambient bed, a ticking pulse that tightens as the risk climbs,
sound effects cued from timeline.json, and the voiceover. Writes $SCR/2am_mix.wav."""
import json, os, wave
import numpy as np

SCR = os.environ["SCR"]
HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "timeline.json")))
L = TL["lines"]; DUR = TL["duration"]; SR = 44100; N = int(SR * DUR); tt = np.arange(N) / SR
rng = np.random.default_rng(3)
def env(pts): ts, vs = zip(*pts); return np.interp(tt, ts, vs).astype(np.float32)
def filt(x, lo=None, hi=None):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR); m = np.ones_like(f)
    if lo: m *= 1 / (1 + (lo / np.maximum(f, 1e-3)) ** 4)
    if hi: m *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(X * m, len(x)).astype(np.float32)
norm = lambda x: x / (np.max(np.abs(x)) + 1e-9)
def place(buf, sig, t0, g=1.0):
    i = int(t0 * SR); j = min(len(buf), i + len(sig))
    if 0 <= i < len(buf): buf[i:j] += sig[:j - i] * g
def burst(d, lo, hi, a=0.01, dec=4.0):
    n = int(d * SR); t = np.arange(n) / SR
    return norm(filt(rng.normal(0, 1, n).astype(np.float32), lo, hi)) * (np.minimum(1, t / a) * np.exp(-dec * t)).astype(np.float32)
def tone(f, d, dec=6.0, harm=((1, 1.0),)):
    t = np.arange(int(d * SR)) / SR
    return (sum(a * np.sin(2 * np.pi * f * h * t) for h, a in harm) * np.exp(-dec * t)).astype(np.float32)
def thump(d=0.4, f=55, dec=10):
    t = np.arange(int(d * SR)) / SR
    return (np.sin(2 * np.pi * f * t * (1 + 0.8 * np.exp(-t * 35))) * np.exp(-t * dec)).astype(np.float32)
def boom(d=2.5):
    t = np.arange(int(d * SR)) / SR
    return norm(np.sin(2 * np.pi * np.cumsum(70 * np.exp(-t * 1.5) + 28) / SR) * np.exp(-t * 1.6) + burst(d, 30, 400, 0.005, 3) * 0.5).astype(np.float32)
ch = lambda i, k: L[i]["chunks"][min(k, len(L[i]["chunks"]) - 1)][0]
st = lambda i: L[i]["start"]

# ---- bed: tense first (the problem), then a bright major-key pluck once ClearToWork arrives
note = lambda n: 440 * 2 ** ((n - 69) / 12)
drone = np.zeros(N, np.float32)
for m, w in ((45, 0.5), (52, 0.3), (57, 0.25)):
    drone += w * np.sin(2 * np.pi * note(m) * tt * (1 + 0.002 * np.sin(tt * 0.3 + m))).astype(np.float32)
drone = filt(drone, 40, 900) * env([(0, 0), (0.8, 1), (st(3) - 0.3, 1), (st(3) + 0.3, 0), (DUR, 0)])
tick = np.zeros(N, np.float32); t = 0.5
while t < st(3):
    place(tick, tone(1900, 0.03, 120), t, 0.12); t += 0.5
pluck = np.zeros(N, np.float32)
prog_ = [(60, 64, 67), (55, 59, 62), (57, 60, 64), (53, 57, 60)]           # C G Am F
t = st(3); k = 0
while t < DUR - 1.5:
    chd = prog_[(k // 4) % 4]
    place(pluck, tone(note(chd[k % 3] + 12), 0.5, 6, ((1, 1), (2, .3))), t, 0.06)
    if k % 4 == 0:
        place(pluck, tone(note(chd[0] - 12), 1.6, 1.8, ((1, 1), (2, .2))), t, 0.09)
    t += 0.3; k += 1
pad = np.zeros(N, np.float32)
for m in (60, 64, 67):
    pad += np.sin(2 * np.pi * note(m) * tt).astype(np.float32) * 0.2
pad = filt(pad, 60, 1500) * env([(0, 0), (st(3), 0), (st(3) + 1.0, 0.5), (DUR - 2, 0.6), (DUR, 0)])
music = drone * 0.14 + tick + pluck + pad * 0.12

# ---- sfx
sfx = np.zeros(N, np.float32)
place(sfx, thump(0.4, 70, 10), st(0) + 0.3, 0.5)
for k in range(3): place(sfx, tone(880 - k * 110, 0.15, 20), ch(1, min(k * 2, len(L[1]["chunks"]) - 1)), 0.12)
place(sfx, boom(1.5), st(3), 0.35); place(sfx, tone(1046, 0.8, 4, ((1, 1), (2, .4))), st(3) + 0.1, 0.18)
for k in range(6): place(sfx, tone(1320 if k in (0, 3, 5) else 660, 0.12, 25), st(4) + 0.3 + k * 0.35, 0.1)
for k in range(3): place(sfx, tone(1568, 0.2, 14, ((1, 1), (2, .3))), ch(5, min(k * 2 + 1, len(L[5]["chunks"]) - 1)), 0.13)
place(sfx, thump(0.35, 70, 12), ch(6, 1), 0.7)
place(sfx, tone(1318, 0.12, 30) + tone(1760, 0.12, 30), st(7) + 0.3, 0.12)
place(sfx, burst(0.6, 300, 3000, 0.05, 5), st(8), 0.2)
place(sfx, tone(1046, 1.2, 3, ((1, 1), (1.5, .4), (2, .3))), st(9) + 0.2, 0.2)

# ---- voice
vo = np.zeros(N, np.float32)
for l in L:
    a = np.load(f"{SCR}/vocleartowork/vo_{l['i']:02d}.npy").astype(np.float32); place(vo, a / (np.max(np.abs(a)) + 1e-9) * 0.9, l["start"])
duck = 1 - 0.45 * np.clip(np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same") / 0.08, 0, 1)
mix = music * duck + sfx * 0.55 + vo
mix = np.tanh(mix * 1.1) / np.tanh(1.1); mix = mix / np.max(np.abs(mix)) * 0.93
st2 = (np.stack([mix, mix], 1) * 32767).astype(np.int16)
with wave.open(f"{SCR}/ctw_mix.wav", "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st2.tobytes())
print("ok", DUR)
