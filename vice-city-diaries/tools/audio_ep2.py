"""Soundtrack for Episode 2: suspense score (A minor, 92 BPM), city ambience, car/phone SFX, dialogue.
Writes audio/soundtrack.m4a (for the browser) and $SCR/vc_soundtrack.wav (for the MP4 render)."""
import json, os, subprocess, wave
import numpy as np

SCR = os.environ["SCR"]
HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "..", "data", "timeline_ep2.json")))
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


# ---------------------------------------------------------------- score (Episode 2)
BPM = 96; beat = 60 / BPM; bar = beat * 4
note = lambda n: 440 * 2 ** ((n - 69) / 12)
chords = [(57, 60, 64), (53, 57, 60), (52, 56, 59), (57, 60, 64)]          # Am F E Am
roots = [45, 41, 40, 45]
pad = np.zeros(N, np.float32); bass = np.zeros(N, np.float32)
for k in range(int(DUR / (bar * 2)) + 1):
    t0 = k * bar * 2; ch = chords[k % 4]; n = int(bar * 2 * SR)
    t = np.arange(n) / SR
    e = np.minimum(1, t / 0.8) * np.minimum(1, (bar * 2 - t) / 0.6)
    s = sum(np.sin(2 * np.pi * note(m) * t * d) * w for m in ch for d, w in ((1, 0.5), (1.003, 0.35), (0.997, 0.35), (2, 0.12)))
    place(pad, (s * e).astype(np.float32), t0)
    for b8 in range(16):
        bt = t0 + b8 * beat / 2; d = beat / 2 * 0.9; tb = np.arange(int(d * SR)) / SR
        f0 = note(roots[k % 4] - 12)
        sb = (np.sign(np.sin(2 * np.pi * f0 * tb)) * 0.5 + np.sin(2 * np.pi * f0 * tb)) * np.exp(-tb * 6)
        place(bass, sb.astype(np.float32), bt)
pad = filt(pad, 60, 1800) * 0.12
bass = filt(bass, 30, 420) * 0.35
drums = np.zeros(N, np.float32)
t = 0.0; i = 0
while t < DUR:
    if t < 12.9: place(drums, thump(0.35, 52), t, 0.95)
    if t < 12.9 and i % 2 == 1: place(drums, burst(0.18, 900, 6000, 0.002, 18), t, 0.38)
    if t < 12.9:
        for q in range(4): place(drums, burst(0.04, 6000, 14000, 0.001, 90), t + q * beat / 4, 0.18 if q % 2 else 0.1)
    t += beat; i += 1
hb = np.zeros(N, np.float32)                                                 # heartbeat while they hide
for k in range(int((33.0 - 17.0) / 0.95)):
    b0 = 17.0 + k * 0.95
    place(hb, thump(0.25, 48, 16), b0, 0.8); place(hb, thump(0.22, 44, 18), b0 + 0.22, 0.55)
pad *= env([(0, 0.9), (12.9, 1.0), (13.4, 0.15), (16.4, 0.0), (20, 0.25), (33, 0.35), (36.5, 0.7), (52, 0.9), (71, 0.9), (71.3, 0.4), (79, 0.6), (84, 1.2), (86.5, 1.3), (86.6, 0), (90, 0)])
bass *= env([(0, 1.0), (12.9, 1.0), (13.2, 0), (46, 0), (47, 0.5), (52, 0.7), (70.8, 0.8), (71.2, 0), (79.4, 0), (80, 0.5), (84, 0.9), (86.5, 1.0), (86.6, 0), (90, 0)])
hb *= env([(16.4, 0), (17.5, 0.9), (31.5, 0.9), (33, 0), (90, 0)])
riser_t = np.arange(int(4.0 * SR)) / SR
riser = (np.sin(2 * np.pi * np.cumsum(120 + 500 * (riser_t / 4.0) ** 2) / SR) * (riser_t / 4.0) ** 2).astype(np.float32)
music = pad + bass + drums + hb
place(music, riser * 0.25, 80.0)
place(music, riser * 0.18, 9.0)

# ---------------------------------------------------------------- ambience
road = norm(filt(np.cumsum(rng.normal(0, 1, N)).astype(np.float32), 25, 180)) * env([(0, 0.8), (12.9, 0.9), (15.8, 0.25), (16.4, 0), (90, 0)])
city = norm(filt(rng.normal(0, 1, N).astype(np.float32), 60, 500)) * env([(0, 0), (16.4, 0), (16.6, 0.25), (70.8, 0.25), (71, 0), (90, 0)])     # traffic hum over the overpass
water = norm(filt(rng.normal(0, 1, N).astype(np.float32), 150, 1400)) * (0.55 + 0.45 * np.sin(tt * 1.3) * np.sin(tt * 0.37)) * env([(0, 0), (71, 0), (71.4, 0.5), (86.6, 0.5), (86.7, 0), (90, 0)])
wind = norm(filt(rng.normal(0, 1, N).astype(np.float32), 300, 2500)) * (0.5 + 0.5 * np.sin(tt * 0.6)) * env([(0, 0), (71, 0), (71.4, 0.18), (86.6, 0.18), (86.7, 0), (90, 0)])
amb = road * 0.35 + city * 0.2 + water * 0.22 + wind * 0.12
for k in range(6):                                   # traffic thumping over the deck joints
    place(amb, thump(0.5, 40, 6), 18 + k * 8.3 + rng.random() * 2, 0.18)
bell = tone(523, 2.5, 1.2, ((1, 1), (2.76, .5), (5.4, .2)))                    # distant buoy bell
for bt in (72.5, 78.8, 85.1): place(amb, filt(bell, hi=2500), bt, 0.035)

# ---------------------------------------------------------------- sfx
sfx = np.zeros(N, np.float32)
def vibrate(d):
    t = np.arange(int(d * SR)) / SR
    s = (np.sign(np.sin(2 * np.pi * 160 * t)) * 0.6 + np.sin(2 * np.pi * 320 * t) * 0.3) * ((t % 0.5) < 0.33)
    return filt(s.astype(np.float32), 100, 2500)
eng_t = np.arange(int(13.0 * SR)) / SR                                        # hero engine during the chase
eng = np.sin(2 * np.pi * np.cumsum(70 + 8 * np.sin(eng_t * 0.9)) / SR) + 0.4 * np.sign(np.sin(2 * np.pi * np.cumsum(140 + 16 * np.sin(eng_t * 0.9)) / SR))
place(sfx, filt(eng.astype(np.float32), 30, 700) * 0.6, 0.0, 0.5)
suv_t = np.arange(int(13.0 * SR)) / SR
place(sfx, filt((np.sin(2 * np.pi * 48 * suv_t) + 0.5 * np.sign(np.sin(2 * np.pi * 96 * suv_t))).astype(np.float32), 30, 400), 0.0, 0.4)
for w in (12.6,): place(sfx, burst(0.5, 400, 6000, 0.25, 6), w - 0.25, 0.4)
sq_t = np.arange(int(2.2 * SR)) / SR                                          # tyre screech
sq = filt(rng.normal(0, 1, len(sq_t)).astype(np.float32), 1800, 5000) * (0.6 + 0.4 * np.sin(2 * np.pi * 11 * sq_t)) * np.exp(-sq_t * 0.8)
place(sfx, (sq * np.minimum(1, sq_t / 0.05)).astype(np.float32), 12.95, 0.35)
for k, ct in enumerate((13.45, 13.6, 13.78, 13.95, 14.1, 14.3)):             # cones + barrier
    place(sfx, thump(0.2, 140 + k * 15, 22), ct, 0.5); place(sfx, burst(0.25, 800, 5000, 0.002, 14), ct, 0.25)
place(sfx, burst(0.9, 200, 4000, 0.003, 4) , 14.45, 0.4); place(sfx, thump(0.6, 60, 7), 14.45, 0.7)
off_t = np.arange(int(1.6 * SR)) / SR                                         # engine winds down, off
off = np.sin(2 * np.pi * np.cumsum(70 * np.exp(-off_t * 1.2) + 15) / SR) * np.exp(-off_t * 2.2)
place(sfx, filt(off.astype(np.float32), 30, 500), 16.5, 0.45)
crawl_t = np.arange(int(12.0 * SR)) / SR                                      # SUV crawling past
crawl = filt((np.sin(2 * np.pi * 42 * crawl_t) + 0.5 * np.sign(np.sin(2 * np.pi * 84 * crawl_t))).astype(np.float32), 30, 380)
place(sfx, crawl * np.exp(-((crawl_t - 6.0) / 3.2) ** 2).astype(np.float32), 21.0, 0.6)
for k in range(3): place(sfx, vibrate(0.7), 33.2 + k * 0.8, 0.35)
place(sfx, tone(1318, 0.12, 30) + tone(1760, 0.12, 30), 36.35, 0.2)
place(sfx, tone(880, 0.15, 25), 50.9, 0.15); place(sfx, tone(660, 0.18, 25), 51.06, 0.15)
for k in range(12): place(sfx, burst(0.03, 2500, 9000, 0.001, 90), 56.2 + k * 0.08, 0.18)
arr_t = np.arange(int(4.2 * SR)) / SR                                         # arriving at the marina
arr = np.sin(2 * np.pi * np.cumsum(50 + 20 * (1 - arr_t / 4.2)) / SR) + 0.4 * np.sign(np.sin(2 * np.pi * np.cumsum(100 + 40 * (1 - arr_t / 4.2)) / SR))
place(sfx, filt(arr.astype(np.float32), 30, 600) * np.minimum(1, (4.2 - arr_t) / 0.8).astype(np.float32), 71.0, 0.35)
place(sfx, filt(rng.normal(0, 1, int(4 * SR)).astype(np.float32), 300, 2500) * 0.3, 71.0, 0.12)   # gravel
place(sfx, thump(0.3, 90, 14), 79.1, 0.4)
for k in range(7): place(sfx, thump(0.18, 95, 26), 79.5 + k * 0.52, 0.45); place(sfx, burst(0.12, 300, 2200, 0.002, 30), 79.5 + k * 0.52, 0.18)   # heels on wood
place(sfx, thump(0.4, 70, 10), 83.0, 0.5)                                     # SUV door
for k in range(3): place(sfx, thump(0.2, 80, 24), 83.3 + k * 0.4, 0.4)        # his steps
def boom(d=2.5):
    t = np.arange(int(d * SR)) / SR
    return norm(np.sin(2 * np.pi * np.cumsum(70 * np.exp(-t * 1.5) + 28) / SR) * np.exp(-t * 1.6) + burst(d, 30, 400, 0.005, 3) * 0.5).astype(np.float32)
place(sfx, boom(), 84.0, 0.7)
place(sfx, boom(), 87.2, 0.9)

# ---------------------------------------------------------------- dialogue
vo = np.zeros(N, np.float32)
for l in TL["lines"]:
    a = np.load(f"{SCR}/vo_vc2/line_{l['i']:02d}.npy").astype(np.float32)
    a = a / (np.max(np.abs(a)) + 1e-9)
    place(vo, a, l["start"], {"man": 0.9, "lucia": 0.85, "lucia_vo": 0.8, "jason": 0.85, "caller": 0.7}[l["speaker"]])

ve = np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same")
duck = 1 - 0.5 * np.clip(ve / 0.08, 0, 1)
mix = (music * 0.55 + amb) * duck + sfx * 0.6 + vo
mix = np.tanh(mix * 1.1) / np.tanh(1.1)
mix = mix / np.max(np.abs(mix)) * 0.93
wide = np.roll((music * 0.55 + amb) * duck, 280) * 0.08
st = (np.stack([np.clip(mix + wide, -1, 1), np.clip(mix - wide, -1, 1)], 1) * 32767).astype(np.int16)
wav = f"{SCR}/vc2_soundtrack.wav"
with wave.open(wav, "w") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-c:a", "aac", "-b:a", "160k", os.path.join(HERE, "..", "audio", "soundtrack_ep2.m4a")], check=True)
print("ok")
