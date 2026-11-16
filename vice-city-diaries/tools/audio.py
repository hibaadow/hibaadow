"""Soundtrack for Episode 1: suspense score (A minor, 92 BPM), city ambience, car/phone SFX, dialogue.
Writes audio/soundtrack.m4a (for the browser) and $SCR/vc_soundtrack.wav (for the MP4 render)."""
import json, os, subprocess, wave
import numpy as np

SCR = os.environ["SCR"]
HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "..", "data", "timeline.json")))
SR, DUR = 44100, 90.0
N = int(SR * DUR)
tt = np.arange(N) / SR
rng = np.random.default_rng(6)


def env(points):
    ts, vs = zip(*points)
    return np.interp(tt, ts, vs).astype(np.float32)


def filt(x, lo=None, hi=None):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR); m = np.ones_like(f)
    if lo: m *= 1 / (1 + (lo / np.maximum(f, 1e-3)) ** 4)
    if hi: m *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(X * m, len(x)).astype(np.float32)


def norm(x): return x / (np.max(np.abs(x)) + 1e-9)


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


# ---------------------------------------------------------------- score
BPM = 92; beat = 60 / BPM; bar = beat * 4
note = lambda n: 440 * 2 ** ((n - 69) / 12)
chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]          # Am F C G
roots = [45, 41, 36, 43]
pad = np.zeros(N, np.float32); bass = np.zeros(N, np.float32)
for k in range(int(DUR / (bar * 2)) + 1):
    t0 = k * bar * 2; ch = chords[k % 4]; n = int(bar * 2 * SR)
    t = np.arange(n) / SR
    e = np.minimum(1, t / 0.8) * np.minimum(1, (bar * 2 - t) / 0.6)
    s = sum(np.sin(2 * np.pi * note(m) * t * d) * w for m in ch for d, w in ((1, 0.5), (1.003, 0.35), (0.997, 0.35), (2, 0.12)))
    place(pad, (s * e).astype(np.float32), t0)
    for b8 in range(16):                                                    # 8th-note bass pulse
        bt = t0 + b8 * beat / 2; d = beat / 2 * 0.9; tb = np.arange(int(d * SR)) / SR
        f0 = note(roots[k % 4] - 12)
        sb = (np.sign(np.sin(2 * np.pi * f0 * tb)) * 0.5 + np.sin(2 * np.pi * f0 * tb)) * np.exp(-tb * 6)
        place(bass, sb.astype(np.float32), bt)
pad = filt(pad, 60, 1800) * 0.12
bass = filt(bass, 30, 420) * 0.35
drums = np.zeros(N, np.float32)
t = 0.0; i = 0
while t < DUR:
    if 45.0 <= t < 86.5: place(drums, thump(0.35, 52), t, 0.9)
    if 70.0 <= t < 86.5 and i % 2 == 1: place(drums, burst(0.18, 900, 6000, 0.002, 18), t, 0.35)
    if 61.0 <= t < 86.5:
        for q in range(4): place(drums, burst(0.04, 6000, 14000, 0.001, 90), t + q * beat / 4, 0.18 if q % 2 else 0.1)
    t += beat; i += 1
pad *= env([(0, 0), (2, 0.6), (27.8, 0.7), (28, 1.0), (61, 1.1), (86.5, 1.3), (86.6, 0), (90, 0)])
bass *= env([(0, 0), (27.8, 0), (28.5, 0.7), (45, 0.9), (61, 1.1), (86.5, 1.2), (86.6, 0), (90, 0)])
riser_t = np.arange(int(6.3 * SR)) / SR
riser = (np.sin(2 * np.pi * np.cumsum(120 + 500 * (riser_t / 6.3) ** 2) / SR) * (riser_t / 6.3) ** 2).astype(np.float32)
music = pad + bass + drums
place(music, riser * 0.25, 80.2)

# ---------------------------------------------------------------- ambience
city = norm(filt(rng.normal(0, 1, N).astype(np.float32), 80, 900)) * env([(0, 0), (1, 0.35), (12, 0.3), (27.8, 0.3), (28, 0.6), (35.3, 0.6), (35.5, 0.08), (86.6, 0.08), (86.7, 0), (90, 0)])
wind = norm(filt(rng.normal(0, 1, N).astype(np.float32), 300, 2500)) * (0.5 + 0.5 * np.sin(tt * 0.6)) * env([(0, 0), (6.6, 0.12), (27.7, 0.12), (27.8, 0), (90, 0)])
road = norm(filt(np.cumsum(rng.normal(0, 1, N)).astype(np.float32), 25, 180)) * env([(0, 0), (35.4, 0), (35.6, 0.25), (44.6, 0.3), (47, 0.7), (86.6, 0.8), (86.7, 0), (90, 0)])
amb = city * 0.22 + wind * 0.12 + road * 0.35
for k in range(10):                                   # distant passing cars / horn on the balcony + street
    place(amb, burst(2.5, 100, 1500, 1.0, 1.2), 1 + k * 2.9 + rng.random(), 0.06)
place(amb, (tone(392, 0.5, 2, ((1, 1), (2, .4))) + tone(466, 0.5, 2, ((1, 1), (2, .4)))) * 0.5, 8.2, 0.03)
s9 = np.arange(int(6 * SR)) / SR
siren = np.sin(2 * np.pi * np.cumsum(800 + 300 * np.sin(2 * np.pi * s9 / 2.2)) / SR) * np.sin(np.pi * s9 / 6)
place(amb, filt(siren.astype(np.float32), hi=900), 3.0, 0.03)

# ---------------------------------------------------------------- sfx
sfx = np.zeros(N, np.float32)
def vibrate(d):
    t = np.arange(int(d * SR)) / SR
    s = (np.sign(np.sin(2 * np.pi * 160 * t)) * 0.6 + np.sin(2 * np.pi * 320 * t) * 0.3) * ((t % 0.5) < 0.33)
    return filt(s.astype(np.float32), 100, 2500)
for k in range(2): place(sfx, vibrate(0.8), 12.2 + k * 0.85, 0.35)
place(sfx, tone(1318, 0.12, 30) + tone(1760, 0.12, 30), 14.65, 0.2)            # answer
place(sfx, tone(880, 0.15, 25), 26.7, 0.15); place(sfx, tone(660, 0.18, 25), 26.86, 0.15)   # hang up
for w in (6.6, 27.8, 45.0, 71.2, 84.0):                                        # whip-pan whooshes
    place(sfx, burst(0.5, 400, 6000, 0.25, 6), w - 0.25, 0.35)
eng_t = np.arange(int(4.0 * SR)) / SR                                           # car arrives
eng = np.sin(2 * np.pi * np.cumsum(55 + 30 * (1 - eng_t / 4)) / SR) + 0.4 * np.sign(np.sin(2 * np.pi * np.cumsum(110 + 50 * (1 - eng_t / 4)) / SR))
place(sfx, filt(eng.astype(np.float32), 30, 600) * np.minimum(1, eng_t / 1.5).astype(np.float32), 27.8, 0.35)
place(sfx, burst(0.9, 2500, 7000, 0.1, 3) , 30.4, 0.12)                          # brake squeal
place(sfx, thump(0.3, 90, 14), 34.4, 0.5); place(sfx, burst(0.15, 300, 3000, 0.002, 25), 34.4, 0.3)   # door open
place(sfx, thump(0.4, 70, 10), 35.25, 0.8)                                      # door shut
rev_t = np.arange(int(3.0 * SR)) / SR                                           # rev + tyres
rev = np.sin(2 * np.pi * np.cumsum(60 + 140 * (rev_t / 3) ** 0.6) / SR) + 0.5 * np.sign(np.sin(2 * np.pi * np.cumsum(120 + 280 * (rev_t / 3) ** 0.6) / SR))
place(sfx, filt(rev.astype(np.float32), 30, 1200) * np.exp(-rev_t * 0.5).astype(np.float32), 44.5, 0.5)
place(sfx, burst(1.2, 1500, 6000, 0.05, 1.5), 44.7, 0.18)
for k in range(12):                                                              # zipper
    place(sfx, burst(0.03, 2500, 9000, 0.001, 90), 52.7 + k * 0.09, 0.2)
suv_t = np.arange(int(25.5 * SR)) / SR                                          # SUV closing in
suvs = filt((np.sin(2 * np.pi * 48 * suv_t) + 0.5 * np.sign(np.sin(2 * np.pi * 96 * suv_t))).astype(np.float32), 30, 400)
place(sfx, suvs * np.clip((suv_t / 25) ** 1.6, 0, 1).astype(np.float32), 61.0, 0.45)
place(sfx, vibrate(0.7), 75.6, 0.4)
place(sfx, tone(1568, 0.25, 12, ((1, 1), (2, .3))), 76.3, 0.2)
def boom(d=2.5):
    t = np.arange(int(d * SR)) / SR
    return norm(np.sin(2 * np.pi * np.cumsum(70 * np.exp(-t * 1.5) + 28) / SR) * np.exp(-t * 1.6) + burst(d, 30, 400, 0.005, 3) * 0.5).astype(np.float32)
place(sfx, boom(), 76.3, 0.6)
place(sfx, boom(), 87.2, 0.9)

# ---------------------------------------------------------------- dialogue
vo = np.zeros(N, np.float32)
for l in TL["lines"]:
    a = np.load(f"{SCR}/vo_vc/line_{l['i']:02d}.npy").astype(np.float32)
    a = a / (np.max(np.abs(a)) + 1e-9)
    place(vo, a, l["start"], {"lucia": 0.85, "lucia_vo": 0.8, "jason": 0.85, "caller": 0.7}[l["speaker"]])

ve = np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same")
duck = 1 - 0.5 * np.clip(ve / 0.08, 0, 1)
mix = (music * 0.55 + amb) * duck + sfx * 0.6 + vo
mix = np.tanh(mix * 1.1) / np.tanh(1.1)
mix = mix / np.max(np.abs(mix)) * 0.93
wide = np.roll((music * 0.55 + amb) * duck, 280) * 0.08
st = (np.stack([np.clip(mix + wide, -1, 1), np.clip(mix - wide, -1, 1)], 1) * 32767).astype(np.int16)
wav = f"{SCR}/vc_soundtrack.wav"
with wave.open(wav, "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-c:a", "aac", "-b:a", "160k", os.path.join(HERE, "..", "audio", "soundtrack.m4a")], check=True)
print("ok")
