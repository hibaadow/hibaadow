"""Soundtrack for THE AGENCY: dark ambient bed, a ticking pulse that tightens as the risk climbs,
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

# ---- bed: soft drone, a music-box motif that turns sour, a pulse from the reveal on
note = lambda n: 440 * 2 ** ((n - 69) / 12)
drone = np.zeros(N, np.float32)
for m, w in ((45, 0.5), (52, 0.3), (57, 0.25), (60, 0.18)):
    drone += w * np.sin(2 * np.pi * note(m) * tt * (1 + 0.002 * np.sin(tt * 0.3 + m))).astype(np.float32)
drone = filt(drone, 40, 900) * (0.8 + 0.2 * np.sin(tt * 0.5)).astype(np.float32)
air = norm(filt(rng.normal(0, 1, N).astype(np.float32), 200, 2000)) * 0.15
bed = (drone * 0.13 + air * 0.05) * env([(0, 0), (1.0, 1), (st(9), 1), (st(10), 1.3), (DUR - 2.5, 1.3), (DUR, 0)])
box = np.zeros(N, np.float32)                                    # music box, souring from the charges on
mel = [76, 79, 83, 81, 79, 76, 74, 76]
t = 0.4; k = 0
while t < st(10):
    sour = t > st(3)
    n = mel[k % len(mel)] - (1 if sour and k % 3 == 1 else 0)
    place(box, tone(note(n), 0.9, 4.5, ((1, 1), (2, .35), (3, .12))), t, 0.06)
    t += 0.5; k += 1
low = np.zeros(N, np.float32); t = st(10)
while t < DUR - 2.5:
    place(low, thump(0.3, 48, 12), t, 0.45); t += 0.82 if t < st(15) else 0.62
music = bed + box + low

# ---- sfx
sfx = np.zeros(N, np.float32)
def ping(t0, g=0.14): place(sfx, tone(1568, 0.22, 14, ((1, 1), (2, .3))), t0, g)
def slam(t0, g=0.8): place(sfx, thump(0.35, 70, 12), t0, g); place(sfx, burst(0.2, 300, 2500, 0.002, 20), t0, g * 0.35)
place(sfx, boom(2.0), st(0) + 0.2, 0.4)
place(sfx, tone(880, 0.6, 5, ((1, 1), (2, .3))), st(2) + 0.3, 0.1)                    # correction chime
sir = np.arange(int(6.0 * SR)) / SR
place(sfx, filt((np.sin(2 * np.pi * np.cumsum(780 + 260 * np.sin(2 * np.pi * sir / 1.6)) / SR) * np.minimum(1, sir / 1.5) * np.minimum(1, (6.0 - sir) / 1.0)).astype(np.float32), hi=1400), ch(3, 3), 0.08)
for k in range(12): place(sfx, tone(2093, 0.05, 60), st(5) + 0.2 + k * 0.22, 0.05)   # camera beeps
slam(ch(6, 0)); place(sfx, tone(520, 0.5, 5), ch(6, 2), 0.1)
for k in range(8): ping(st(7) + 0.2 + k * (L[7]["dur"] - 0.4) / 8, 0.08)
slam(ch(8, 4), 0.6)
place(sfx, boom(2.5), ch(10, 4), 0.6); slam(ch(10, 4), 0.7)
place(sfx, boom(3.0), st(11) + 0.2, 0.5)
slam(ch(13, 2), 0.7)
for k in range(10): place(sfx, burst(0.025, 2000, 7000, 0.001, 120), st(14) + 0.2 + k * 0.08, 0.12)   # counter
slam(ch(14, 4), 0.6)
place(sfx, boom(2.0), st(15) + 0.2, 0.35)
for k in range(3): slam(st(18) + 0.5 + k * 0.45, 0.5)                                # gavel
place(sfx, boom(3.0), st(19) + 0.3, 0.6)

# ---- voice
vo = np.zeros(N, np.float32)
for l in L:
    a = np.load(f"{SCR}/voagency2/vo_{l['i']:02d}.npy").astype(np.float32); place(vo, a / (np.max(np.abs(a)) + 1e-9) * 0.9, l["start"])
duck = 1 - 0.45 * np.clip(np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same") / 0.08, 0, 1)
mix = music * duck + sfx * 0.55 + vo
mix = np.tanh(mix * 1.1) / np.tanh(1.1); mix = mix / np.max(np.abs(mix)) * 0.93
st2 = (np.stack([mix, mix], 1) * 32767).astype(np.int16)
with wave.open(f"{SCR}/agency2_mix.wav", "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st2.tobytes())
print("ok", DUR)
