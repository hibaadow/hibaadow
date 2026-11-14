"""THE LAST BUS — frame renderer. Flat 2D vector look, drawn with Pillow.

usage: python render.py <start_frame> <end_frame> <out.mp4>     (render a range to video)
       python render.py --still <t> <out.png>                    (single frame)
"""
import json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.environ.get("SCR", HERE)
W, H, FPS, DUR = 1080, 1920, 30, 90.0
SS = 2        # supersampling for the base layer
GS = 0.25     # glow layer scale

# ---------------------------------------------------------------- palette
NAVY0 = (7, 9, 26)
NAVY1 = (13, 16, 44)
NAVY2 = (21, 25, 64)
INDIGO = (36, 39, 96)
INDIGO2 = (50, 53, 124)
AMBER = (255, 184, 74)
AMBER_D = (150, 98, 40)
WHITE = (246, 246, 250)
RED = (232, 36, 46)
LIME = (198, 241, 53)
BLUE = (126, 204, 255)
ORANGE = (255, 140, 40)
BLACK = (3, 3, 10)

FONTS = {
    "anton": f"{SCR}/fonts/Anton.ttf",
    "inter": "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "interx": "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "inters": "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
    "mono": "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-ExtraBold.ttf",
    "vt": f"{SCR}/fonts/VT323.ttf",
    "emoji": "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
}
_fc = {}


def F(name, size):
    k = (name, int(size))
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FONTS[name], int(size))
    return _fc[k]


# ---------------------------------------------------------------- easing
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def lerp(a, b, u):
    return a + (b - a) * u


def ease(u):
    u = clamp(u)
    return u * u * (3 - 2 * u)


def eout(u):
    u = clamp(u)
    return 1 - (1 - u) ** 3


def prog(t, a, b):
    return clamp((t - a) / (b - a))


def mix(c1, c2, u):
    return tuple(int(lerp(a, b, u)) for a, b in zip(c1, c2))


def hrand(i, s=0):
    """deterministic hash random in [0,1)"""
    x = math.sin(i * 127.1 + s * 311.7) * 43758.5453
    return x - math.floor(x)


# ---------------------------------------------------------------- canvas
class Cv:
    def __init__(s, bg=NAVY0):
        s.im = Image.new("RGB", (W * SS, H * SS), bg)
        s.d = ImageDraw.Draw(s.im, "RGBA")
        s.gl = Image.new("RGB", (int(W * GS), int(H * GS)), (0, 0, 0))
        s.gd = ImageDraw.Draw(s.gl, "RGBA")

    @staticmethod
    def P(pts):
        return [(x * SS, y * SS) for x, y in pts]

    def rect(s, x0, y0, x1, y1, c):
        s.d.rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=c)

    def rrect(s, x0, y0, x1, y1, r, c=None, outline=None, w=0):
        s.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=r * SS,
                              fill=c, outline=outline, width=int(w * SS))

    def ell(s, cx, cy, rx, ry, c=None, outline=None, w=0):
        s.d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS],
                    fill=c, outline=outline, width=int(w * SS))

    def circ(s, cx, cy, r, c=None, outline=None, w=0):
        s.ell(cx, cy, r, r, c, outline, w)

    def poly(s, pts, c):
        s.d.polygon(s.P(pts), fill=c)

    def line(s, pts, c, w, caps=True):
        s.d.line(s.P(pts), fill=c, width=max(1, int(w * SS)), joint="curve")
        if caps:
            for x, y in (pts[0], pts[-1]):
                s.circ(x, y, w / 2, c)

    def text(s, xy, txt, font, size, c, anchor="mm", spacing=0):
        f = F(font, size * SS)
        x, y = xy
        if spacing:
            # manual letter spacing
            widths = [f.getlength(ch) for ch in txt]
            tot = sum(widths) + spacing * SS * (len(txt) - 1)
            cx = x * SS - tot / 2 if anchor[0] == "m" else x * SS
            for ch, wd in zip(txt, widths):
                s.d.text((cx, y * SS), ch, font=f, fill=c, anchor="l" + anchor[1])
                cx += wd + spacing * SS
        else:
            s.d.text((x * SS, y * SS), txt, font=f, fill=c, anchor=anchor)

    # glow layer (additive, blurred)
    def glow(s, cx, cy, r, c, a=255):
        s.gd.ellipse([(cx - r) * GS, (cy - r) * GS, (cx + r) * GS, (cy + r) * GS], fill=c + (a,))

    def glow_ell(s, cx, cy, rx, ry, c, a=255):
        s.gd.ellipse([(cx - rx) * GS, (cy - ry) * GS, (cx + rx) * GS, (cy + ry) * GS], fill=c + (a,))

    def glow_rect(s, x0, y0, x1, y1, c, a=255):
        s.gd.rectangle([x0 * GS, y0 * GS, x1 * GS, y1 * GS], fill=c + (a,))

    def glow_poly(s, pts, c, a=255):
        s.gd.polygon([(x * GS, y * GS) for x, y in pts], fill=c + (a,))


def camera(cv, cx, cy, z, blur=7):
    z = max(z, 1.0)
    hw, hh = W / 2 / z, H / 2 / z
    cx = clamp(cx, hw, W - hw)
    cy = clamp(cy, hh, H - hh)
    box = (cx - hw, cy - hh, cx + hw, cy + hh)
    out = cv.im.resize((W, H), Image.BILINEAR, box=tuple(v * SS for v in box))
    g = cv.gl.filter(ImageFilter.GaussianBlur(blur))
    g = g.resize((W, H), Image.BILINEAR, box=tuple(v * GS for v in box))
    out = ImageChops.add(out, g)
    return out


def to_screen(cam, x, y):
    cx, cy, z = cam
    z = max(z, 1.0)
    cx = clamp(cx, W / 2 / z, W - W / 2 / z)
    cy = clamp(cy, H / 2 / z, H - H / 2 / z)
    return (x - cx) * z + W / 2, (y - cy) * z + H / 2


# ---------------------------------------------------------------- caches
_cache = {}


def gradient(w, h, c0, c1, key):
    if key not in _cache:
        a = np.linspace(0, 1, h * SS)[:, None, None]
        arr = (np.array(c0)[None, None, :] * (1 - a) + np.array(c1)[None, None, :] * a)
        arr = np.repeat(arr, w * SS, axis=1).astype(np.uint8)
        _cache[key] = Image.fromarray(arr, "RGB")
    return _cache[key]


def skyline_strip(key, length, hmin, hmax, wmin, wmax, color, win_color, base_h, seed, win_p=0.12):
    """long horizontal strip of building silhouettes (RGBA at SS), cached"""
    if key in _cache:
        return _cache[key]
    im = Image.new("RGBA", (length * SS, base_h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x, i = 0, 0
    rng = np.random.default_rng(seed)
    while x < length:
        bw = int(rng.uniform(wmin, wmax))
        bh = int(rng.uniform(hmin, hmax))
        d.rectangle([x * SS, (base_h - bh) * SS, (x + bw) * SS, base_h * SS], fill=color + (255,))
        if rng.random() < 0.3:  # antenna
            d.rectangle([(x + bw // 2) * SS, (base_h - bh - 30) * SS, (x + bw // 2 + 3) * SS, (base_h - bh) * SS], fill=color + (255,))
        for wy in range(base_h - bh + 14, base_h - 10, 22):
            for wx in range(x + 8, x + bw - 10, 16):
                if rng.random() < win_p:
                    d.rectangle([wx * SS, wy * SS, (wx + 7) * SS, (wy + 10) * SS], fill=win_color + (255,))
        x += bw + int(rng.uniform(0, 12))
        i += 1
    _cache[key] = im
    return im


def paste_strip(cv, strip, offset, y, length):
    """paste looping strip scrolled by offset at y (1x units)"""
    sw = strip.width // SS
    off = int(offset) % sw
    x = -off
    while x < W + 10:
        cv.im.paste(strip, (int(x * SS), int(y * SS)), strip)
        x += sw


# ---------------------------------------------------------------- 5x7 LED font
G = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    ".": ["..", "..", "..", "..", "..", "##", "##"],
    ",": ["..", "..", "..", "..", "##", ".#", "#."],
    "'": ["##", ".#", "#.", "..", "..", "..", ".."],
    "!": ["#", "#", "#", "#", "#", ".", "#"],
    "?": [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
    ":": ["..", "##", "##", "..", "##", "##", ".."],
    "-": ["....", "....", "....", "####", "....", "....", "...."],
    "#": [".#.#.", ".#.#.", "#####", ".#.#.", "#####", ".#.#.", ".#.#."],
    ">": ["#...", ".#..", "..#.", "...#", "..#.", ".#..", "#..."],
    "<": ["...#", "..#.", ".#..", "#...", ".#..", "..#.", "...#"],
    " ": ["...", "...", "...", "...", "...", "...", "..."],
}


def led_text_bits(txt):
    cols = []
    for i, ch in enumerate(txt):
        g = G.get(ch, G[" "])
        for c in range(len(g[0])):
            cols.append([g[r][c] == "#" for r in range(7)])
        if i < len(txt) - 1:
            cols.append([False] * 7)
    return np.array(cols, dtype=bool).T if cols else np.zeros((7, 0), bool)  # (7, n)


def led_width(txt):
    return led_text_bits(txt).shape[1]


def draw_led(cv, x0, y0, cols, rows, pitch, layers, off_col=(34, 20, 10), glow_a=200, flick=1.0):
    """layers: list of (text, color, col_offset or 'c', row_offset). flick: 0..1 brightness"""
    grid = np.zeros((rows, cols), dtype=np.int16) - 1
    colors = []
    for li, (txt, col, cx, ry) in enumerate(layers):
        b = led_text_bits(txt)
        n = b.shape[1]
        if cx == "c":
            cx = (cols - n) // 2
        cx = int(round(cx))
        for c in range(n):
            gc = cx + c
            if 0 <= gc < cols:
                for r in range(7):
                    if b[r, c] and 0 <= ry + r < rows:
                        grid[ry + r, gc] = li
        colors.append(col)
    rad = pitch * 0.36
    for r in range(rows):
        for c in range(cols):
            px, py = x0 + (c + 0.5) * pitch, y0 + (r + 0.5) * pitch
            li = grid[r, c]
            if li >= 0 and flick > 0.05:
                col = mix(off_col, colors[li], flick)
                cv.circ(px, py, rad, col)
                cv.glow(px, py, pitch * 0.85, colors[li], int(glow_a * flick))
            else:
                cv.circ(px, py, rad, off_col)


# ---------------------------------------------------------------- characters
HOODIE = (206, 32, 44)
HOODIE_D = (150, 20, 32)
JOG = (16, 16, 22)
JOG_RIM = (70, 74, 120)


def you_seated(cv, x, head_y, eyes=None, look=0.0):
    """main character: white stick figure in a red hoodie and black joggers, seated, facing camera"""
    r = 60
    neck = head_y + r
    hip = neck + 290
    sh = neck + 60
    # hood (behind the head)
    cv.ell(x, head_y + 34, 82, 66, HOODIE_D)
    # joggers
    for sg in (-1, 1):
        leg = [(x + sg * 14, hip), (x + sg * 88, hip + 62), (x + sg * 80, hip + 255)]
        cv.line(leg, JOG_RIM, 42)
        cv.line(leg, JOG, 36)
        cv.rect(x + sg * 80 - 21, hip + 236, x + sg * 80 + 21, hip + 256, (40, 42, 60))   # cuffs
        cv.line([(x + sg * 80, hip + 262), (x + sg * 116, hip + 266)], WHITE, 18)        # white trainers
    # hoodie body
    body = [(x - 58, neck + 8), (x + 58, neck + 8), (x + 66, hip + 18), (x - 66, hip + 18)]
    cv.poly(body, HOODIE)
    cv.rrect(x - 66, hip - 6, x + 66, hip + 22, 8, HOODIE_D)               # waistband
    cv.rrect(x - 44, hip - 100, x + 44, hip - 30, 14, HOODIE_D)            # front pocket
    cv.ell(x, neck + 10, 36, 18, HOODIE_D)                                # neckline
    for dx in (-12, 12):                                                  # drawstrings
        cv.line([(x + dx, neck + 16), (x + dx * 1.2, neck + 80)], WHITE, 4)
    # sleeves + hands
    for sg in (-1, 1):
        arm = [(x + sg * 50, sh - 30), (x + sg * 66, sh + 135), (x + sg * 82, hip + 40)]
        cv.line(arm, HOODIE_D, 40)
        cv.line(arm, HOODIE, 34)
        cv.circ(x + sg * 84, hip + 60, 13, WHITE)
    # head
    rx = r * (1 - 0.06 * abs(look))
    cv.ell(x, head_y, rx, r, WHITE)
    if eyes:
        ex = look * 28
        for dx in (-19, 19):
            cv.circ(x + dx + ex, head_y - 6, 7.5, NAVY0)


def stick_figure(cv, x, head_y, scale=1.0, eyes=None, look=0.0, sit=True, wave=None, color=WHITE, lw=15, bun=False):
    s = scale
    r = 60 * s
    hx = x
    rx = r * (1 - 0.06 * abs(look))
    cv.ell(hx, head_y, rx, r, color)
    if bun:
        cv.circ(hx + 8 * s, head_y - r - 10 * s, 22 * s, color)
    neck = head_y + r
    if sit:
        hip = neck + 290 * s
        cv.line([(x, neck - 4), (x, hip)], color, lw * s)
        sh = neck + 60 * s
        for sg in (-1, 1):
            cv.line([(x, sh), (x + sg * 58 * s, sh + 135 * s), (x + sg * 80 * s, hip + 58 * s)], color, lw * s)
            cv.line([(x + sg * 6 * s, hip), (x + sg * 88 * s, hip + 62 * s), (x + sg * 80 * s, hip + 270 * s), (x + sg * 112 * s, hip + 272 * s)], color, lw * s)
    else:
        hip = neck + 300 * s
        cv.line([(x, neck - 4), (x, hip)], color, lw * s)
        sh = neck + 55 * s
        cv.line([(x, sh), (x - 70 * s, sh + 130 * s), (x - 85 * s, sh + 250 * s)], color, lw * s)
        if wave is None:
            cv.line([(x, sh), (x + 70 * s, sh + 130 * s), (x + 85 * s, sh + 250 * s)], color, lw * s)
        else:
            ex, ey = x + 95 * s, sh - 40 * s
            ang = -1.2 + 0.45 * math.sin(wave)
            hxx, hyy = ex + 110 * s * math.cos(ang), ey + 110 * s * math.sin(ang)
            cv.line([(x, sh), (ex, ey), (hxx, hyy)], color, lw * s)
        cv.line([(x, hip), (x - 55 * s, hip + 280 * s), (x - 80 * s, hip + 285 * s)], color, lw * s)
        cv.line([(x, hip), (x + 55 * s, hip + 280 * s), (x + 80 * s, hip + 285 * s)], color, lw * s)
    if eyes:
        ex = look * 28 * s
        for dx in (-19, 19):
            cv.circ(hx + dx * s + ex, head_y - 6 * s, 7.5 * s, NAVY0)


def creature(cv, x, head_y, turn=0.0, eye_a=1.0, scale=1.0):
    """tall black figure, oval head, two small white eyes. turn: 0 = facing camera, 1 = facing left (you)"""
    s = scale
    rim = (58, 60, 140)
    rx, ry = 58 * s * (1 - 0.1 * turn), 90 * s
    hip = head_y + 620 * s
    # body
    torso = [(x - 70 * s, head_y + 130 * s), (x + 70 * s, head_y + 130 * s), (x + 34 * s, hip), (x - 34 * s, hip)]
    cv.poly([(px - 3, py) for px, py in torso], rim)
    cv.poly(torso, BLACK)
    cv.line([(x, head_y + ry - 10), (x, head_y + 140 * s)], BLACK, 30 * s)
    for sgn in (-1, 1):
        arm = [(x + sgn * 66 * s, head_y + 140 * s), (x + sgn * 92 * s, head_y + 420 * s), (x + sgn * 70 * s, hip + 90 * s)]
        cv.line(arm, rim, 26 * s)
        cv.line(arm, BLACK, 20 * s)
        leg = [(x + sgn * 26 * s, hip), (x + sgn * 70 * s, hip + 80 * s), (x + sgn * 68 * s, hip + 380 * s), (x + sgn * 100 * s, hip + 386 * s)]
        cv.line(leg, rim, 30 * s)
        cv.line(leg, BLACK, 24 * s)
    cv.ell(x - turn * 6 * s, head_y, rx + 3, ry + 3, rim)
    cv.ell(x - turn * 6 * s, head_y, rx, ry, BLACK)
    if eye_a > 0.02:
        ex = -turn * 30 * s
        for dx in (-17, 17):
            ddx = dx * (1 - 0.35 * turn)
            c = mix(BLACK, (255, 255, 255), eye_a)
            cv.ell(x + ddx * s + ex, head_y - 8 * s, 7 * s, 8 * s, c)
            cv.glow(x + ddx * s + ex, head_y - 8 * s, 18 * s, (200, 200, 230), int(120 * eye_a))


# ---------------------------------------------------------------- environment pieces
RAIN = [(hrand(i, 1) * 1300 - 100, hrand(i, 2) * 2100, 1500 + hrand(i, 3) * 900, 30 + hrand(i, 4) * 60) for i in range(260)]


def rain(cv, t, box=(0, 0, W, H), alpha=70, n=260, slant=0.18, speed=1.0):
    x0, y0, x1, y1 = box
    hgt = y1 - y0 + 200
    for i in range(n):
        rx, ry, sp, ln = RAIN[i % len(RAIN)]
        x = x0 + (rx / 1300) * (x1 - x0 + 100) - 50
        y = y0 - 100 + (ry + sp * t * speed) % hgt
        xa, ya, xb, yb = x, y, x - ln * slant, y + ln
        if yb < y0 or ya > y1:
            continue
        ya2, yb2 = max(ya, y0), min(yb, y1)
        fa = (ya2 - ya) / ln
        fb = (yb2 - ya) / ln
        pa = (xa + (xb - xa) * fa, ya2)
        pb = (xa + (xb - xa) * fb, yb2)
        if pa[0] < x0 or pa[0] > x1:
            continue
        cv.d.line([(pa[0] * SS, pa[1] * SS), (pb[0] * SS, pb[1] * SS)], fill=(170, 190, 255, alpha), width=2 * SS // 2 + 1)


def glass_drops(cv, t, box, n=40, seed=5):
    x0, y0, x1, y1 = box
    for i in range(n):
        x = x0 + 10 + hrand(i, seed) * (x1 - x0 - 20)
        sp = 8 + hrand(i, seed + 1) * 50
        y = y0 + ((hrand(i, seed + 2) * (y1 - y0)) + sp * t) % (y1 - y0 - 10)
        r = 3 + hrand(i, seed + 3) * 5
        cv.ell(x, y, r, r * 1.2, (150, 170, 240, 60))
        if sp > 35:
            cv.d.line([(x * SS, (y - 60) * SS), (x * SS, y * SS)], fill=(150, 170, 240, 30), width=3)


def moon(cv, x, y, r):
    cv.glow(x, y, r * 3.2, (90, 100, 170), 90)
    cv.glow(x, y, r * 1.6, (200, 200, 220), 90)
    cv.circ(x, y, r, (236, 233, 214))
    cv.circ(x - r * 0.3, y - r * 0.2, r * 0.18, (214, 210, 192))
    cv.circ(x + r * 0.35, y + r * 0.3, r * 0.12, (214, 210, 192))


def stars(cv, box, n=40, seed=9):
    x0, y0, x1, y1 = box
    for i in range(n):
        x = x0 + hrand(i, seed) * (x1 - x0)
        y = y0 + hrand(i, seed + 1) * (y1 - y0)
        cv.circ(x, y, 1.5 + hrand(i, seed + 2) * 1.5, (190, 195, 235, 150))


# ---------------------------------------------------------------- SHOTS
# every shot: fn(cv, t, lt, **kw) -> (cx, cy, z) camera in scene coords. t = global time, lt = local time

def shot_ext_bus(cv, t, lt, speed=1.0, bx=0, stop_at=None, z0=1.0, z1=1.1, cyc=1000, dur=3.4, shelter=False):
    # scroll distance with deceleration
    if stop_at is None:
        dist = 520 * t
    else:
        a, b = stop_at
        # moving until a, decel to b, then stopped
        def pos(tt):
            if tt < a:
                return 520 * tt
            if tt < b:
                u = (tt - a) / (b - a)
                return 520 * a + 520 * (b - a) * (u - u * u / 2)
            return 520 * a + 520 * (b - a) * 0.5
        dist = pos(t)
    moving = stop_at is None or t < stop_at[1]
    cv.im.paste(gradient(W, 1440, (5, 7, 24), (30, 28, 78), "extsky"), (0, 0))
    stars(cv, (0, 0, W, 700))
    moon(cv, 800, 320, 72)
    paste_strip(cv, skyline_strip("sky_far", 2400, 260, 620, 60, 160, (17, 19, 52), (90, 70, 50), 700, 1, 0.08), dist * 0.15, 560, 2400)
    paste_strip(cv, skyline_strip("sky_near", 2600, 160, 420, 90, 220, (10, 11, 33), (130, 92, 45), 560, 2, 0.12), dist * 0.4, 880, 2600)
    # street lamps (behind bus)
    for k in range(-1, 4):
        lx = (k * 700 - dist * 0.8) % 2800 - 400
        cv.rect(lx - 6, 760, lx + 6, 1440, (18, 20, 46))
        cv.rect(lx - 6, 760, lx + 60, 772, (18, 20, 46))
        cv.ell(lx + 60, 780, 22, 10, AMBER)
        cv.glow(lx + 60, 790, 120, AMBER, 110)
    # pavement + road
    cv.rect(0, 1440, W, 1500, (22, 24, 54))
    cv.rect(0, 1500, W, H, (12, 13, 32))
    for k in range(8):
        dx = (k * 300 - dist) % 2400 - 200
        cv.rect(dx, 1700, dx + 150, 1712, (60, 62, 100))
    # empty shelter at the stop
    if shelter:
        sx = 700 + (bx if False else 0)
        flick = 0.25 + 0.75 * (hrand(int(t * 12), 77) > 0.35)
        cv.rect(sx, 1000, sx + 330, 1024, (28, 30, 70))
        cv.rect(sx + 10, 1024, sx + 22, 1440, (28, 30, 70))
        cv.rect(sx + 308, 1024, sx + 320, 1440, (28, 30, 70))
        cv.rect(sx + 22, 1050, sx + 308, 1330, (60, 70, 140, 50))
        cv.rect(sx + 60, 1330, sx + 270, 1346, (30, 32, 74))
        cv.ell(sx + 165, 1034, 70, 8, mix((60, 40, 20), AMBER, flick))
        cv.poly([(sx + 100, 1034), (sx + 230, 1034), (sx + 320, 1440), (sx + 10, 1440)], AMBER + (int(40 * flick),))
        cv.glow(sx + 165, 1050, 140, AMBER, int(120 * flick))
    # bus
    bob = 4 * math.sin(t * 9) if moving else 0
    by = bob
    X0, X1 = 90 + bx, 990 + bx
    cv.rrect(X0, 770 + by, X1, 1420 + by, 46, (40, 46, 112))
    cv.rect(X0, 1040 + by, X1, 1090 + by, (30, 34, 86))          # mid band
    cv.rect(X0, 1330 + by, X1, 1420 + by, (28, 31, 78))
    # upper windows
    for i in range(5):
        wx = X0 + 40 + i * 150
        cv.rrect(wx, 830 + by, wx + 132, 1000 + by, 14, (120, 82, 40))
    # front upper window
    cv.rrect(X1 - 100, 830 + by, X1 - 22, 1000 + by, 14, (110, 76, 38))
    # you, top deck window 3 (white stick head + shoulders)
    wx = X0 + 40 + 2 * 150
    cv.ell(wx + 66, 922 + by, 34, 26, HOODIE_D)
    cv.poly([(wx + 40, 935 + by), (wx + 92, 935 + by), (wx + 100, 1000 + by), (wx + 32, 1000 + by)], HOODIE)
    cv.circ(wx + 66, 905 + by, 26, WHITE)
    # lower windows
    for i in range(4):
        wx = X0 + 40 + i * 170
        cv.rrect(wx, 1115 + by, wx + 150, 1280 + by, 12, (90, 62, 34))
    # doors
    cv.rrect(X1 - 150, 1110 + by, X1 - 40, 1410 + by, 8, (70, 52, 34))
    cv.rect(X1 - 96, 1110 + by, X1 - 94, 1410 + by, (40, 46, 112))
    # destination box
    cv.rrect(X1 - 110, 784 + by, X1 - 20, 822 + by, 6, (10, 8, 6))
    draw_led(cv, X1 - 105, 788 + by, 13, 9, 3.4, [("13", AMBER, "c", 1)], glow_a=120)
    # headlight
    cv.ell(X1 - 14, 1360 + by, 14, 20, (255, 220, 150))
    cv.glow(X1 + 40, 1370 + by, 120, AMBER, 140)
    cv.poly([(X1 - 10, 1350 + by), (X1 + 600, 1300), (X1 + 600, 1500)], AMBER + (35,))
    # window glows + wet reflections
    for i in range(5):
        cv.glow_rect(X0 + 40 + i * 150, 830 + by, X0 + 172 + i * 150, 1000 + by, AMBER, 60)
    for i in range(4):
        rx = X0 + 40 + i * 170
        cv.rect(rx + 20, 1520, rx + 130, 1900, (90, 62, 34, 26))
    # wheels
    for wx in (X0 + 180, X1 - 240):
        cv.circ(wx, 1420, 84, (18, 20, 48))
        cv.circ(wx, 1420, 72, (8, 8, 18))
        cv.circ(wx, 1420, 34, (70, 72, 110))
        ang = -dist / 72
        for k in range(5):
            a = ang + k * 2 * math.pi / 5
            cv.line([(wx, 1420), (wx + 30 * math.cos(a), 1420 + 30 * math.sin(a))], (40, 42, 80), 6, caps=False)
    # foreground lamp passing (parallax fast)
    rain(cv, t, (0, 0, W, H), alpha=55, n=200)
    u = eout(prog(lt, 0, dur))
    return (540, cyc, lerp(z0, z1, u))


def row_scene(cv, t, figure_eyes=None, look=0.0, creature_on=False, c_turn=0.0, c_eyes=1.0,
              sweep=None, handprint=0.0, dim=1.0, fig=True):
    """inside the top deck looking at the back seat + rear window"""
    cv.rect(0, 0, W, H, (18, 21, 54))
    # ceiling
    cv.poly([(0, 0), (W, 0), (930, 300), (150, 300)], (11, 13, 36))
    cv.rect(380, 120, 700, 140, (60, 62, 110))   # strip light
    cv.glow(540, 140, 160, (110, 110, 170), 60)
    # side walls
    cv.poly([(0, 0), (150, 300), (150, 1460), (0, 1700)], (14, 16, 44))
    cv.poly([(W, 0), (930, 300), (930, 1460), (W, 1700)], (14, 16, 44))
    # side windows (light bars sweep past)
    for side in (0, 1):
        if side == 0:
            q = [(20, 260), (130, 380), (130, 860), (20, 900)]
        else:
            q = [(W - 20, 260), (W - 130, 380), (W - 130, 860), (W - 20, 900)]
        cv.poly(q, (9, 11, 30))
        ph = (t * 0.9 + side * 0.37) % 1.0
        if ph < 0.35:
            a = math.sin(ph / 0.35 * math.pi)
            gx = 75 if side == 0 else W - 75
            cv.glow_ell(gx, 580, 70, 260, AMBER, int(150 * a))
            cv.poly(q, AMBER + (int(60 * a),))
    # floor
    cv.poly([(150, 1460), (930, 1460), (W, 1700), (W, H), (0, H), (0, 1700)], (10, 11, 30))
    # rear window
    WX0, WY0, WX1, WY1 = 200, 370, 880, 930
    cv.rrect(WX0 - 16, WY0 - 16, WX1 + 16, WY1 + 16, 50, (32, 36, 84))
    cv.im.paste(gradient(WX1 - WX0, 330, (8, 10, 34), (32, 30, 82), "rearsky"), (WX0 * SS, WY0 * SS))
    cv.rect(WX0, 700, WX1, WY1, (12, 13, 32))
    moon(cv, 760, 470, 36)
    # distant skyline
    for i in range(14):
        bx = WX0 + i * 50
        bh = 20 + hrand(i, 31) * 70
        cv.rect(bx, 700 - bh, bx + 44, 700, (14, 16, 44))
        if hrand(i, 32) > 0.5:
            cv.rect(bx + 14, 700 - bh + 12, bx + 20, 700 - bh + 18, (130, 92, 45))
    # road receding to vanishing point (540,700)
    cv.poly([(530, 700), (550, 700), (WX1 - 40, WY1), (WX0 + 40, WY1)], (20, 20, 44))
    for k in range(6):
        u = (k / 6 + t * 0.35) % 1.0
        y = 700 + 230 * (1 - u) ** 2
        w = 3 + 14 * (1 - u) ** 2
        hgt = 4 + 30 * (1 - u) ** 2
        cv.rect(540 - w / 2, y - hgt, 540 + w / 2, y, (90, 92, 130))
    for k in range(4):
        u = (k / 4 + t * 0.35 + 0.1) % 1.0
        sp = (1 - u) ** 2
        for sgn in (-1, 1):
            lx = 540 + sgn * (30 + 330 * sp)
            ly = 700 + 230 * sp
            ph = 160 * sp + 10
            cv.line([(lx, ly), (lx, ly - ph)], (30, 32, 70), 2 + 5 * sp, caps=False)
            cv.circ(lx - sgn * 8 * sp, ly - ph, 3 + 8 * sp, AMBER)
            cv.glow(lx, ly - ph, 20 + 70 * sp, AMBER, int(90 + 80 * sp))
    rain(cv, t, (WX0, WY0, WX1, WY1), alpha=60, n=120, slant=0.05, speed=0.5)
    glass_drops(cv, t, (WX0, WY0, WX1, WY1), n=36)
    if handprint > 0:
        a = int(110 * handprint)
        hx, hy = 500, 650
        cv.ell(hx, hy, 34, 40, (170, 180, 230, a))
        for k, (dx, ln) in enumerate([(-30, 50), (-12, 66), (6, 70), (24, 60)]):
            cv.line([(hx + dx, hy - 20), (hx + dx * 1.2, hy - 20 - ln)], (170, 180, 230, a), 13)
        cv.line([(hx - 30, hy + 10), (hx - 64, hy - 20)], (170, 180, 230, a), 13)
    # back bench
    cv.rrect(160, 880, 920, 1240, 34, (36, 40, 98))
    cv.rrect(160, 872, 920, 908, 18, (52, 56, 128))
    cv.rect(538, 900, 542, 1230, (26, 29, 72))
    for i in range(18):   # moquette dots
        for j in range(5):
            cv.circ(190 + i * 41 + (j % 2) * 20, 950 + j * 60, 4, (46, 50, 116))
    cv.rrect(150, 1220, 930, 1300, 22, (46, 50, 118))
    cv.rect(160, 1300, 920, 1460, (24, 27, 68))
    # amber streetlight sweep on the empty seat
    if sweep is not None and sweep > 0:
        cv.glow_ell(720, 1080, 260, 330, AMBER, int(190 * sweep))
        cv.poly([(560, 880), (900, 880), (930, 1300), (545, 1300)], AMBER + (int(70 * sweep),))
    if fig:
        you_seated(cv, 350, 820, eyes=figure_eyes, look=look)
    if creature_on:
        creature(cv, 730, 560, turn=c_turn, eye_a=c_eyes)
    if dim < 1:
        cv.rect(0, 0, W, H, (0, 0, 0, int(255 * (1 - dim))))


def shot_row(cv, t, lt, z0=1.05, z1=1.15, c0=(470, 960), c1=(450, 950), dur=4.0, **kw):
    row_scene(cv, t, **kw)
    u = ease(prog(lt, 0, dur))
    return (lerp(c0[0], c1[0], u), lerp(c0[1], c1[1], u), lerp(z0, z1, u))


def front_scene(cv, t, led_layers, led_flick=1.0):
    cv.rect(0, 0, W, H, (16, 19, 50))
    cv.poly([(0, 0), (W, 0), (W, 300), (0, 300)], (11, 13, 36))
    # front window
    WX0, WY0, WX1, WY1 = 50, 560, 1030, 1200
    cv.rrect(WX0 - 18, WY0 - 18, WX1 + 18, WY1 + 18, 50, (30, 34, 82))
    cv.im.paste(gradient(WX1 - WX0, 330, (6, 8, 30), (30, 28, 80), "frontsky"), (WX0 * SS, WY0 * SS))
    cv.rect(WX0, 890, WX1, WY1, (12, 13, 32))
    moon(cv, 250, 680, 44)
    for i in range(20):
        bx = WX0 + i * 50
        bh = 30 + hrand(i, 41) * 110
        cv.rect(bx, 890 - bh, bx + 46, 890, (14, 16, 44))
        if hrand(i, 42) > 0.4:
            cv.rect(bx + 16, 890 - bh + 14, bx + 23, 890 - bh + 22, (130, 92, 45))
    cv.poly([(530, 890), (550, 890), (WX1 - 60, WY1), (WX0 + 60, WY1)], (20, 20, 44))
    for k in range(6):   # dashes approaching
        u = (k / 6 - t * 0.5) % 1.0
        y = 890 + 310 * (1 - u) ** 2
        w = 3 + 16 * (1 - u) ** 2
        hgt = 4 + 40 * (1 - u) ** 2
        cv.rect(540 - w / 2, y - hgt, 540 + w / 2, y, (90, 92, 130))
    for k in range(4):
        u = (k / 4 - t * 0.5 + 0.1) % 1.0
        sp = (1 - u) ** 2
        for sgn in (-1, 1):
            lx = 540 + sgn * (30 + 470 * sp)
            ly = 890 + 310 * sp
            ph = 220 * sp + 10
            cv.line([(lx, ly), (lx, ly - ph)], (30, 32, 70), 2 + 6 * sp, caps=False)
            cv.circ(lx - sgn * 10 * sp, ly - ph, 3 + 9 * sp, AMBER)
            cv.glow(lx, ly - ph, 20 + 90 * sp, AMBER, int(90 + 90 * sp))
    rain(cv, t, (WX0, WY0, WX1, WY1), alpha=70, n=200, slant=0.08, speed=0.7)
    glass_drops(cv, t, (WX0, WY0, WX1, WY1), n=50, seed=11)
    # LED housing above window
    cv.rrect(200, 370, 880, 490, 14, (8, 8, 16), outline=(40, 44, 96), w=4)
    draw_led(cv, 540 - 84 * 7.4 / 2, 397, 84, 9, 7.4, led_layers, flick=led_flick)
    # front seat backs (silhouettes)
    cv.rrect(-40, 1300, 460, 1960, 60, (24, 27, 70))
    cv.rrect(620, 1300, 1120, 1960, 60, (24, 27, 70))
    cv.rrect(-40, 1290, 460, 1330, 20, (40, 44, 104))
    cv.rrect(620, 1290, 1120, 1330, 20, (40, 44, 104))
    cv.rect(0, 1240, W, 1262, (190, 150, 60))      # yellow grab rail
    cv.glow_rect(0, 1240, W, 1262, AMBER, 40)


def shot_front(cv, t, lt, layers_fn, dur=2.6, z0=1.0, z1=1.25):
    layers, fl = layers_fn(t)
    front_scene(cv, t, layers, fl)
    u = ease(prog(lt, 0, dur))
    return (540, lerp(960, 640, u), lerp(z0, z1, u))


LED_COLS, LED_ROWS, LED_P = 78, 17, 12.8
LED_X, LED_Y = 40 + (1000 - LED_COLS * LED_P) / 2, 780


def led_close_scene(cv, t, layers, flick=1.0, color_tint=None):
    cv.rect(0, 0, W, H, (14, 16, 44))
    cv.rect(0, 0, W, 520, (10, 12, 34))
    cv.rect(0, 420, W, 436, (200, 160, 70))          # grab rail
    cv.glow_rect(0, 420, W, 436, AMBER, 50)
    for hx in (180, 540, 900):
        cv.rect(hx - 3, 436, hx + 3, 520, (60, 62, 110))
        cv.ell(hx, 545, 26, 30, None, outline=(60, 62, 110), w=6)
    cv.rect(300, 230, 780, 250, (60, 62, 110))
    cv.glow(540, 250, 200, (110, 110, 170), 50)
    cv.rect(0, 1080, W, H, (16, 19, 50))
    # window strip below with passing lights
    cv.rect(0, 1140, W, 1700, (8, 10, 30))
    for k in range(5):
        lx = (k * 320 - t * 900) % 1700 - 300
        cv.glow(lx, 1420, 140, AMBER, 70)
        cv.circ(lx, 1420, 10, AMBER)
    rain(cv, t, (0, 1140, W, 1700), alpha=60, n=120, slant=0.08)
    cv.rect(0, 1130, W, 1150, (30, 34, 82))
    cv.rect(0, 1690, W, 1710, (30, 34, 82))
    # housing
    cv.rrect(16, 700, 1064, 1060, 26, (6, 6, 12), outline=(46, 50, 110), w=6)
    cv.rect(30, 1040, 1050, 1046, (30, 32, 70))
    cv.text((540, 735), "· NEXT STOP ·", "inters", 22, (80, 84, 140), spacing=6)
    draw_led(cv, LED_X, LED_Y, LED_COLS, LED_ROWS, LED_P, layers, flick=flick)
    cv.glow_rect(40, 780, 1040, 1000, (255, 120, 40), int(25 * flick))


def scroll_layers(txt, color, t0, t, speed, row=5, cols=LED_COLS):
    w = led_width(txt)
    x = cols - (t - t0) * speed
    return [(txt, color, x, row)]


def scroll_in_hold(txt, color, t0, t, speed, row, cols=LED_COLS):
    w = led_width(txt)
    target = (cols - w) // 2
    x = max(target, cols - (t - t0) * speed)
    return (txt, color, x, row)


def flicker(t, a, b, seed=1):
    """random flicker brightness in [a,b]"""
    if t < a or t > b:
        return 1.0
    v = hrand(int(t * 30), seed)
    return 0.0 if v < 0.4 else (0.35 if v < 0.6 else 1.0)


def stair_scene(cv, t, shadow=None, glow_amt=1.0):
    cv.rect(0, 0, W, H, (5, 6, 16))
    # far landing glow
    cv.glow(760, 380, 380, AMBER, int(110 * glow_amt))
    cv.poly([(380, 260), (900, 200), (900, 600), (380, 560)], (40, 30, 24))
    cv.poly([(380, 260), (900, 200), (900, 600), (380, 560)], AMBER + (int(30 * glow_amt),))
    # steps descending (bottom of frame = nearest)
    n = 9
    for k in range(n, -1, -1):
        f = k / n
        y = 560 + 1360 * (1 - f) ** 1.6
        y2 = 560 + 1360 * (1 - (k + 1) / n) ** 1.6 if k < n else 560
        xl = 380 - 380 * (1 - f) ** 1.3
        xr = 900 + 180 * (1 - f) ** 1.3
        shade = 0.25 + 0.75 * (1 - f)
        tread = mix((40, 30, 24), (30, 34, 80), 1 - f)
        tread = mix((8, 8, 20), tread, shade)
        cv.poly([(xl, y), (xr, y), (xr, y - (y - y2) * 0.55), (xl, y - (y - y2) * 0.55)], tread)
        cv.poly([(xl, y - (y - y2) * 0.55), (xr, y - (y - y2) * 0.55), (xr, y2), (xl, y2)], mix((4, 4, 12), tread, 0.5))
        cv.rect(xl, y - 6, xr, y, (150, 120, 50, int(120 * shade)))   # step nosing (yellow)
    # left wall + handrail
    cv.poly([(0, 0), (380, 200), (380, 600), (0, H)], (12, 14, 38))
    cv.line([(40, 1900), (370, 600)], (200, 160, 70), 16)
    cv.glow_poly([(40, 1900), (370, 600), (380, 610), (50, 1910)], AMBER, 40)
    # right wall (lit by glow from below) — where the shadow appears
    wall = [(900, 120), (W, 40), (W, H), (900, 1500)]
    cv.poly(wall, (40, 34, 52))
    cv.poly(wall, AMBER + (int(26 * glow_amt),))
    cv.glow_poly(wall, AMBER, int(50 * glow_amt))
    # ceiling
    cv.poly([(0, 0), (W, 0), (W, 40), (900, 120), (380, 200)], (8, 9, 24))
    if shadow is not None:
        rise = shadow   # 0..1
        base_y = 2300 - 1250 * rise
        sc = 1.6 + 0.8 * rise
        sx = 880
        sh = (6, 4, 10, 235)
        cv.ell(sx, base_y - 520 * sc, 50 * sc, 78 * sc, sh)
        cv.poly([(sx - 70 * sc, base_y - 420 * sc), (sx + 70 * sc, base_y - 420 * sc),
                 (sx + 40 * sc, base_y + 200), (sx - 40 * sc, base_y + 200)], sh)
        cv.line([(sx - 60 * sc, base_y - 400 * sc), (sx - 90 * sc, base_y)], sh, 22 * sc)
        cv.line([(sx + 60 * sc, base_y - 400 * sc), (sx + 85 * sc, base_y)], sh, 22 * sc)


def shelter_scene(cv, t, wave=True, flick=1.0, mum=True):
    cv.im.paste(gradient(W, 1300, (5, 7, 24), (28, 26, 74), "shsky"), (0, 0))
    stars(cv, (0, 0, W, 600), seed=21)
    moon(cv, 230, 300, 60)
    paste_strip(cv, skyline_strip("sky_sh", 2400, 200, 560, 70, 180, (15, 17, 48), (100, 74, 46), 600, 3, 0.07), 300, 700, 2400)
    # pavement
    cv.rect(0, 1300, W, 1330, (40, 42, 86))
    cv.rect(0, 1330, W, H, (20, 22, 52))
    for k in range(6):
        cv.rect(0, 1420 + k * 90 + k * k * 6, W, 1424 + k * 90 + k * k * 6, (28, 30, 66))
    lx, ly = 930, 430                      # lamp head
    # light pool on ground
    cv.ell(560, 1500, 520, 150, AMBER + (int(46 * flick),))
    cv.glow_ell(560, 1480, 480, 170, AMBER, int(90 * flick))
    # shadows from the shelter posts and bench (lamp at right -> shadows fall left)
    sh = (6, 7, 20, 190)
    for px in (200, 740):
        cv.poly([(px, 1330), (px + 16, 1330), (px + 16 - 420, 1700), (px - 440, 1700)], sh)
    cv.poly([(310, 1250), (640, 1250), (420, 1520), (60, 1520)], (6, 7, 20, 150))
    # shelter
    cv.rect(160, 760, 800, 800, (32, 36, 84))
    cv.rect(190, 800, 206, 1330, (32, 36, 84))
    cv.rect(734, 800, 750, 1330, (32, 36, 84))
    cv.rect(206, 820, 734, 1240, (90, 110, 200, 34))
    cv.rect(220, 830, 400, 1000, (12, 14, 38))           # timetable panel
    for i in range(6):
        cv.rect(236, 850 + i * 24, 380 - (i % 3) * 30, 860 + i * 24, (60, 64, 120))
    cv.text((310, 960), "N13", "inter", 22, (130, 134, 190))
    cv.rect(300, 1240, 650, 1258, (36, 40, 94))
    cv.rect(316, 1258, 326, 1330, (36, 40, 94))
    cv.rect(624, 1258, 634, 1330, (36, 40, 94))
    # shelter light strip (warm)
    cv.rect(220, 800, 720, 812, mix((60, 40, 20), AMBER, flick))
    cv.glow_rect(220, 790, 720, 840, AMBER, int(200 * flick))
    cv.poly([(220, 812), (720, 812), (780, 1330), (180, 1330)], AMBER + (int(36 * flick),))
    # lamp post
    cv.rect(970, 400, 986, 1330, (24, 26, 60))
    cv.rect(900, 400, 986, 414, (24, 26, 60))
    cv.ell(lx - 20, ly + 10, 40, 14, mix((60, 40, 20), (255, 214, 140), flick))
    cv.glow(lx - 20, ly + 20, 170, AMBER, int(170 * flick))
    cv.poly([(lx - 60, ly + 18), (lx + 20, ly + 18), (1040, 1330), (420, 1330)], AMBER + (int(22 * flick),))
    # bus-stop flag pole (casts a long shadow across the pavement)
    cv.poly([(854, 1336), (868, 1336), (640, 1760), (610, 1760)], (6, 7, 20, 200))
    cv.rect(854, 640, 866, 1336, (40, 44, 96))
    cv.circ(860, 640, 46, (232, 36, 46))
    cv.circ(860, 640, 32, (246, 246, 250))
    cv.text((860, 641), "13", "interx", 30, (20, 22, 60))
    if mum:
        stick_figure(cv, 560, 950, sit=False, wave=(t * 7.0 if wave else None), color=WHITE, lw=14, bun=True)
        cv.glow(560, 1100, 220, AMBER, int(50 * flick))
    rain(cv, t, (0, 0, W, H), alpha=55, n=220)
    # puddle reflection of lamp
    cv.ell(800, 1600, 120, 16, AMBER + (int(50 * flick),))


def doors_scene(cv, t, open_u):
    cv.rect(0, 0, W, H, (14, 16, 44))
    # outside through doors
    cv.rect(240, 420, 840, 1620, (30, 22, 20))
    cv.glow(540, 760, 300, AMBER, 120)
    cv.ell(540, 640, 60, 20, (255, 214, 140))
    cv.rect(240, 1300, 840, 1620, (36, 34, 60))
    cv.rect(400, 700, 412, 1300, (24, 26, 60))   # far shelter post silhouettes
    cv.rect(680, 700, 692, 1300, (24, 26, 60))
    cv.rect(380, 690, 720, 708, (24, 26, 60))
    rain(cv, t, (240, 420, 840, 1620), alpha=80, n=120)
    # door panels sliding
    off = 290 * ease(open_u)
    for sgn, base in ((-1, 240), (1, 540)):
        x0 = base + sgn * off
        x0c = x0 if sgn < 0 else x0
        cv.rect(x0c, 420, x0c + 300, 1620, (40, 46, 110))
        cv.rrect(x0c + 34, 470, x0c + 266, 1180, 16, (8, 10, 30, 230))
        cv.rect(x0c + 34, 1240, x0c + 266, 1260, (26, 30, 76))
        edge = x0c + 300 if sgn < 0 else x0c
        cv.rect(edge - 8, 420, edge + 8, 1620, (20, 22, 54))
    # frame
    cv.rect(0, 0, W, 420, (12, 14, 38))
    cv.rect(0, 1620, W, H, (10, 11, 30))
    cv.rect(0, 0, 240, H, (16, 19, 50))
    cv.rect(840, 0, W, H, (16, 19, 50))
    # yellow poles
    for px in (205, 875):
        cv.rect(px - 10, 300, px + 10, 1800, (200, 160, 70))
        cv.glow_rect(px - 14, 300, px + 14, 1800, AMBER, 40)
    cv.ell(540, 380, 36, 20, AMBER if open_u > 0 else (90, 60, 30))     # stop-request light
    cv.glow(540, 380, 90, AMBER, 160 if open_u > 0 else 40)


# ---------------------------------------------------------------- overlay text helpers (screen space, 1x)
def draw_text_center(d, xy, txt, font, size, fill, stroke=0, stroke_fill=(0, 0, 0), anchor="mm"):
    d.text(xy, txt, font=F(font, size), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=stroke_fill)


def spaced(d, xy, txt, font, size, fill, spacing, anchor_v="m"):
    f = F(font, size)
    widths = [f.getlength(ch) for ch in txt]
    tot = sum(widths) + spacing * (len(txt) - 1)
    x = xy[0] - tot / 2
    for ch, wd in zip(txt, widths):
        d.text((x, xy[1]), ch, font=f, fill=fill, anchor="l" + anchor_v)
        x += wd + spacing


EMOJI_CACHE = {}


def emoji(ch, size):
    k = (ch, size)
    if k not in EMOJI_CACHE:
        f = ImageFont.truetype(FONTS["emoji"], 109)
        im = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((70, 70), ch, font=f, embedded_color=True, anchor="mm")
        im = im.crop(im.getbbox())
        sc = size / im.height
        EMOJI_CACHE[k] = im.resize((max(1, int(im.width * sc)), size), Image.LANCZOS)
    return EMOJI_CACHE[k]


# ---------------------------------------------------------------- captions
VO = json.load(open(f"{SCR}/vo/vo.json"))


def parse_chunk(ch):
    out, cur = [], None
    for w in ch.split():
        if cur is None and w[0] in "*_":
            cur = LIME if w[0] == "*" else BLUE
        col = cur or WHITE
        core = w.rstrip(".,?…!")
        if cur is not None and len(core) > 1 and core[-1] in "*_":
            cur = None
        out.append((w.replace("*", "").replace("_", ""), col))
    return out


CAPS = []   # (t0, t1, words)
for i, ln in enumerate(VO):
    if not ln["cap"]:
        continue
    chunks = ln["cap"].split("|")
    wts = [max(3, len(c.replace("*", "").replace("_", ""))) for c in chunks]
    tot = sum(wts)
    nxt = VO[i + 1]["start"] if i + 1 < len(VO) else 999
    t = ln["start"]
    for c, w in zip(chunks, wts):
        d = ln["dur"] * w / tot
        CAPS.append([t, t + d, parse_chunk(c)])
        t += d
    CAPS[-1][1] = min(t + 0.45, nxt - 0.02)


def draw_captions(img, t, y=1340, size=112):
    d = ImageDraw.Draw(img)
    for t0, t1, words in CAPS:
        if t0 <= t < t1:
            p = eout((t - t0) / 0.14)
            sz = int(size * (1.14 - 0.14 * p))
            f = F("anton", sz)
            sp = f.getlength(" ")
            widths = [f.getlength(w) for w, _ in words]
            tot = sum(widths) + sp * (len(words) - 1)
            if tot > 980:
                sz = int(sz * 980 / tot)
                f = F("anton", sz)
                sp = f.getlength(" ")
                widths = [f.getlength(w) for w, _ in words]
                tot = sum(widths) + sp * (len(words) - 1)
            x = W / 2 - tot / 2
            for (w, col), wd in zip(words, widths):
                d.text((x + 5, y + 7), w, font=f, fill=(0, 0, 0), anchor="lm")
                d.text((x, y), w, font=f, fill=col, anchor="lm", stroke_width=7, stroke_fill=(5, 5, 14))
                x += wd + sp
            break


# ---------------------------------------------------------------- HUD
def clock_str(t):
    if t < 41.8:
        return "2:14 AM"
    if t < 42.7:
        k = int((t - 41.8) * 20)
        return f"2:{14 + k:02d} AM" if 14 + k < 31 else "2:31 AM"
    if t < 64.0:
        return "2:31 AM"
    if t < 78.4:
        return "2:32 AM"
    if t < 85.2:
        return "2:33 AM"
    return "2:34 AM"


def draw_hud(img, t):
    d = ImageDraw.Draw(img, "RGBA")
    pulse = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 4))
    d.ellipse([60, 101, 82, 123], fill=(232, 36, 46, int(255 * pulse)))
    d.text((96, 112), "NIGHT 1", font=F("interx", 34), fill=WHITE, anchor="lm")
    cs = clock_str(t)
    glitch = 41.8 <= t < 42.7
    f = F("mono", 92)
    if glitch:
        d.text((60 + 5, 140), cs, font=f, fill=(232, 36, 46, 200), anchor="lt")
        d.text((60 - 4, 140), cs, font=f, fill=(126, 204, 255, 160), anchor="lt")
    d.text((60 + 3, 143), cs, font=f, fill=(0, 0, 0, 140), anchor="lt")
    d.text((60, 140), cs, font=f, fill=WHITE, anchor="lt")
    x = 63
    for ch in "ROUTE 13":
        d.text((x, 262), ch, font=F("inters", 24), fill=(170, 174, 210), anchor="lm")
        x += F("inters", 24).getlength(ch) + 5


# ---------------------------------------------------------------- rule cards
RULES = {
    1: (22.4, 25.8, "DON'T LOOK OUT THE BACK WINDOW."),
    2: (30.2, 33.8, "IF SOMEONE SITS NEXT TO YOU, DON'T SPEAK."),
    3: (38.2, 41.7, "ONLY GET OFF WHEN THE SIGN SAYS YOUR NAME."),
}


def wrap(txt, font, maxw):
    lines, cur = [], ""
    for w in txt.split():
        tst = (cur + " " + w).strip()
        if font.getlength(tst) <= maxw:
            cur = tst
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def draw_rule(img, t, n):
    t0, t1, txt = RULES[n]
    lt = t - t0
    ov = Image.new("RGBA", (W, H), (4, 5, 16, 165))
    img.paste(Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"))
    d = ImageDraw.Draw(img, "RGBA")
    # pill
    p = eout(lt / 0.22)
    lab = f"RULE #{n}"
    f = F("interx", 46)
    tw = f.getlength(lab)
    pw, ph = (tw + 70) * (0.6 + 0.4 * p), 82 * (0.6 + 0.4 * p)
    cy = 650
    d.rounded_rectangle([W / 2 - pw / 2, cy - ph / 2, W / 2 + pw / 2, cy + ph / 2], radius=ph / 2, fill=(232, 36, 46, int(255 * p)))
    if p > 0.5:
        d.text((W / 2, cy + 2), lab, font=F("interx", int(46 * (0.6 + 0.4 * p))), fill=WHITE, anchor="mm")
    fb = F("anton", 150)
    lines = wrap(txt, fb, 960)
    for i, ln in enumerate(lines):
        q = eout((lt - 0.15 - i * 0.13) / 0.3)
        if q <= 0:
            continue
        y = 790 + i * 168 + 40 * (1 - q)
        d.text((W / 2 + 6, y + 8), ln, font=fb, fill=(0, 0, 0, int(200 * q)), anchor="mt")
        d.text((W / 2, y), ln, font=fb, fill=(246, 246, 250, int(255 * q)), anchor="mt")


# ---------------------------------------------------------------- post effects
def make_vignette():
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.6)) ** 2)
    a = np.clip((r - 0.55) / 0.6, 0, 1) ** 1.4 * 215
    arr = np.zeros((H, W, 4), np.uint8)
    arr[..., 3] = a.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


VIG = None
GRAIN = []


def post(img, t):
    global VIG
    if VIG is None:
        VIG = make_vignette()
        rng = np.random.default_rng(0)
        for k in range(4):
            n = rng.integers(0, 255, (H // 2, W // 2), dtype=np.uint8)
            a = np.zeros((H // 2, W // 2, 4), np.uint8)
            a[..., 0] = a[..., 1] = a[..., 2] = n
            a[..., 3] = 9
            GRAIN.append(Image.fromarray(a, "RGBA").resize((W, H), Image.NEAREST))
    im = img.convert("RGBA")
    im = Image.alpha_composite(im, VIG)
    im = Image.alpha_composite(im, GRAIN[int(t * FPS) % 4])
    return im.convert("RGB")


def chroma(img, amt):
    r, g, b = img.split()
    r = ImageChops.offset(r, amt, 0)
    b = ImageChops.offset(b, -amt, 0)
    return Image.merge("RGB", (r, g, b))


def flash(img, a, col=(255, 255, 255)):
    if a <= 0:
        return img
    return Image.blend(img, Image.new("RGB", (W, H), col), clamp(a))


# ---------------------------------------------------------------- timeline
def led_front_layers(t):
    if t < 9.7:
        return [("13 CITY CENTRE", AMBER, "c", 1)], 1.0
    fl = flicker(t, 9.7, 10.8, 3)
    if t < 10.3:
        return [("13 CITY CENTRE", AMBER, "c", 1)], fl
    return [("DON'T GET OFF", RED, "c", 1)], fl


def led_warning(t):
    # 10.8 -> 16.2 : glitch, then scrolling two-line warning
    fl = flicker(t, 10.8, 11.3, 5)
    if t < 11.3:
        return [("13 CITY CENTRE", AMBER, "c", 5)], fl
    l1 = scroll_in_hold("DON'T GET OFF", RED, 11.3, t, 48, 1)
    l2 = scroll_in_hold("AT YOUR STOP.", RED, 12.4, t, 48, 9)
    fl2 = 1.0 if t < 15.6 else flicker(t, 15.6, 16.2, 7)
    return [l1, l2], fl2


DRIVER_PAGES = [(16.2, ["I'M THE", "DRIVER."], AMBER), (17.2, ["I CAN'T", "TALK."], AMBER),
                (18.2, ["READ", "CAREFULLY."], AMBER), (19.2, ["3 RULES."], RED)]


def led_driver(t):
    cur = None
    for i, (t0, lines, col) in enumerate(DRIVER_PAGES):
        if t >= t0:
            cur = i
    t0, lines, col = DRIVER_PAGES[cur]
    up = int((1 - eout((t - t0) / 0.18)) * 9)     # scroll up from below
    if len(lines) == 1:
        return [(lines[0], col, "c", 5 + up)], 1.0
    return [(lines[0], col, "c", 1 + up), (lines[1], col, "c", 9 + up)], 1.0


def led_name(t):
    fl = flicker(t, 70.2, 71.0, 9)
    if t < 70.6:
        return [("2:32", AMBER, "c", 5)], fl
    if int((t - 70.6) / 1.1) % 2 == 0:
        return [("YOUR", LIME, "c", 1), ("NAME", LIME, "c", 9)], fl
    return [("GET OFF", LIME, "c", 1), ("NOW.", LIME, "c", 9)], fl


def frame(t):
    """returns final RGB image for global time t"""
    cv = Cv()
    cam = (540, 960, 1.0)
    extra = []   # callables(img) drawn in screen space after camera
    fl_a, chrom = 0.0, 0
    shake = 0.0

    def cut_flash(t0, d=0.16, a=0.6):
        return a * (1 - (t - t0) / d) if t0 <= t < t0 + d else 0.0

    if t < 3.4:
        cam = shot_ext_bus(cv, t, t, z0=1.0, z1=1.1, cyc=1020, dur=3.4)
    elif t < 8.2:
        lt = t - 3.4
        cam = shot_row(cv, t, lt, z0=1.0, z1=1.16, c0=(540, 960), c1=(470, 930), dur=4.8)
    elif t < 10.8:
        cam = shot_front(cv, t, t - 8.2, led_front_layers, dur=2.6, z0=1.0, z1=1.35)
        if 9.7 <= t < 10.8:
            chrom = int(8 * (1 - led_front_layers(t)[1]) + 2)
        fl_a = cut_flash(8.2, a=0.4)
    elif t < 16.2:
        layers, fl = led_warning(t)
        led_close_scene(cv, t, layers, fl)
        u = ease(prog(t, 10.8, 16.2))
        cam = (540, 900, lerp(1.0, 1.08, u))
        if fl < 1:
            chrom = 6
        fl_a = cut_flash(10.8, a=0.5)
    elif t < 20.2:
        layers, fl = led_driver(t)
        led_close_scene(cv, t, layers, fl)
        u = ease(prog(t, 16.2, 20.2))
        cam = (540, 890, lerp(1.04, 1.12, u))
        if 19.2 <= t < 19.4:
            chrom = 7
    elif t < 22.4:
        stair_scene(cv, t)
        u = ease(prog(t, 20.2, 22.4))
        cam = (600, lerp(960, 900, u), lerp(1.0, 1.18, u))
        fl_a = cut_flash(20.2, a=0.3)
    elif t < 25.8:
        row_scene(cv, t, dim=0.9)
        cam = (540, 960, lerp(1.1, 1.2, prog(t, 22.4, 25.8)))
        extra.append(lambda im: draw_rule(im, t, 1))
        fl_a = cut_flash(22.4, a=0.7)
    elif t < 30.2:
        lt = t - 25.8
        # head starts to turn, then stops (and snaps back on "don't look")
        if t < 28.6:
            look = 0.75 * ease(prog(t, 26.4, 28.2))
        else:
            look = 0.75 * (1 - ease(prog(t, 28.6, 28.9)))
        hp = ease(prog(t, 27.3, 28.4)) * (1 - prog(t, 29.6, 30.2))
        row_scene(cv, t, figure_eyes=True, look=look, handprint=hp)
        z = lerp(2.3, 2.75, ease(prog(t, 25.8, 30.2)))
        cam = (lerp(380, 420, ease(prog(t, 25.8, 30.2))), 820, z)
        if 26.9 <= t < 27.05 or 27.4 <= t < 27.55:
            shake = 6
    elif t < 33.8:
        row_scene(cv, t, dim=0.9, fig=True)
        cam = (540, 960, lerp(1.1, 1.2, prog(t, 30.2, 33.8)))
        extra.append(lambda im: draw_rule(im, t, 2))
        fl_a = cut_flash(30.2, a=0.7)
    elif t < 38.2:
        ph = (t - 33.8) % 2.2
        sweep = math.sin(clamp(ph / 1.2) * math.pi) ** 2 if ph < 1.2 else 0
        sweep = max(sweep, 0.35)
        row_scene(cv, t, sweep=sweep, figure_eyes=t > 36.0, look=0.5 * ease(prog(t, 36.0, 37.0)))
        u = ease(prog(t, 33.8, 38.2))
        cam = (lerp(640, 690, u), lerp(1020, 1060, u), lerp(1.45, 1.75, u))
    elif t < 41.7:
        row_scene(cv, t, dim=0.9, sweep=0.3)
        cam = (540, 960, lerp(1.1, 1.2, prog(t, 38.2, 41.7)))
        extra.append(lambda im: draw_rule(im, t, 3))
        fl_a = cut_flash(38.2, a=0.7)
    elif t < 43.9:
        # big clock glitch
        cv.rect(0, 0, W, H, (6, 7, 20))
        cam = (540, 960, 1.0)

        def big_clock(im, t=t):
            d = ImageDraw.Draw(im, "RGBA")
            cs = clock_str(t).replace(" AM", "")
            z = 1.0 + 0.06 * ease(prog(t, 41.7, 43.9))
            f = F("mono", int(260 * z))
            if t < 42.8:
                d.text((540 + 14, 900), cs, font=f, fill=(232, 36, 46, 200), anchor="mm")
                d.text((540 - 12, 900), cs, font=f, fill=(126, 204, 255, 150), anchor="mm")
            col = WHITE if t < 42.7 else (246, 246, 250)
            d.text((540, 900), cs, font=f, fill=col, anchor="mm")
            d.text((540, 1080), "AM", font=F("mono", 80), fill=(170, 174, 210), anchor="mm")
            if t >= 42.7:
                a = int(255 * eout((t - 42.7) / 0.3))
                d.text((540, 700), "17 MINUTES GONE", font=F("inters", 34), fill=(232, 36, 46, a), anchor="mm")
        extra.append(big_clock)
        fl_a = cut_flash(41.7, a=0.6) + cut_flash(42.7, a=0.4)
        if t < 42.7:
            chrom = 5
    elif t < 46.2:
        row_scene(cv, t, figure_eyes=True, look=0.6 * math.sin((t - 43.9) * 2.2))
        u = ease(prog(t, 43.9, 46.2))
        cam = (lerp(420, 450, u), lerp(900, 920, u), lerp(1.35, 1.5, u))
    elif t < 49.6:
        cam = shot_ext_bus(cv, t, t - 46.2, bx=-430, stop_at=(46.2, 47.6), z0=1.0, z1=1.08, cyc=1060, dur=3.4, shelter=True)
        fl_a = cut_flash(46.2, a=0.3)
    elif t < 52.4:
        # footsteps: shadow rises in steps
        steps = [49.9, 50.5, 51.1, 51.7, 52.2]
        k = sum(1 for s in steps if t >= s)
        frac = 0
        for s in steps:
            if s <= t < s + 0.25:
                frac = eout((t - s) / 0.25)
        rise = (max(0, k - 1) + frac) / len(steps) if k else 0
        stair_scene(cv, t, shadow=0.1 + rise * 0.9, glow_amt=1.0 - 0.3 * rise)
        u = ease(prog(t, 49.6, 52.4))
        cam = (760, lerp(1000, 900, u), lerp(1.1, 1.22, u))
        if any(s <= t < s + 0.08 for s in steps):
            shake = 4
    elif t < 55.0:
        row_scene(cv, t, figure_eyes=True, look=0.0, creature_on=True, c_turn=0.0)
        u = ease(prog(t, 52.4, 55.0))
        cam = (lerp(540, 560, u), lerp(900, 880, u), lerp(1.12, 1.24, u))
        fl_a = cut_flash(52.4, d=0.2, a=0.85)
        if t < 52.6:
            shake = 8
    elif t < 57.6:
        turn = ease(prog(t, 55.3, 57.4))
        row_scene(cv, t, figure_eyes=True, look=0.15, creature_on=True, c_turn=turn)
        u = ease(prog(t, 55.0, 57.6))
        cam = (lerp(600, 680, u), lerp(760, 640, u), lerp(1.8, 2.5, u))
    elif t < 58.4:
        led_close_scene(cv, t, [("STOPPING", AMBER, "c", 5)], 1.0)
        cam = (540, 890, 1.1 + 0.4 * eout(prog(t, 57.6, 57.8)))
        fl_a = cut_flash(57.6, a=0.8)
        shake = 6 if t < 57.75 else 0
    elif t < 60.8:
        doors_scene(cv, t, prog(t, 58.6, 59.8))
        cam = (540, 1000, lerp(1.0, 1.12, ease(prog(t, 58.4, 60.8))))
    elif t < 70.2:
        shelter_scene(cv, t)
        u = ease(prog(t, 60.8, 70.2))
        cam = (lerp(540, 560, u), lerp(1000, 1060, u), lerp(1.0, 1.22, u))
        fl_a = cut_flash(60.8, a=0.25)

        def mum_label(im, t=t, cam=cam):
            a = eout(prog(t, 61.6, 62.2))
            if a <= 0:
                return
            d = ImageDraw.Draw(im, "RGBA")
            x, y = to_screen(cam, 540, 700)
            d.rounded_rectangle([x - 300, y - 30, x + 300, y + 30], radius=30, fill=(5, 6, 18, int(170 * a)))
            spaced(d, (x, y), "— YOUR MUM · AT THE STOP —", "interx", 28, ORANGE + (int(255 * a),), 3)
        extra.append(mum_label)
    elif t < 73.8:
        layers, fl = led_name(t)
        led_close_scene(cv, t, layers, fl)
        cam = (540, 890, lerp(1.05, 1.18, ease(prog(t, 70.2, 73.8))))
        if fl < 1:
            chrom = 7
        fl_a = cut_flash(70.2, a=0.5)
    elif t < 75.8:
        row_scene(cv, t, figure_eyes=True, look=0.6, creature_on=True, c_turn=1.0)
        u = ease(prog(t, 73.8, 75.8))
        cam = (lerp(640, 660, u), lerp(660, 640, u), lerp(2.3, 2.6, u))

        def whisper(im, t=t):
            a = eout(prog(t, 74.3, 74.6)) * (1 - prog(t, 75.5, 75.8))
            if a <= 0:
                return
            d = ImageDraw.Draw(im, "RGBA")
            txt = "THAT'S NOT THE SIGN."
            n = int(len(txt) * clamp((t - 74.35) / 0.9))
            d.text((540, 1150), txt[:n], font=F("vt", 64), fill=(255, 184, 74, int(235 * a)), anchor="mm")
        extra.append(whisper)
    elif t < 78.4:
        fl_ = 0.35 + 0.65 * (hrand(int(t * 10), 55) > 0.25)
        shelter_scene(cv, t, wave=True, flick=fl_)
        u = ease(prog(t, 75.8, 78.4))
        cam = (lerp(600, 590, u), lerp(1440, 1480, u), lerp(1.45, 1.7, u))
        fl_a = cut_flash(75.8, d=0.12, a=0.9)

        def noshadow(im, t=t, cam=cam):
            a = eout(prog(t, 76.6, 77.0))
            if a <= 0:
                return
            d = ImageDraw.Draw(im, "RGBA")
            x, y = to_screen(cam, 560, 1560)
            spaced(d, (x, y + 95), "NO SHADOW", "interx", 32, (232, 36, 46, int(255 * a)), 8)
            x0, y0 = to_screen(cam, 470, 1520)
            x1, y1 = to_screen(cam, 650, 1600)
            d.rounded_rectangle([x0, y0, x1, y1], radius=20, outline=(232, 36, 46, int(220 * a)), width=4)
        extra.append(noshadow)
    elif t < 85.2:
        return choice_frame(t)
    else:
        return outro_frame(t)

    img = camera(cv, *cam)
    if shake:
        dx = int((hrand(int(t * 60), 3) - 0.5) * 2 * shake)
        dy = int((hrand(int(t * 60), 4) - 0.5) * 2 * shake)
        img = ImageChops.offset(img, dx, dy)
    if chrom:
        img = chroma(img, chrom)
    for fn in extra:
        fn(img)
    img = post(img, t)
    draw_hud(img, t)
    draw_captions(img, t, y=1730 if 75.8 <= t < 78.4 else 1340)
    img = flash(img, fl_a)
    return img


def choice_frame(t):
    lt = t - 78.4
    # left: sign
    cv = Cv()
    cv.rect(0, 0, W, H, (12, 14, 40))
    cv.rrect(290, 590, 790, 970, 26, (6, 6, 12), outline=(46, 50, 110), w=6)
    cv.text((540, 625), "· NEXT STOP ·", "inters", 20, (80, 84, 140), spacing=5)
    fl = 1.0 if hrand(int(t * 8), 13) > 0.12 else 0.4
    draw_led(cv, 540 - 27 * 17 / 2, 650, 27, 17, 17, [("YOUR", LIME, "c", 1), ("NAME", LIME, "c", 9)], flick=fl)
    left = camera(cv, 540, 780, 1.0 + 0.05 * ease(prog(t, 78.4, 85.2)))
    # right: mum
    cv2 = Cv()
    shelter_scene(cv2, t, wave=True)
    right = camera(cv2, 560, 1120, 1.25 + 0.05 * ease(prog(t, 78.4, 85.2)))
    img = Image.new("RGB", (W, H))
    img.paste(left.crop((270, 0, 810, H)), (0, 0))
    img.paste(right.crop((270, 0, 810, H)), (540, 0))
    sl = eout(prog(t, 78.4, 78.8))
    if sl < 1:   # slide in
        img = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), img, sl)
    img = post(img, t)
    d = ImageDraw.Draw(img, "RGBA")
    # bottom panel gradient
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(1080, H, 6):
        gd.rectangle([0, y, W, y + 6], fill=(4, 5, 16, int(clamp((y - 1080) / 260) * 235)))
    img.paste(Image.alpha_composite(img.convert("RGBA"), grad).convert("RGB"))
    d = ImageDraw.Draw(img, "RGBA")
    # divider
    jit = int((hrand(int(t * 20), 4) - 0.5) * 6)
    d.rectangle([538 + jit, 0, 542 + jit, 1180], fill=(232, 36, 46, 230))
    # tiny labels
    spaced(d, (270, 1060), "THE SIGN", "interx", 26, (126, 204, 255), 6)
    spaced(d, (810, 1060), "YOUR MUM", "interx", 26, ORANGE, 6)
    # title
    q = eout(prog(t, 78.7, 79.1))
    ft = F("anton", int(168 * (1.15 - 0.15 * q)))
    if q > 0:
        d.text((546, 1278), "SIGN OR MUM?", font=ft, fill=(0, 0, 0, int(200 * q)), anchor="mm")
        d.text((540, 1270), "SIGN OR MUM?", font=ft, fill=(246, 246, 250, int(255 * q)), anchor="mm")
    # buttons
    for i, (lab, em, col, cx, tt) in enumerate([("SIGN", "🚌", (64, 150, 255), 300, 79.2), ("MUM", "🏠", ORANGE, 780, 79.45)]):
        p = eout(prog(t, tt, tt + 0.25))
        if p <= 0:
            continue
        pulse = 1 + 0.03 * math.sin((t - tt) * 5 + i * 2)
        bw, bh = 400 * p * pulse, 128 * p * pulse
        cy = 1460
        d.rounded_rectangle([cx - bw / 2, cy - bh / 2 + 8, cx + bw / 2, cy + bh / 2 + 8], radius=bh / 2, fill=(0, 0, 0, 120))
        d.rounded_rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], radius=bh / 2, fill=col)
        if p > 0.8:
            fnt = F("interx", 58)
            e = emoji(em, 62)
            tw = fnt.getlength(lab)
            total = e.width + 18 + tw
            x0 = int(cx - total / 2)
            img.paste(e, (x0, int(cy - e.height / 2)), e)
            d.text((x0 + e.width + 18, cy + 2), lab, font=fnt, fill=WHITE, anchor="lm")
    draw_hud(img, t)
    draw_captions(img, t, y=1690, size=84)
    if t < 78.55:
        img = flash(img, 0.7 * (1 - (t - 78.4) / 0.15))
    return img


def outro_frame(t):
    lt = t - 85.2
    img = Image.new("RGB", (W, H), (5, 5, 14))
    dim = eout(lt / 0.6)
    gl = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(gl)
    q = eout(prog(t, 85.5, 86.1))
    flick = 1.0 if hrand(int(t * 15), 19) > 0.08 else 0.5
    a = q * flick
    gd.text((540, 930), "NIGHT 2", font=F("anton", 270), fill=(int(232 * a), int(30 * a), int(40 * a)), anchor="mm")
    gl = gl.filter(ImageFilter.GaussianBlur(28))
    img = ImageChops.add(img, gl)
    img = ImageChops.add(img, gl)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((540, 930), "NIGHT 2", font=F("anton", 270), fill=(255, 60, 66, int(255 * a)), anchor="mm")
    q2 = eout(prog(t, 85.3, 85.8))
    spaced(d, (540, 700), "ROUTE 13", "inters", 34, (200, 204, 230, int(255 * q2)), 22)
    q3 = eout(prog(t, 86.0, 86.5))
    d.text((540, 1150), "2:34 AM", font=F("mono", 70), fill=(220, 222, 240, int(255 * q3)), anchor="mm")
    q4 = eout(prog(t, 86.6, 87.0))
    if q4 > 0:
        pulse = 1 + 0.025 * math.sin((t - 86.6) * 4)
        bw, bh = 620 * pulse, 120 * pulse
        cy = 1400
        d.rounded_rectangle([540 - bw / 2, cy - bh / 2, 540 + bw / 2, cy + bh / 2], radius=bh / 2,
                            outline=(246, 246, 250, int(255 * q4)), width=5)
        spaced(d, (540, cy + 2), "FOLLOW FOR NIGHT 2", "interx", 44, (246, 246, 250, int(255 * q4)), 3)
    img = post(img, t)
    draw_hud(img, t)
    if lt < 0.6:
        img = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), img, dim)
    if t > 89.4:
        img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), clamp((t - 89.4) / 0.6))
    return img


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    if sys.argv[1] == "--still":
        frame(float(sys.argv[2])).save(sys.argv[3])
        sys.exit()
    a, b, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                          "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for fi in range(a, b):
        p.stdin.write(frame(fi / FPS).tobytes())
    p.stdin.close()
    p.wait()
