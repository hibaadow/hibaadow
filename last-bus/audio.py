"""Build the soundtrack: low drone, rain, engine, SFX, ducked under the voiceover."""
import json, os, wave
import numpy as np

SCR = os.environ["SCR"]
SR = 44100
DUR = 90.0
N = int(SR * DUR)
rng = np.random.default_rng(7)
tt = np.arange(N) / SR


def env(points):
    """piecewise-linear envelope from [(t, v), ...]"""
    ts, vs = zip(*points)
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


def place(buf, sig, t0, gain=1.0):
    i = int(t0 * SR)
    j = min(len(buf), i + len(sig))
    if i < len(buf):
        buf[i:j] += sig[: j - i] * gain


def norm(x):
    return x / (np.max(np.abs(x)) + 1e-9)


# ---------------------------------------------------------------- beds
drone = (np.sin(2 * np.pi * 43.65 * tt) + 0.8 * np.sin(2 * np.pi * 44.1 * tt)
         + 0.35 * np.sin(2 * np.pi * 65.4 * tt + np.sin(tt * 0.3))
         + 0.18 * np.sin(2 * np.pi * 92.5 * tt) * (0.5 + 0.5 * np.sin(tt * 0.21)))
drone = drone.astype(np.float32) / 2.2
dark = fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=60, hi=260)
drone += norm(dark) * 0.25 * (0.6 + 0.4 * np.sin(tt * 0.17))
drone *= env([(0, 0), (1.5, 0.55), (22, 0.6), (46, 0.7), (52, 0.9), (57.6, 1.0), (57.7, 0.4), (60, 0.55),
              (67, 0.8), (75.7, 0.9), (75.8, 0.2), (76.3, 1.0), (78.4, 0.8), (85, 0.9), (85.2, 0.5), (89, 0.4), (90, 0)])

rain = norm(fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=900, hi=7000))
rain_env = env([(0, 0), (0.5, 0.5), (3.4, 0.5), (3.5, 0.25), (46.2, 0.25), (46.3, 0.5), (49.6, 0.5), (49.7, 0.15),
                (58.4, 0.15), (59.5, 0.5), (70.2, 0.5), (70.3, 0.2), (75.8, 0.2), (75.9, 0.5), (85.2, 0.5), (86, 0.1), (90, 0)])
rain *= rain_env * 0.22

engine = norm(fft_filter(np.cumsum(rng.normal(0, 1, N)).astype(np.float32), lo=25, hi=140))
engine *= (0.8 + 0.2 * np.sin(2 * np.pi * 3.1 * tt)).astype(np.float32)
engine *= env([(0, 0), (0.6, 0.7), (46.2, 0.7), (47.6, 0.15), (49.6, 0.15), (52.4, 0.5), (57.6, 0.5), (58.4, 0.15),
               (70.2, 0.15), (70.3, 0.45), (78.4, 0.45), (79, 0.2), (85.2, 0.1), (86, 0)]) * 0.35

music = (drone * 0.5 + rain + engine) * 0.45

# ---------------------------------------------------------------- sfx
sfx = np.zeros(N, np.float32)


def tone(freq, dur, decay=6.0, harm=((1, 1.0),)):
    t = np.arange(int(dur * SR)) / SR
    s = sum(a * np.sin(2 * np.pi * freq * h * t) for h, a in harm)
    return (s * np.exp(-decay * t)).astype(np.float32)


def noise_burst(dur, lo, hi, attack=0.01, decay=4.0):
    n = int(dur * SR)
    x = fft_filter(rng.normal(0, 1, n).astype(np.float32), lo=lo, hi=hi)
    t = np.arange(n) / SR
    e = np.minimum(1, t / attack) * np.exp(-decay * t)
    return norm(x) * e.astype(np.float32)


def boom(dur=2.5):
    t = np.arange(int(dur * SR)) / SR
    f = 70 * np.exp(-t * 1.5) + 28
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t * 1.6)
    s += noise_burst(dur, 30, 400, 0.005, 3.0) * 0.5
    return norm(s).astype(np.float32)


def glitch(dur, seed):
    r = np.random.default_rng(seed)
    out = np.zeros(int(dur * SR), np.float32)
    i = 0
    while i < len(out):
        seg = int(r.uniform(0.02, 0.08) * SR)
        f = r.choice([220, 440, 880, 1320, 3000])
        t = np.arange(seg) / SR
        s = np.sign(np.sin(2 * np.pi * f * t)) * (r.random() > 0.35)
        out[i:i + seg] = s[: len(out) - i] * 0.6
        i += seg
    return fft_filter(out, hi=5000)


def thump(dur=0.5, f=55):
    t = np.arange(int(dur * SR)) / SR
    s = np.sin(2 * np.pi * f * t * (1 + 0.6 * np.exp(-t * 30))) * np.exp(-t * 11)
    s += noise_burst(dur, 80, 1200, 0.001, 40) * 0.35
    return s.astype(np.float32)


def bell():
    return norm(tone(988, 1.6, 3.2, ((1, 1), (2.01, 0.5), (2.76, 0.35), (5.4, 0.15))))


def riser(dur):
    t = np.arange(int(dur * SR)) / SR
    f = 80 + 220 * (t / dur) ** 2
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * (t / dur) ** 1.5
    s += noise_burst(dur, 500, 4000, dur * 0.9, 0) * (t / dur) ** 2 * 0.4
    return s.astype(np.float32)


def tick():
    return noise_burst(0.04, 2000, 8000, 0.0005, 120) * 0.8


# glitches on the sign
place(sfx, glitch(1.1, 1), 9.7, 0.16)
place(sfx, glitch(0.5, 2), 10.8, 0.18)
place(sfx, glitch(0.6, 3), 15.6, 0.12)
place(sfx, glitch(0.8, 4), 70.2, 0.18)
place(sfx, glitch(0.25, 5), 19.2, 0.15)
for p in (16.2, 17.2, 18.2, 19.2):         # page flips
    place(sfx, tone(1760, 0.12, 30), p, 0.12)
place(sfx, tone(1500, 0.1, 30), 11.3, 0.1)
# stingers on rule cards / big cuts
for t0, g in ((22.4, 0.9), (30.2, 0.9), (38.2, 0.9), (52.4, 1.0), (75.8, 1.0), (85.2, 0.8), (0.0, 0.5)):
    place(sfx, boom(), t0, g)
# clock spin
for k in range(18):
    place(sfx, tick(), 41.8 + k * 0.05, 0.5)
place(sfx, noise_burst(0.9, 300, 6000, 0.4, 2), 41.4, 0.3)
place(sfx, tone(1200, 0.4, 8, ((1, 1), (2, 0.3))), 42.7, 0.2)
# knocks behind the bus (rule 1)
place(sfx, thump(0.5, 70), 26.9, 0.9)
place(sfx, thump(0.5, 70), 27.4, 0.9)
# brakes + hiss at the empty stop
place(sfx, noise_burst(1.2, 2500, 9000, 0.05, 2.0), 46.4, 0.25)
place(sfx, tone(2600, 0.8, 4) * 0.4, 46.5, 0.06)
place(sfx, noise_burst(1.0, 1500, 8000, 0.02, 3.0), 47.6, 0.3)
# footsteps
for p in (49.9, 50.5, 51.1, 51.7, 52.2):
    place(sfx, thump(0.45, 50), p, 1.0)
place(sfx, noise_burst(0.7, 60, 500, 0.08, 4), 52.45, 0.5)   # seat creak / weight
# heartbeat under the head turn
hb = 53.2
while hb < 57.4:
    place(sfx, thump(0.3, 40), hb, 0.7)
    place(sfx, thump(0.3, 38), hb + 0.18, 0.5)
    hb += 0.72
# bell: ding ding
place(sfx, bell(), 57.6, 0.45)
place(sfx, bell(), 57.95, 0.4)
# doors
place(sfx, noise_burst(1.3, 1500, 9000, 0.05, 2.2), 58.6, 0.35)
place(sfx, thump(0.3, 90), 59.8, 0.4)
# whisper sting / no-shadow hit
place(sfx, noise_burst(1.6, 3000, 9000, 0.6, 1.5), 73.4, 0.12)
place(sfx, tone(110, 3.0, 0.9, ((1, 1), (1.5, 0.5), (2.03, 0.3))), 75.8, 0.35)
# choice: riser + pops
place(sfx, riser(6.4), 78.6, 0.35)
place(sfx, tone(880, 0.15, 25), 79.2, 0.2)
place(sfx, tone(660, 0.15, 25), 79.45, 0.2)
place(sfx, tone(220, 1.8, 2, ((1, 1), (1.5, 0.4))), 86.6, 0.2)

# ---------------------------------------------------------------- voiceover
vo = np.zeros(N, np.float32)
meta = json.load(open(f"{SCR}/vo/vo.json"))
for m in meta:
    a = np.load(f"{SCR}/vo/vo_{m['i']:02d}.npy").astype(np.float32)
    a = a / (np.max(np.abs(a)) + 1e-9)
    g = {"narr": 0.85, "mum": 0.7, "whisper": 0.75}[m["voice"]]
    place(vo, a, m["start"], g)

# duck music/sfx beds under voice
vo_env = np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same")
duck = 1 - 0.55 * np.clip(vo_env / 0.08, 0, 1)
mixd = music * duck + sfx * 0.5 + vo
# soft limiter + stereo widening of beds
mixd = np.tanh(mixd * 1.1) / np.tanh(1.1)
mixd = mixd / np.max(np.abs(mixd)) * 0.93
wide = np.roll(music * duck, 300) * 0.06
L = np.clip(mixd + wide, -1, 1)
R = np.clip(mixd - wide, -1, 1)
st = (np.stack([L, R], 1) * 32767).astype(np.int16)
with wave.open(f"{SCR}/soundtrack.wav", "w") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(st.tobytes())
print("ok", st.shape)

if os.environ.get("STATS"):
    def rms(x, a, b):
        s = x[int(a * SR):int(b * SR)]
        return 20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-9)
    for a, b in ((5.8, 7.4), (8.0, 8.4), (14, 16), (50, 52), (53, 55), (84, 85)):
        print(a, b, "vo %.1f  music %.1f  sfx %.1f" % (rms(vo, a, b), rms(music * duck, a, b), rms(sfx * 0.8, a, b)))
