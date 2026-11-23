"""Soundtrack for THE 2AM DELIVERY: dark ambient bed, a ticking pulse that tightens as the risk climbs,
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

# ---- bed: drone (A minor), slow-moving, darker after the reveal
note = lambda n: 440 * 2 ** ((n - 69) / 12)
drone = np.zeros(N, np.float32)
for m, w in ((45, 0.5), (52, 0.3), (57, 0.25), (60, 0.18)):
    drone += w * np.sin(2 * np.pi * note(m) * tt * (1 + 0.002 * np.sin(tt * 0.3 + m))).astype(np.float32)
drone = filt(drone, 40, 900) * (0.8 + 0.2 * np.sin(tt * 0.5)).astype(np.float32)
air = norm(filt(rng.normal(0, 1, N).astype(np.float32), 200, 2000)) * 0.15
bed = (drone * 0.14 + air * 0.05) * env([(0, 0), (1.5, 1), (st(11), 1.1), (st(13), 1.3), (DUR - 2.5, 1.3), (DUR, 0)])
# ---- ticking pulse: faster and louder as the risk climbs
tick = np.zeros(N, np.float32); t = st(4)
while t < DUR - 3.5:
    if not (st(11) - 0.2 < t < st(12)):
        g = 0.10 + 0.12 * (t / DUR); place(tick, tone(1900, 0.03, 120), t, g); place(tick, burst(0.02, 3000, 9000, 0.001, 200), t, g * 0.4)
    t += np.interp(t, [0, st(7), st(12), DUR], [0.75, 0.6, 0.42, 0.3])
low = np.zeros(N, np.float32); t = st(7)                                         # low pulse on every other beat
while t < DUR - 3.5:
    place(low, thump(0.3, 48, 12), t, 0.5 * (t / DUR)); t += np.interp(t, [0, st(12), DUR], [1.2, 0.84, 0.6])
hb = np.zeros(N, np.float32)                                                     # heartbeat under the reveal
for k in range(int((st(12) - st(11)) / 0.9)):
    b0 = st(11) + k * 0.9; place(hb, thump(0.25, 46, 16), b0, 0.7); place(hb, thump(0.22, 42, 18), b0 + 0.22, 0.5)
music = bed + tick + low + hb

# ---- sfx
sfx = np.zeros(N, np.float32)
for a in (1.5, 1.85, 2.2): place(sfx, thump(0.25, 110, 22) + burst(0.25, 200, 1800, 0.002, 30) * 0.3, st(0) + a, 0.7)   # knocks
cr = np.arange(int(0.9 * SR)) / SR
place(sfx, filt((np.sin(2 * np.pi * np.cumsum(300 + 120 * np.sin(cr * 9)) / SR) * np.exp(-cr * 2)).astype(np.float32), 200, 2000), st(1), 0.15)  # door creak
place(sfx, burst(0.6, 300, 3000, 0.05, 5), st(2) + 0.2, 0.25)                    # cardboard flaps
for k in range(14): place(sfx, burst(0.03, 2000, 8000, 0.001, 80), ch(2, 1) + k * 0.06, 0.18)   # bills riffle
place(sfx, boom(1.8), ch(2, 1), 0.45)
place(sfx, burst(0.35, 1500, 6000, 0.01, 10), ch(3, 1), 0.15)                    # paper
for k, it in enumerate((ch(4, 2), ch(4, 2) + 0.45, ch(4, 3))): place(sfx, tone(1320 + k * 220, 0.12, 30), it, 0.12)   # price pops
place(sfx, thump(0.35, 70, 12), ch(5, 2), 0.8); place(sfx, burst(0.2, 300, 2500, 0.002, 20), ch(5, 2), 0.3)   # stamp
place(sfx, tone(880, 0.18, 18) + tone(1320, 0.18, 18), ch(5, 4), 0.14)            # message ping
for k, a in enumerate((0.5, 0.85, 1.2)):                                         # keypad 9-1-1
    f1, f2 = ((852, 1477), (697, 1209), (697, 1209))[k]; place(sfx, tone(f1, 0.15, 8) + tone(f2, 0.15, 8), st(6) + a, 0.1)
def vibrate(d):
    t = np.arange(int(d * SR)) / SR
    return filt(((np.sign(np.sin(2 * np.pi * 160 * t)) * 0.6 + np.sin(2 * np.pi * 320 * t) * 0.3) * ((t % 0.5) < 0.33)).astype(np.float32), 100, 2500)
place(sfx, vibrate(1.4), ch(7, 1), 0.4); place(sfx, tone(1568, 0.25, 12, ((1, 1), (2, .3))), ch(7, 2), 0.18); place(sfx, boom(), ch(7, 2), 0.4)
eng = np.arange(int(5 * SR)) / SR                                                # idling car
place(sfx, filt((np.sin(2 * np.pi * 38 * eng) + 0.4 * np.sign(np.sin(2 * np.pi * 76 * eng))).astype(np.float32), 30, 300) * np.minimum(1, eng / 1.0).astype(np.float32), st(8) + 1.0, 0.35)
for k in range(12): place(sfx, burst(0.025, 2000, 7000, 0.001, 120), ch(9, 1) + k * 0.075, 0.15)   # typing
place(sfx, boom(), ch(10, 1), 0.6)
place(sfx, boom(3.0), ch(11, 2), 0.8)
for k, a in enumerate((ch(12, 1), ch(12, 1) + 0.9, ch(12, 2) + 0.6)): place(sfx, tone(1568, 0.2, 14, ((1, 1), (2, .3))), a, 0.16)
for i in (13, 14, 15):
    place(sfx, burst(0.4, 400, 5000, 0.15, 8), st(i) - 0.1, 0.25)                  # card whoosh
    place(sfx, thump(0.2, 140, 20), ch(i, 1), 0.6)                                 # X
for k in range(3): place(sfx, tone(660 + k * 220, 0.2, 10), st(16) + 0.9 + k * 0.4, 0.12)
place(sfx, boom(3.0), st(16) + L[16]["dur"] + 0.3, 0.7)

# ---- voice
vo = np.zeros(N, np.float32)
for l in L:
    a = np.load(f"{SCR}/vo2am/vo_{l['i']:02d}.npy").astype(np.float32); place(vo, a / (np.max(np.abs(a)) + 1e-9) * 0.9, l["start"])
duck = 1 - 0.45 * np.clip(np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same") / 0.08, 0, 1)
mix = music * duck + sfx * 0.55 + vo
mix = np.tanh(mix * 1.1) / np.tanh(1.1); mix = mix / np.max(np.abs(mix)) * 0.93
st2 = (np.stack([mix, mix], 1) * 32767).astype(np.int16)
with wave.open(f"{SCR}/2am_mix.wav", "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st2.tobytes())
print("ok", DUR)
