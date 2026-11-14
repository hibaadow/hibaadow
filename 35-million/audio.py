"""Soundtrack for 35 MILLION: low drone, heartbeat, sirens, phone buzzes, SFX, ducked under the voiceover."""
import json, os, wave
import numpy as np

SCR = os.environ["SCR"]
SR = 44100
_TM = json.load(open(f"{SCR}/vo35n/timemap.json"))
_TO, _TN = np.array([p[0] for p in _TM]), np.array([p[1] for p in _TM])


def M(t):
    """old (story) time -> new tightened time"""
    return float(np.interp(t, _TO, _TN))


DUR = float(_TN[-1])
N = int(SR * DUR)
rng = np.random.default_rng(35)
tt = np.arange(N) / SR


def env(points):
    ts, vs = zip(*points)
    ts = [M(x) for x in ts]
    return np.interp(tt, ts, vs).astype(np.float32)


def fft_filter(x, lo=None, hi=None):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    m = np.ones_like(f)
    if lo:
        m *= 1 / (1 + (lo / np.maximum(f, 1e-3)) ** 4)
    if hi:
        m *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(X * m, len(x)).astype(np.float32)


def place(buf, sig, t0, gain=1.0, mapped=True):
    i = int((M(t0) if mapped else t0) * SR)
    j = min(len(buf), i + len(sig))
    if 0 <= i < len(buf):
        buf[i:j] += sig[: j - i] * gain


def norm(x):
    return x / (np.max(np.abs(x)) + 1e-9)


def noise_burst(dur, lo, hi, attack=0.01, decay=4.0):
    n = int(dur * SR)
    x = fft_filter(rng.normal(0, 1, n).astype(np.float32), lo=lo, hi=hi)
    t = np.arange(n) / SR
    return norm(x) * (np.minimum(1, t / attack) * np.exp(-decay * t)).astype(np.float32)


def tone(freq, dur, decay=6.0, harm=((1, 1.0),)):
    t = np.arange(int(dur * SR)) / SR
    return (sum(a * np.sin(2 * np.pi * freq * h * t) for h, a in harm) * np.exp(-decay * t)).astype(np.float32)


def thump(dur=0.5, f=55):
    t = np.arange(int(dur * SR)) / SR
    s = np.sin(2 * np.pi * f * t * (1 + 0.6 * np.exp(-t * 30))) * np.exp(-t * 11)
    return (s + noise_burst(dur, 80, 1200, 0.001, 40) * 0.35).astype(np.float32)


def boom(dur=2.5):
    t = np.arange(int(dur * SR)) / SR
    f = 70 * np.exp(-t * 1.5) + 28
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6) + noise_burst(dur, 30, 400, 0.005, 3.0) * 0.5
    return norm(s).astype(np.float32)


def glitch(dur, seed):
    r = np.random.default_rng(seed)
    out = np.zeros(int(dur * SR), np.float32)
    i = 0
    while i < len(out):
        seg = int(r.uniform(0.02, 0.08) * SR)
        f = r.choice([220, 440, 880, 1320, 3000])
        s = np.sign(np.sin(2 * np.pi * f * np.arange(seg) / SR)) * (r.random() > 0.35)
        out[i:i + seg] = s[: len(out) - i] * 0.6
        i += seg
    return fft_filter(out, hi=5000)


def buzz(dur=0.9):
    """phone vibrating on a table: two pulses"""
    t = np.arange(int(dur * SR)) / SR
    s = np.sign(np.sin(2 * np.pi * 150 * t)) * 0.6 + np.sin(2 * np.pi * 300 * t) * 0.3
    gate = ((t % 0.45) < 0.32).astype(np.float32)
    return fft_filter((s * gate).astype(np.float32), lo=90, hi=2500)


def chime(f1=1318, f2=1760):
    a = tone(f1, 0.5, 7, ((1, 1), (2, 0.2)))
    b = tone(f2, 0.8, 5, ((1, 1), (2, 0.2)))
    out = np.zeros(int(1.0 * SR), np.float32)
    out[:len(a)] += a
    out[int(0.13 * SR):int(0.13 * SR) + len(b)] += b
    return out


def tick():
    return noise_burst(0.03, 2000, 8000, 0.0005, 150)


def siren(dur, seed=0, far=1.0):
    """US wail siren with distance filtering; far 1=distant, 0=close"""
    t = np.arange(int(dur * SR)) / SR
    f = 900 + 450 * np.sin(2 * np.pi * t / 2.4 + seed)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.3 * np.sin(2 * np.pi * 2 * np.cumsum(f) / SR)
    s = s.astype(np.float32)
    lo = fft_filter(s, hi=900)
    return norm(lo * far + s * (1 - far))


def heartbeat_track(t0, t1, bpm0, bpm1, gain):
    t = t0
    while t < t1:
        bpm = bpm0 + (bpm1 - bpm0) * (t - t0) / (t1 - t0)
        place(sfx, thump(0.3, 42), t, gain)
        place(sfx, thump(0.3, 38), t + 0.17, gain * 0.7)
        t += 60 / bpm


# ---------------------------------------------------------------- beds
drone = (np.sin(2 * np.pi * 41.2 * tt) + 0.8 * np.sin(2 * np.pi * 41.6 * tt)
         + 0.3 * np.sin(2 * np.pi * 61.7 * tt + np.sin(tt * 0.3))
         + 0.15 * np.sin(2 * np.pi * 98 * tt) * (0.5 + 0.5 * np.sin(tt * 0.23))).astype(np.float32) / 2.2
drone += norm(fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=60, hi=260)) * 0.25
drone *= env([(0, 0), (1.5, 0.5), (16, 0.6), (24, 0.75), (45, 0.8), (62, 0.7), (66, 0.85), (76, 1.0), (82, 0.9),
              (84.6, 0.6), (100, 0.45), (114, 0.6), (118, 0.8), (126.5, 1.0), (126.6, 0.3), (127.6, 0.9), (131, 0.4), (132, 0)])
rain = norm(fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=900, hi=7000))
rain *= env([(0, 0.18), (29.5, 0.18), (29.6, 0.5), (31, 0.5), (31.1, 0.18), (51.2, 0.18), (51.3, 0.5), (53.4, 0.5),
             (53.5, 0.1), (56.4, 0.1), (56.5, 0.7), (62, 0.7), (62.1, 0.05), (92, 0.05), (132, 0.05)]) * 0.22
hum = norm(fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=40, hi=180))     # station / train idle
hum *= env([(0, 0), (61.9, 0), (62.2, 0.6), (84.6, 0.6), (87.9, 0.2), (88, 0), (132, 0)]) * 0.35
waves = norm(fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=150, hi=1800))
waves *= (0.5 + 0.5 * np.sin(2 * np.pi * tt / 5.5)) ** 2
waves *= env([(0, 0), (113.9, 0), (114.2, 0.6), (118, 0.6), (118.1, 0.25), (126.5, 0.25), (126.6, 0), (132, 0)]) * 0.4
engine = norm(fft_filter(np.cumsum(rng.normal(0, 1, N)).astype(np.float32), lo=30, hi=160))
engine *= env([(0, 0), (89.7, 0), (89.9, 0.8), (99.9, 0.8), (100, 0), (132, 0)]) * 0.45
hum = hum + waves + engine
music = (drone * 0.5 + rain + hum) * 0.45

# ---------------------------------------------------------------- sfx
sfx = np.zeros(N, np.float32)
place(sfx, boom(), 0.0, 0.4)
# phone buzz + transfer chime + slot-machine roll
place(sfx, buzz(0.95), 8.3, 0.6)
place(sfx, chime(), 9.7, 0.35)
for k in range(60):
    place(sfx, tick(), 10.9 + k * 0.035, 0.45)
place(sfx, chime(1568, 2093), 13.0, 0.35)
# noodles hit the floor
place(sfx, thump(0.4, 90), 13.95, 0.8)
place(sfx, noise_burst(0.6, 600, 6000, 0.005, 6), 13.97, 0.4)
# text message: buzz + pops for each bubble
place(sfx, buzz(0.5), 16.0, 0.5)
for p in (20.1, 21.2, 22.4, 23.4):
    place(sfx, tone(1046, 0.15, 25), p, 0.18)
heartbeat_track(16.5, 24.0, 70, 90, 0.5)
# rule cards
for p in (24.0, 31.0, 38.0):  # rule cards
    place(sfx, boom(), p, 0.8)
# location ping
for k in range(4):
    place(sfx, tone(1975, 0.3, 12, ((1, 1), (2, 0.2))), 27.4 + k * 0.6, 0.12)
place(sfx, noise_burst(1.0, 300, 3000, 0.02, 3), 29.5, 0.2)
# knock at the door (peephole)
for p in (35.2, 35.55, 35.9):
    place(sfx, thump(0.35, 85), p, 0.6)
# flip clock
place(sfx, noise_burst(0.12, 1500, 7000, 0.001, 30), 42.6, 0.6)
place(sfx, thump(0.15, 140), 42.65, 0.4)
# news sting
place(sfx, boom(1.8), 45.0, 0.7)
place(sfx, tone(587, 0.6, 3, ((1, 1), (1.5, 0.4))), 45.05, 0.18)
place(sfx, tone(784, 0.8, 3, ((1, 1), (1.5, 0.4))), 45.3, 0.18)
# sirens: distant -> close during the escape
sirens = siren(17.5, 0, far=1.0)
sirens *= np.interp(np.arange(len(sirens)) / SR, [0, 3, 6, 9, 17.5], [0.0, 0.35, 0.9, 0.7, 0.5]).astype(np.float32)
place(sfx, sirens, 47.5, 0.35)
place(sfx, siren(8, 1.3, far=0.3), 51.2, 0.18)
# SUVs: tyres + doors
place(sfx, noise_burst(1.0, 1500, 6000, 0.05, 2.5), 51.3, 0.25)
for p in (52.4, 52.7, 52.95):
    place(sfx, thump(0.3, 70), p, 0.6)
# running footsteps
p = 53.5
while p < 62.0:
    place(sfx, thump(0.18, 75 + 20 * rng.random()), p, 0.45)
    if p > 56.4:
        place(sfx, noise_burst(0.12, 1200, 6000, 0.002, 30), p, 0.12)   # splash
    p += 0.22
place(sfx, thump(0.4, 60), 56.4, 0.9)       # back door bangs open
heartbeat_track(45.5, 62.0, 100, 140, 0.45)
# platform: door chime + countdown ticks
place(sfx, tone(659, 0.5, 4), 62.3, 0.15)
place(sfx, tone(523, 0.7, 4), 62.65, 0.15)
for k in range(26):
    place(sfx, tick(), 62.0 + k, 0.25)
heartbeat_track(66.0, 82.0, 80, 115, 0.4)
place(sfx, boom(1.5), 66.0, 0.4)            # agent steps in
# reveal
place(sfx, glitch(0.6, 3), 76.0, 0.18)
place(sfx, boom(), 76.0, 0.9)
place(sfx, boom(1.5), 78.4, 0.7)
place(sfx, buzz(0.95), 79.7, 0.7)           # someone is texting...
# escape onto the train
p = 82.2
while p < 83.9:
    place(sfx, thump(0.18, 80), p, 0.45)
    p += 0.2
place(sfx, tone(659, 0.5, 4), 83.9, 0.18)
place(sfx, tone(523, 0.7, 4), 84.15, 0.18)
place(sfx, noise_burst(0.8, 1500, 8000, 0.02, 3), 84.0, 0.3)       # doors hiss shut
place(sfx, thump(0.3, 70), 84.5, 0.5)
rumble = norm(fft_filter(np.cumsum(rng.normal(0, 1, int(4 * SR))).astype(np.float32), lo=25, hi=200))
rumble *= np.interp(np.arange(len(rumble)) / SR, [0, 1, 3, 4], [0, 1, 0.8, 0]).astype(np.float32)
place(sfx, rumble, 84.6, 0.7)
# keys
for k in range(5):
    place(sfx, tone(3200 + 400 * k, 0.15, 30), 89.2 + k * 0.04, 0.1)
place(sfx, noise_burst(0.5, 200, 2000, 0.01, 5), 89.85, 0.5)        # ignition
# sold / cash register
place(sfx, tone(2093, 0.6, 5, ((1, 1), (2, 0.3))), 100.9, 0.25)
place(sfx, noise_burst(0.15, 2000, 8000, 0.001, 25), 100.85, 0.4)
spin = np.sin(2 * np.pi * 60 * tt[:int(3.8 * SR)]) * (0.6 + 0.4 * np.sin(2 * np.pi * 1.2 * tt[:int(3.8 * SR)]))
place(sfx, fft_filter(spin.astype(np.float32), hi=300), 103.4, 0.3)
# fire
place(sfx, noise_burst(1.6, 200, 3000, 0.05, 0.8), 107.2, 0.45)
place(sfx, boom(1.2), 109.6, 0.5)                                    # transformation hit
place(sfx, tone(1318, 0.4, 8), 111.4, 0.15)
# the house: car passing, knock, phone
place(sfx, noise_burst(1.6, 100, 1500, 0.6, 1.2), 119.8, 0.4)
for p in (121.6, 122.0):
    place(sfx, thump(0.35, 85), p, 0.8)
heartbeat_track(118.5, 126.5, 70, 110, 0.45)
place(sfx, buzz(0.95), 126.6, 0.8)
place(sfx, boom(), 126.6, 0.9)
place(sfx, boom(), 127.6, 0.6)
place(sfx, tone(220, 1.8, 2, ((1, 1), (1.5, 0.4))), 129.0, 0.2)

# ---------------------------------------------------------------- voiceover
vo = np.zeros(N, np.float32)
for m in json.load(open(f"{SCR}/vo35n/vo.json")):
    a = np.load(f"{SCR}/vo35n/vo_{m['i']:02d}.npy").astype(np.float32)
    a = a / (np.max(np.abs(a)) + 1e-9)
    place(vo, a, m["start"], {"narr": 0.85, "agent": 0.8}[m["voice"]], mapped=False)

vo_env = np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same")
duck = 1 - 0.55 * np.clip(vo_env / 0.08, 0, 1)
mixd = music * duck + sfx * 0.5 * (1 - 0.3 * np.clip(vo_env / 0.08, 0, 1)) + vo
mixd = np.tanh(mixd * 1.1) / np.tanh(1.1)
mixd = mixd / np.max(np.abs(mixd)) * 0.93
wide = np.roll(music * duck, 300) * 0.06
st = (np.stack([np.clip(mixd + wide, -1, 1), np.clip(mixd - wide, -1, 1)], 1) * 32767).astype(np.int16)
with wave.open(f"{SCR}/soundtrack35n.wav", "w") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(st.tobytes())
print("ok", st.shape)
