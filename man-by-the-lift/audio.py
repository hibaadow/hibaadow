"""Soundtrack for THE MAN BY THE LIFT: drone, building hum, lift dings, locks, knocks, phone, CCTV."""
import json, os, wave
import numpy as np

SCR = os.environ["SCR"]
SR = 44100
VO = json.load(open(f"{SCR}/vo_lift/vo.json"))
DUR = VO[-1]["start"] + VO[-1]["dur"] + 3.0


def M(t):
    return t


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


# ---------------------------------------------------------------- timeline helpers
SHOT = {}
for m in VO:
    SHOT.setdefault(m["shot"], max(0.0, m["start"] - 0.15))


def items(shot):
    return [m for m in VO if m["shot"] == shot]


def chunk_t(m, k, edge=0):
    return m["start"] + m["chunks"][k][edge]


def lift_ding():
    a = tone(1175, 1.2, 3.5, ((1, 1), (2.0, 0.25), (3.0, 0.1)))
    b = tone(880, 1.4, 3.0, ((1, 1), (2.0, 0.25)))
    out = np.zeros(int(1.8 * SR), np.float32)
    out[:len(a)] += a
    out[int(0.32 * SR):int(0.32 * SR) + len(b)] += b
    return out


def clack():
    return noise_burst(0.12, 600, 5000, 0.0005, 70) * 0.9 + thump(0.12, 180) * 0.5


def knock():
    return thump(0.3, 95) * 0.9 + noise_burst(0.3, 300, 3000, 0.0005, 80) * 0.4


# ---------------------------------------------------------------- beds
drone = (np.sin(2 * np.pi * 43.65 * tt) + 0.8 * np.sin(2 * np.pi * 44.0 * tt)
         + 0.3 * np.sin(2 * np.pi * 65.4 * tt + np.sin(tt * 0.3))).astype(np.float32) / 2.1
drone += norm(fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=60, hi=260)) * 0.25
hum = norm(fft_filter(rng.normal(0, 1, N).astype(np.float32), lo=50, hi=140)) * 0.5   # building ventilation
hum += (np.sin(2 * np.pi * 50 * tt) * 0.15).astype(np.float32)
end = DUR
drone *= env([(0, 0), (1.0, 0.55), (SHOT["cctv"], 0.7), (SHOT["cctv2"], 0.9), (SHOT["card5"], 0.6),
              (SHOT["polaroid"], 1.0), (SHOT["card6"], 0.5), (SHOT["twodoors"], 0.9), (SHOT["open"] - 0.05, 1.0),
              (SHOT["open"], 0.2), (SHOT["open"] + 0.4, 1.0), (end - 1, 0.5), (end, 0)])
music = (drone * 0.5 + hum * 0.25) * 0.45

# ---------------------------------------------------------------- sfx
sfx = np.zeros(N, np.float32)
cards = [k for k in SHOT if k.startswith("card")]
for c in cards:
    place(sfx, boom(), SHOT[c], 0.8)
# hallway: lift ding, keys
place(sfx, lift_ding(), SHOT["hall"] + 0.3, 0.25)
for k in range(4):
    place(sfx, tone(3000 + 300 * k, 0.12, 30), SHOT["hall"] + 0.8 + k * 0.05, 0.08)
# deadbolt: lock / unlock / lock
for shot in ("lock", "lock2"):
    m = items(shot)[0]
    c0, c1 = chunk_t(m, 1, 0), chunk_t(m, 1, 1)
    for k in range(3):
        place(sfx, clack(), c0 + k * (c1 - c0) / 3, 0.8)
# the lift opens behind him, he doesn't turn
m = items("peep")[1]
place(sfx, lift_ding(), m["start"] - 0.2, 0.25)
place(sfx, noise_burst(1.0, 200, 2000, 0.3, 2), m["start"] + 0.2, 0.15)
# phones: buzz + message pops
place(sfx, buzz(0.95), SHOT["phone1"], 0.6)
for shot in ("phone1", "phone2", "phone3", "phone4", "phone5"):
    for m in items(shot):
        if m["voice"] == "him":
            place(sfx, buzz(0.5), m["start"] - 0.25, 0.35)
            place(sfx, tone(1046, 0.15, 25), m["start"], 0.15)
# three quiet, precise knocks
m = items("knock")[0]
k0 = chunk_t(m, 0, 1) + 0.05
for k in range(3):
    place(sfx, knock(), k0 + k * 0.32, 0.9)
heartbeat_track(SHOT["knock"], SHOT["peep2"] + 1.5, 80, 100, 0.4)
# reception: lobby tone, keyboard
for k in range(14):
    place(sfx, noise_burst(0.03, 1500, 7000, 0.0005, 150), SHOT["recep"] + 0.3 + k * 0.11, 0.12)
place(sfx, tone(659, 0.6, 4), SHOT["plan"] + 0.1, 0.12)
# CCTV: static and beeps
place(sfx, noise_burst(1.0, 2000, 9000, 0.01, 1.5), SHOT["cctv"], 0.25)
for k in range(5):
    place(sfx, tone(1500, 0.08, 40), SHOT["cctv"] + 0.5 + k * 1.2, 0.08)
m = items("cctv2")[0]
place(sfx, boom(), chunk_t(m, 3, 0), 1.0)
heartbeat_track(SHOT["cctv"], SHOT["card5"], 85, 125, 0.45)
# the door behind the wardrobe, the passage
place(sfx, noise_burst(1.2, 100, 1200, 0.4, 1.5), SHOT["wardrobe"] + 0.5, 0.35)
place(sfx, tone(160, 2.0, 1.2, ((1, 1), (1.5, 0.5))), SHOT["lair"], 0.18)
for k in range(10):
    place(sfx, noise_burst(0.04, 1500, 6000, 0.001, 60), SHOT["wall"] + chunk_t(items("wall")[0], 1, 0) - SHOT["wall"] + k * 0.12, 0.12)
m = items("polaroid")[0]
place(sfx, boom(), chunk_t(m, 2, 0), 1.0)
heartbeat_track(SHOT["lair"], SHOT["card6"], 90, 130, 0.45)
# new building
place(sfx, lift_ding(), chunk_t(items("newhall")[0], 3, 0) - 0.4, 0.3)
heartbeat_track(SHOT["phone5"], SHOT["open"], 85, 135, 0.5)
place(sfx, noise_burst(1.6, 150, 1500, 0.8, 1.0), SHOT["open"] - 0.6, 0.3)   # door creak/air
place(sfx, boom(), SHOT["open"], 1.2)
place(sfx, boom(), SHOT["outro"], 0.6)

# ---------------------------------------------------------------- voiceover
vo = np.zeros(N, np.float32)
for m in VO:
    a = np.load(f"{SCR}/vo_lift/vo_{m['i']:02d}.npy").astype(np.float32)
    a = a / (np.max(np.abs(a)) + 1e-9)
    g = {"her": 0.85, "him": 0.72, "neigh": 0.8, "recep": 0.8}[m["voice"]]
    place(vo, a, m["start"], g, mapped=False)

vo_env = np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same")
duck = 1 - 0.55 * np.clip(vo_env / 0.08, 0, 1)
mixd = music * duck + sfx * 0.5 * (1 - 0.3 * np.clip(vo_env / 0.08, 0, 1)) + vo
mixd = np.tanh(mixd * 1.1) / np.tanh(1.1)
mixd = mixd / np.max(np.abs(mixd)) * 0.93
wide = np.roll(music * duck, 300) * 0.06
st = (np.stack([np.clip(mixd + wide, -1, 1), np.clip(mixd - wide, -1, 1)], 1) * 32767).astype(np.int16)
with wave.open(f"{SCR}/soundtrack_lift.wav", "w") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(st.tobytes())
print("ok", round(DUR, 2))
