"""THE AGENCY Part 2 — frame renderer (Pillow, flat 2D), to the creator's own script.
Kayla is drawn as the house girl character (white stick figure, red hoodie, black joggers, long dark hair).

usage: python render.py <start_frame> <end_frame> <out.mp4>  |  python render.py --still <t> <out.png>"""
import importlib.util, json, math, os, subprocess, sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
am = _load("am", os.path.join(HERE, "..", "2am-delivery", "render.py"))       # shared toolkit (captions, cards, bubbles)
ml = _load("ml", os.path.join(HERE, "..", "man-by-the-lift", "render.py"))    # the girl character
m35, lb = am.m35, am.lb
Cv, camera, F, post = lb.Cv, lb.camera, lb.F, lb.post
clamp, lerp, ease, eout, prog, hrand = lb.clamp, lb.lerp, lb.ease, lb.eout, lb.prog, lb.hrand
W, H, FPS, SS = lb.W, lb.H, lb.FPS, lb.SS
BG, CARD, WHITE, GREY, RED, BLUE, AMBER, GREEN, PAPER, INK = am.BG, am.CARD, am.WHITE, am.GREY, am.RED, am.BLUE, am.AMBER, am.GREEN, am.PAPER, am.INK
card, slide, bubble, bg = am.card, am.slide, am.bubble, am.bg

TL = json.load(open(os.path.join(HERE, "timeline.json")))
LINES = TL["lines"]; DUR = TL["duration"]
am.LINES = LINES                     # captions + chunk timing read this
chunk_t = am.chunk_t
SUIT = (24, 26, 40); ELISE = (70, 40, 58)


def girl(cv, x, fy, s=1.0, look=0.0, bump=0.0, eyes=True, back=False, arms_up=0.0):
    ml.girl(cv, x, fy, s=s, eyes=eyes, look=look, back=back, arms_up=arms_up)
    if bump > 0 and not back:        # pregnancy bump over the hoodie
        hip = fy - 300 * s
        cv.ell(x + 8 * s, hip - 90 * s, 70 * s * bump, 62 * s * bump, m35.lb.HOODIE)
        cv.ell(x + 8 * s, hip - 90 * s, 70 * s * bump, 62 * s * bump, None, outline=m35.lb.HOODIE_D, w=4 * s)


def victor(cv, x, fy, s=1.0):
    m35.suit_man(cv, x, fy, s=s, shades=False, color=SUIT)


def elise(cv, x, fy, s=1.0):
    m35.suit_man(cv, x, fy, s=s, shades=False, color=ELISE, rim=(110, 70, 96))
    hy = fy - (310 + 300 + 64) * s
    cv.d.chord([(x - 64 * s) * SS, (hy - 74 * s) * SS, (x + 64 * s) * SS, (hy + 40 * s) * SS], 180, 360, fill=(30, 22, 22))
    cv.circ(x, hy - 76 * s, 28 * s, (30, 22, 22))            # bun


def phone(cv, x0=230, y0=330, w=620, h=1060):
    return m35.phone_frame(cv, x0, y0, w, h)


def toddler(cv, x, fy, s, ph):
    b = abs(math.sin(ph)) * 8 * s
    cv.line([(x - 10 * s, fy - 60 * s - b), (x - 16 * s, fy)], (220, 220, 230), 12 * s)
    cv.line([(x + 10 * s, fy - 60 * s - b), (x + 16 * s, fy)], (220, 220, 230), 12 * s)
    cv.rrect(x - 30 * s, fy - 130 * s - b, x + 30 * s, fy - 55 * s - b, 14 * s, (160, 190, 230))
    cv.circ(x, fy - 160 * s - b, 32 * s, (240, 240, 246))


def crib(cv, x, y, s=1.0, baby=True):
    cv.rect(x - 110 * s, y - 70 * s, x + 110 * s, y - 60 * s, (210, 200, 190))
    cv.rect(x - 110 * s, y + 40 * s, x + 110 * s, y + 50 * s, (210, 200, 190))
    for k in range(9):
        bx = x - 100 * s + k * 25 * s
        cv.rect(bx, y - 60 * s, bx + 5 * s, y + 40 * s, (200, 190, 180))
    for sg in (-1, 1):
        cv.rect(x + sg * 110 * s - 6 * s, y - 90 * s, x + sg * 110 * s + 6 * s, y + 90 * s, (180, 170, 160))
    if baby:
        cv.circ(x, y + 10 * s, 20 * s, (240, 236, 240)); cv.rrect(x - 26 * s, y + 20 * s, x + 26 * s, y + 40 * s, 8 * s, (200, 220, 245))


def police_lights(cv, t, x, y, a=1.0):
    on = int(t * 6) % 2
    cv.glow(x - 60, y, 220, (230, 30, 50) if on else (40, 90, 255), int(170 * a))
    cv.glow(x + 60, y, 220, (40, 90, 255) if on else (230, 30, 50), int(170 * a))


# ---------------------------------------------------------------- scenes
def sc_hook(cv, t, lt, i):
    bg(cv, RED, 40)
    q = eout(prog(lt, 0.2, 0.9))
    cv.text((540, 560 + am.slide(q, 30)), "THE DARK SIDE", "anton", 150, WHITE)
    cv.text((540, 720 + am.slide(q, 30)), "OF SURROGACY", "anton", 150, RED)
    cv.glow_ell(540, 640, 460, 160, RED, int(90 * q))
    girl(cv, 540, 1380, s=0.75, look=0.0, bump=1.0)
    return (540, 960, lerp(1.0, 1.05, prog(lt, 0, 3)))


def sc_broke(cv, t, lt, i):
    bg(cv, AMBER, 30)
    girl(cv, 300, 1380, s=0.85, look=0.8)
    u = prog(lt, 0.3, 0.7); y = 470 + slide(u)
    card(cv, 520, y, 990, y + 220); cv.text((560, y + 60), "BALANCE", "inters", 30, GREY, anchor="lm")
    cv.text((560, y + 145), "$212.40", "mono", 74, RED, anchor="lm")
    for k, (a, b) in enumerate((("RENT DUE", "$1,400"), ("GROCERIES", "$86"))):
        t0 = chunk_t(i, 3) + k * 0.4; u = prog(t, t0, t0 + 0.35)
        if u <= 0: continue
        y = 760 + k * 170 + slide(u)
        card(cv, 520, y, 990, y + 130); cv.text((560, y + 65), a, "interx", 40, WHITE, anchor="lm"); cv.text((950, y + 65), b, "mono", 40, AMBER, anchor="rm")
    return (540, 960, 1.0)


def sc_signup(cv, t, lt, i):
    bg(cv, BLUE, 28)
    sx0, sy0, sx1, sy1 = phone(cv)
    cx = (sx0 + sx1) / 2
    cv.rect(sx0, sy0 + 60, sx1, sy0 + 420, (230, 222, 240))
    cv.circ(cx, sy0 + 190, 70, (180, 150, 210)); cv.circ(cx, sy0 + 170, 26, (250, 246, 252)); cv.ell(cx, sy0 + 220, 40, 28, (250, 246, 252))
    cv.text((cx, sy0 + 320), "Surrogacy", "interx", 58, (70, 40, 110))
    cv.text((cx, sy0 + 380), "Agency", "inters", 30, (120, 100, 140))
    cv.text((cx, sy0 + 500), "Help a family", "interx", 46, WHITE); cv.text((cx, sy0 + 560), "grow.", "interx", 46, WHITE)
    if t >= chunk_t(i, 2):
        q = eout(prog(t, chunk_t(i, 2), chunk_t(i, 2) + 0.3))
        cv.rrect(sx0 + 60, sy0 + 640, sx1 - 60, sy0 + 720, 40, (40, 140, 90)); cv.text((cx, sy0 + 680), "Earn extra money", "interx", 34, WHITE)
    tap = prog(t, chunk_t(i, 3), chunk_t(i, 3) + 0.3)
    cv.rrect(sx0 + 90, sy1 - 200, sx1 - 90, sy1 - 100, 50, (150, 90, 220) if tap < 0.5 else (110, 60, 170))
    cv.text((cx, sy1 - 150), "APPLY" if tap < 1 else "APPLIED", "interx", 44, WHITE)
    return (540, 900, 1.0)


def sc_couple(cv, t, lt, i):
    bg(cv, (200, 120, 220), 26)
    u = prog(lt, 0, 0.4); y0 = 360 + slide(u)
    card(cv, 120, y0, 960, y0 + 980)
    cv.text((540, y0 + 70), "YOUR MATCH", "mono", 32, GREY)
    victor(cv, 420, y0 + 700, 0.55); elise(cv, 660, y0 + 700, 0.55)
    if t >= chunk_t(i, 1):
        cv.text((540, y0 + 790), "Sylvia & Guojun", "interx", 52, WHITE)
    if t >= chunk_t(i, 2):
        cv.rrect(250, y0 + 850, 830, y0 + 920, 20, (70, 40, 58)); cv.text((540, y0 + 885), "Want a second child", "inters", 32, (255, 200, 220))
    return (540, 900, 1.0)


def sc_pregnant(cv, t, lt, i):
    bg(cv, GREEN, 26)
    q = eout(prog(lt, 0.1, 0.6))
    cv.rrect(470, 420, 610, 1000, 60, (240, 240, 246)); cv.rrect(495, 560, 585, 700, 14, (210, 226, 240))
    cv.line([(540, 590), (540, 670)], (220, 40, 80), 12); cv.line([(500, 630), (580, 630)], (220, 40, 80), 12 * q)
    cv.glow(540, 630, 160, (255, 120, 160), int(110 * q))
    if t >= chunk_t(i, 2):
        cv.glow_ell(540, 1150, 500, 300, RED, 60)
        cv.text((540, 1150), "…then the strange part", "interx", 50, RED)
    return (540, 900, lerp(1.0, 1.08, ease(prog(lt, 0, 4))))


def sc_noshow(cv, t, lt, i):
    bg(cv, BLUE, 22)
    cv.rect(0, 1240, W, H, (26, 24, 34))
    for k, x in enumerate((180, 400, 620, 840)):              # waiting-room chairs
        cv.rrect(x - 80, 1080, x + 80, 1180, 16, (60, 64, 90)); cv.rect(x - 70, 1180, x - 60, 1240, (40, 40, 50)); cv.rect(x + 60, 1180, x + 70, 1240, (40, 40, 50))
    girl(cv, 180, 1240, s=0.62, look=0.9, bump=1.1)
    for k, x in enumerate((620, 840)):
        cv.rrect(x - 60, 1110, x + 60, 1150, 8, PAPER); cv.text((x, 1130), "RESERVED", "mono", 18, INK)
    labels = [("12-week scan", chunk_t(i, 0)), ("Anatomy scan", chunk_t(i, 2)), ("Heartbeat", chunk_t(i, 3))]
    for k, (a, t0) in enumerate(labels):
        u = prog(t, t0, t0 + 0.3)
        if u <= 0: continue
        y = 400 + k * 170 + slide(u)
        card(cv, 160, y, 920, y + 130); cv.text((200, y + 65), a, "interx", 40, WHITE, anchor="lm")
        cv.text((880, y + 65), "Hales: absent", "inters", 32, RED, anchor="rm")
    return (540, 960, 1.0)


def sc_onread(cv, t, lt, i):
    bg(cv, BLUE, 26)
    sx0, sy0, sx1, sy1 = phone(cv)
    cv.text(((sx0 + sx1) / 2, sy0 + 90), "Sylvia & Guojun", "interx", 36, WHITE)
    msgs = [("Scan pics! Baby's healthy", chunk_t(i, 0)), ("Week 18 update!", chunk_t(i, 1)), ("Felt the first kick today!!", chunk_t(i, 2))]
    y = sy0 + 200
    for txt, t0 in msgs:
        u = prog(t, t0, t0 + 0.3)
        if u <= 0: continue
        f = F("inters", 34); w = f.getlength(txt) + 60
        yy = y + slide(u, 30)
        cv.rrect(sx1 - 30 - w, yy, sx1 - 30, yy + 80, 30, (60, 120, 240)); cv.text((sx1 - 60 - w + 60, yy + 40), txt, "inters", 34, WHITE, anchor="lm")
        y += 120
    if t >= chunk_t(i, 3):
        cv.text((sx1 - 40, y), "Read 11:42 PM", "inters", 28, GREY, anchor="rt")
    return (540, 900, 1.0)


def sc_posting(cv, t, lt, i):
    bg(cv, (255, 120, 170), 26)
    u = prog(lt, 0, 0.4); y0 = 380 + slide(u)
    card(cv, 150, y0, 930, y0 + 920)
    cv.circ(220, y0 + 70, 34, (255, 150, 180)); cv.text((275, y0 + 70), "Kayla · surrogacy journey", "interx", 34, WHITE, anchor="lm")
    cv.rect(170, y0 + 130, 910, y0 + 690, (40, 34, 50))
    girl(cv, 540, y0 + 670, s=0.6, look=0.0, bump=1.15)
    cv.text((190, y0 + 750), "Week 20, carrying for a family!", "inters", 32, WHITE, anchor="lm")
    likes = int(lerp(3, 12480, eout(prog(t, chunk_t(i, 2), chunk_t(i, 3) + 1.0))))
    cv.text((190, y0 + 830), f"{likes:,} likes", "interx", 36, (255, 120, 150), anchor="lm")
    return (540, 900, 1.0)


def sc_dm(cv, t, lt, i):
    bg(cv, (180, 120, 255), 26)
    sx0, sy0, sx1, sy1 = phone(cv)
    cv.text(((sx0 + sx1) / 2, sy0 + 90), "Message request", "interx", 34, WHITE)
    cv.text(((sx0 + sx1) / 2, sy0 + 140), "New message", "inters", 28, GREY)
    if t >= chunk_t(i, 1):
        lines = ["Hey, this is gonna sound", "so weird, but I think I'm", "carrying a baby for the", "same couple that you are."]
        n = 1 + int(3 * clamp((t - chunk_t(i, 1)) / max(0.3, chunk_t(i, 3) - chunk_t(i, 1))))
        cv.rrect(sx0 + 30, sy0 + 220, sx1 - 70, sy0 + 260 + 60 * n, 30, (52, 44, 66))
        for k in range(n):
            cv.text((sx0 + 60, sy0 + 260 + k * 60), lines[k], "inters", 34, WHITE, anchor="lm")
    return (540, 900, 1.0)


def sc_more(cv, t, lt, i):
    bg(cv, (180, 120, 255), 30)
    names = ["Another surrogate"] * 6
    n = 1 + int(5 * eout(prog(lt, 0.3, LINES[i]["dur"] - 0.3)))
    for k in range(n):
        y = 380 + k * 112
        card(cv, 160, y, 920, y + 94, c=(40, 33, 52), r=22)
        cv.circ(215, y + 47, 28, (120 + k * 15, 90, 200)); cv.text((265, y + 47), names[k], "interx", 34, WHITE, anchor="lm")
        cv.text((880, y + 47), "same couple?", "inters", 28, RED, anchor="rm")
    cv.circ(880, 330, 46, RED); cv.text((880, 330), str(n), "interx", 50, WHITE)
    return (540, 960, 1.0)


def sc_eight(cv, t, lt, i):
    cv.rect(0, 0, W, H, (12, 8, 14)); cv.glow_ell(540, 820, 560, 420, RED, 50)
    victor(cv, 470, 1020, 0.42); elise(cv, 610, 1020, 0.42)
    for k in range(8):
        a = -math.pi / 2 + k * math.pi / 4
        x, y = 540 + math.cos(a) * 380, 820 + math.sin(a) * 380
        u = prog(lt, 0.1 + k * 0.08, 0.4 + k * 0.08)
        if u <= 0: continue
        cv.line([(x, y + 40), (540, 820)], (120, 40, 60), 3)
        girl(cv, x, y + 120, s=0.26, look=0.0, bump=1.2)
    return (540, 900, 1.0)


def sc_dig(cv, t, lt, i):
    bg(cv, BLUE, 24)
    u = prog(lt, 0, 0.4); y0 = 400 + slide(u)
    cv.rect(170, y0, 910, y0 + 900, (236, 232, 224))
    cv.text((540, y0 + 70), "BUSINESS REGISTRY", "mono", 30, (100, 96, 110))
    cv.text((540, y0 + 150), "THE SURROGACY AGENCY", "interx", 50, INK)
    cv.rect(220, y0 + 210, 860, y0 + 214, (190, 186, 180))
    cv.text((230, y0 + 280), "Status: Active", "inters", 32, (90, 86, 96), anchor="lm")
    cv.text((230, y0 + 400), "Registered officers:", "inters", 34, INK, anchor="lm")
    for k in range(2):
        cv.rrect(230, y0 + 470 + k * 110, 760, y0 + 540 + k * 110, 8, (30, 28, 34))
    return (540, 960, lerp(1.0, 1.1, ease(prog(lt, 1.5, 4.5))))


def sc_owners(cv, t, lt, i):
    sc_dig(cv, t, 0.5, i)
    y0 = 400
    nc = len(LINES[i]["chunks"])
    if t < chunk_t(i, nc - 2): return (540, 960, 1.0)
    for k, nm in enumerate(("Sylvia · Founder", "Guojun · Founder")):
        cv.rrect(230, y0 + 470 + k * 110, 860, y0 + 540 + k * 110, 8, (255, 226, 120))
        cv.text((250, y0 + 505 + k * 110), nm, "interx", 38, INK, anchor="lm")
    if t >= chunk_t(i, nc - 1):
        q = eout(prog(t, chunk_t(i, nc - 1), chunk_t(i, nc - 1) + 0.25))
        im = Image.new("RGBA", (760, 220), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle([14, 14, 746, 206], radius=12, outline=(210, 30, 50, 235), width=10)
        d.text((380, 112), "FOUNDED BY THE COUPLE", font=F("anton", int(lerp(110, 74, q))), fill=(210, 30, 50, 240), anchor="mm")
        im = im.rotate(-6, expand=True).resize((int(im.width * 0.9 * SS), int(im.height * 0.9 * SS)))
        cv.im.paste(im, (int(540 * SS - im.width / 2), int(1140 * SS - im.height / 2)), im)
    return (540, 960, 1.05)


def sc_police(cv, t, lt, i):
    cv.rect(0, 0, W, H, (10, 12, 26)); cv.glow_ell(800, 300, 400, 300, (120, 140, 220), 30)
    cv.poly([(0, 1000), (380, 820), (760, 900), (W, 760), (W, H), (0, H)], (18, 20, 30))        # hills
    hx = 640
    cv.rect(hx - 260, 640, hx + 260, 900, (44, 40, 56)); cv.poly([(hx - 290, 650), (hx, 520), (hx + 290, 650)], (34, 30, 44))
    for r in range(2):
        for c in range(4):
            lit = (r + c) % 2 == 0
            cv.rect(hx - 210 + c * 120, 680 + r * 100, hx - 150 + c * 120, 740 + r * 100, (255, 214, 150) if lit else (20, 20, 30))
    for k in range(14):                                         # gate bars
        gx = 120 + k * 34; cv.rect(gx, 980, gx + 8, 1180, (60, 60, 72))
    cv.rect(110, 980, 600, 994, (60, 60, 72))
    u = ease(prog(t, chunk_t(i, 1), chunk_t(i, 2) + 1.0))
    cx = lerp(-300, 760, u)
    cv.rrect(cx - 200, 1200, cx + 200, 1310, 30, (230, 232, 240)); cv.rrect(cx - 120, 1140, cx + 100, 1220, 30, (230, 232, 240))
    cv.rect(cx - 200, 1240, cx + 200, 1262, (30, 40, 90)); cv.text((cx, 1285), "POLICE", "interx", 30, (30, 40, 90))
    for wx in (cx - 130, cx + 130): cv.circ(wx, 1315, 40, (10, 10, 14))
    cv.rect(cx - 50, 1128, cx + 30, 1142, (200, 30, 40)); police_lights(cv, t, cx - 10, 1135, 0.9)
    return (540, lerp(900, 1000, ease(prog(lt, 0, 5))), 1.0)


def sc_cribs(cv, t, lt, i):
    cv.rect(0, 0, W, H, (36, 32, 40)); cv.rect(0, 1100, W, H, (54, 48, 52))
    cv.glow_ell(540, 400, 600, 300, (255, 230, 190), 40)
    n = int(1 + 14 * eout(prog(t, chunk_t(i, 0), chunk_t(i, 2) + 0.6)))
    k = 0
    for r in range(4):
        for c in range(5):
            if k >= n or k >= 15: break
            crib(cv, 140 + c * 200 + (r % 2) * 40, 520 + r * 200, 0.7); k += 1
    q = eout(prog(t, chunk_t(i, 2), chunk_t(i, 2) + 0.3))
    if q > 0:
        cv.rrect(330, 1260, 750, 1400, 30, (200, 30, 44)); cv.text((540, 1330), f"{n}+ BABIES" if n >= 15 else f"{n} BABIES", "anton", 90, WHITE)
    police_lights(cv, t, 1000, 300, 0.5)
    return (540, 960, 1.0)


def sc_chaos(cv, t, lt, i):
    cv.rect(0, 0, W, H, (34, 30, 38)); cv.rect(0, 1150, W, H, (52, 46, 50))
    for k in range(4): crib(cv, 160 + k * 250, 560, 0.6, baby=k % 2 == 0)
    for k in range(7):
        x = (120 + k * 140 + math.sin(t * 1.5 + k) * 40)
        toddler(cv, x, 1240 + (k % 2) * 40, 0.7, t * 6 + k)
    for k in range(6):                                          # bottles on the floor
        bx = 90 + k * 170; cv.rrect(bx, 1350, bx + 60, 1376, 10, (230, 230, 240)); cv.rect(bx + 60, 1356, bx + 74, 1370, (240, 160, 180))
    if t >= chunk_t(i, 2):
        for k, x in enumerate((360, 760)):
            m35.suit_man(cv, x, 1150, s=0.5, shades=False, color=(120, 160, 190), rim=(150, 190, 220))
        cv.text((560, 380), "NOT ENOUGH ADULTS", "anton", 70, AMBER)
    return (540 + math.sin(t * 30) * 2, 960, 1.0)


def sc_arrest(cv, t, lt, i):
    cv.rect(0, 0, W, H, (8, 8, 16)); police_lights(cv, t, 540, 500, 1.0)
    victor(cv, 440, 1300, 0.8); elise(cv, 660, 1300, 0.8)
    q = eout(prog(lt, 0.4, 0.8))
    if q > 0:
        im = Image.new("RGBA", (700, 200), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle([12, 12, 688, 188], radius=12, outline=(220, 30, 50, 240), width=10)
        d.text((350, 102), "ARRESTED", font=F("anton", int(lerp(150, 110, q))), fill=(220, 30, 50, 245), anchor="mm")
        im = im.rotate(7, expand=True).resize((int(im.width * 0.9 * SS), int(im.height * 0.9 * SS)))
        cv.im.paste(im, (int(540 * SS - im.width / 2), int(560 * SS - im.height / 2)), im)
    return (540, 960, 1.0)


def sc_why(cv, t, lt, i):
    cv.rect(0, 0, W, H, (8, 6, 12)); cv.glow_ell(540, 900, 500, 400, RED, int(50 + 30 * math.sin(t * 2)))
    q = eout(prog(t, chunk_t(i, 1), chunk_t(i, 1) + 0.4))
    cv.text((540, 760), "WHY", "anton", 220, WHITE)
    cv.text((540, 990), "17 BABIES?", "anton", 160 * (0.9 + 0.1 * q), RED)
    return (540, 900, lerp(1.0, 1.08, ease(prog(lt, 0, 3))))


def sc_end(cv, t, lt, i):
    bg(cv, RED, 36)
    girl(cv, 540, 1180, s=0.7, look=0.0, bump=1.2)
    u = prog(lt, 0.2, 0.6)
    cv.rrect(240, 1260 + slide(u, 30), 840, 1370 + slide(u, 30), 55, None, outline=WHITE, w=5)
    cv.text((540, 1315 + slide(u, 30)), "FOLLOW FOR PART 2", "interx", 46, WHITE)
    return (540, 960, 1.0)


def sc_intro(cv, t, lt, i):
    bg(cv, (180, 120, 255), 34)
    for k in range(7):                                           # rabbit hole spiral
        r = 420 - k * 56 + (t * 40) % 56
        cv.circ(540, 860, max(10, r), None, outline=(90 + k * 18, 60, 140 + k * 10), w=6)
    u = prog(lt, 0.1, 0.5); y = 380 + slide(u)
    card(cv, 170, y, 910, y + 220)
    cv.circ(270, y + 110, 62, (120, 80, 200)); cv.text((270, y + 110), "K", "interx", 70, WHITE)
    cv.text((360, y + 80), "Kaelyn", "interx", 52, WHITE, anchor="lm"); cv.text((360, y + 145), "a dark curiosity", "inters", 34, GREY, anchor="lm")
    if t >= chunk_t(i, 2):
        q = eout(prog(t, chunk_t(i, 2), chunk_t(i, 2) + 0.3))
        cv.rrect(330, 1220, 750, 1320, 50, RED); cv.text((540, 1270), "FOLLOW", "interx", 50, WHITE)
    return (540, 960, 1.0)


def sc_onread2(cv, t, lt, i):
    sc_onread(cv, LINES[i - 2]["start"] + 30, 30, i - 2)
    return (540, 900, lerp(1.0, 1.08, ease(prog(lt, 0, 3))))


def sc_arcadia(cv, t, lt, i):
    sc_police(cv, LINES[i - 1]["start"] + LINES[i - 1]["dur"] + 0.4 + lt, 3 + lt, i - 1)
    u = prog(lt, 0.3, 0.7); y = 300 + slide(u)
    card(cv, 240, y, 840, y + 150, c=(30, 24, 36))
    cv.circ(310, y + 75, 26, RED); cv.circ(310, y + 75, 10, WHITE)
    cv.text((360, y + 75), "Arcadia, California", "interx", 44, WHITE, anchor="lm")
    return (540, 1000, 1.0)


def sc_nightmare(cv, t, lt, i):
    cv.rect(0, 0, W, H, (8, 6, 12)); cv.glow_ell(540, 900, 500, 400, RED, int(50 + 30 * math.sin(t * 2)))
    for k in range(3): crib(cv, 300 + k * 240, 1200, 0.7, baby=False)
    q = eout(prog(t, chunk_t(i, len(LINES[i]["chunks"]) - 1), chunk_t(i, len(LINES[i]["chunks"]) - 1) + 0.4))
    cv.text((540, 700), "THE STUFF OF", "anton", 120, WHITE)
    cv.text((540, 860), "NIGHTMARES", "anton", 150 * (0.9 + 0.1 * q), RED)
    return (540, 900, lerp(1.0, 1.08, ease(prog(lt, 0, 3))))


def sc_end2(cv, t, lt, i):
    bg(cv, RED, 30)
    u = prog(lt, 0.2, 0.6); y = 420 + slide(u)
    card(cv, 170, y, 910, y + 520)
    cv.rect(220, y + 50, 860, y + 330, (70, 50, 110)); cv.text((540, y + 190), "THE JOURNEY", "anton", 110, WHITE)
    cv.text((540, y + 400), "The New Yorker · podcast", "inters", 38, GREY)
    cv.text((540, y + 465), "this season", "inters", 32, GREY)
    if t >= chunk_t(i, len(LINES[i]["chunks"]) - 2):
        cv.rrect(260, 1180, 820, 1290, 55, None, outline=WHITE, w=5); cv.text((540, 1235), "FOLLOW FOR MORE", "interx", 46, WHITE)
    return (540, 960, 1.0)


SCENES = {"intro": sc_intro, "onread2": sc_onread2, "arcadia": sc_arcadia, "nightmare": sc_nightmare, "hook": sc_hook, "broke": sc_broke, "signup": sc_signup, "couple": sc_couple, "pregnant": sc_pregnant, "noshow": sc_noshow,
          "onread": sc_onread, "posting": sc_posting, "dm": sc_dm, "more": sc_more, "eight": sc_eight, "dig": sc_dig, "owners": sc_owners,
          "police": sc_police, "cribs": sc_cribs, "chaos": sc_chaos, "arrest": sc_arrest, "why": sc_why, "end": sc_end2}


# ---------------------------------------------------------------- PART 2 scenes
def stamp(cv, text, x, y, q, col=(220, 30, 50), rot=7, size=130, w=760):
    if q <= 0: return
    im = Image.new("RGBA", (w, 220), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([12, 12, w - 12, 208], radius=12, outline=col + (240,), width=10)
    d.text((w / 2, 112), text, font=F("anton", int(lerp(size * 1.35, size, q))), fill=col + (245,), anchor="mm")
    im = im.rotate(rot, expand=True).resize((int(im.width * 0.9 * SS), int(im.height * 0.9 * SS)))
    cv.im.paste(im, (int(x * SS - im.width / 2), int(y * SS - im.height / 2)), im)


def at(i, k):
    n = len(LINES[i]["chunks"]); return chunk_t(i, min(k, n - 1))


def sc_hook2(cv, t, lt, i):
    bg(cv, RED, 40)
    q = eout(prog(lt, 0.1, 0.7))
    cv.text((540, 480 + slide(q, 30)), "PART 2", "anton", 120, RED)
    cv.text((540, 640 + slide(q, 30)), "WHAT HAPPENED", "anton", 130, WHITE)
    cv.text((540, 790 + slide(q, 30)), "NEXT", "anton", 170, WHITE)
    victor(cv, 430, 1450, 0.6); elise(cv, 650, 1450, 0.6)
    return (540, 960, lerp(1.0, 1.05, prog(lt, 0, 3)))


def sc_recap(cv, t, lt, i):
    bg(cv, (180, 120, 255), 30)
    girl(cv, 540, 1150, s=0.6, bump=1.15)
    for k in range(6):
        a = math.pi + k * math.pi / 5
        x, y = 540 + math.cos(a) * 390, 880 + math.sin(a) * 300
        if t < at(i, 3) + k * 0.12: continue
        girl(cv, x, y + 110, s=0.24, bump=1.2)
    u = prog(lt, 0.1, 0.5)
    cv.rrect(300, 1250 + slide(u, 30), 780, 1350 + slide(u, 30), 50, (40, 33, 52)); cv.text((540, 1300 + slide(u, 30)), "PREVIOUSLY", "interx", 46, WHITE)
    return (540, 960, 1.0)


def sc_correct(cv, t, lt, i):
    bg(cv, AMBER, 34)
    u = prog(lt, 0.1, 0.5); y = 380 + slide(u)
    card(cv, 150, y, 930, y + 720)
    cv.text((540, y + 90), "CORRECTION", "anton", 80, AMBER)
    cv.text((540, y + 210), "Part 1 said:", "inters", 36, GREY)
    cv.text((540, y + 290), "\"all under 3 years old\"", "interx", 50, WHITE)
    cv.line([(250, y + 290), (830, y + 290)], RED, 8 * eout(prog(t, at(i, 2), at(i, 2) + 0.3)))
    if t >= at(i, 3):
        q = eout(prog(t, at(i, 3), at(i, 3) + 0.4))
        cv.text((540, y + 420), "Actually:", "inters", 36, GREY)
        cv.text((540, y + 530), "2 months – 13 years", "anton", 92 * (0.9 + 0.1 * q), GREEN)
    return (540, 900, 1.0)


def sc_hospital(cv, t, lt, i):
    cv.rect(0, 0, W, H, (14, 16, 30)); cv.glow_ell(540, 500, 500, 260, (120, 160, 255), 30)
    cv.rect(220, 620, 860, 1180, (210, 214, 226)); cv.rect(220, 600, 860, 640, (180, 186, 200))
    cv.rect(500, 660, 580, 860, (220, 40, 60)); cv.rect(440, 720, 640, 800, (220, 40, 60))
    for r in range(2):
        for c in range(4):
            cv.rect(270 + c * 150, 900 + r * 120, 350 + c * 150, 970 + r * 120, (255, 236, 190) if (r + c) % 2 else (70, 80, 110))
    cv.text((540, 1250), "2025", "anton", 90, WHITE)
    if t >= at(i, 3):
        q = eout(prog(t, at(i, 3), at(i, 3) + 0.3))
        card(cv, 230, 330, 850, 520, c=(30, 26, 40)); cv.text((540, 390), "Hospital → Police", "interx", 48, WHITE)
        cv.text((540, 460), "child with a head injury", "inters", 34, (255, 170, 170))
        police_lights(cv, t, 540, 1400, 0.6 * q)
    return (540, 960, 1.0)


def sc_found(cv, t, lt, i):
    sc_police(cv, t, lt, i)
    u = prog(lt, 0.2, 0.6); y = 300 + slide(u)
    card(cv, 240, y, 840, y + 150, c=(30, 24, 36)); cv.circ(310, y + 75, 26, RED); cv.circ(310, y + 75, 10, WHITE)
    cv.text((360, y + 75), "Arcadia, California", "interx", 44, WHITE, anchor="lm")
    if t >= at(i, 3):
        q = eout(prog(t, at(i, 3), at(i, 3) + 0.3))
        cv.rrect(330, 480, 750, 600, 30, (200, 30, 44)); cv.text((540, 540), "15 CHILDREN", "anton", 80 * (0.9 + 0.1 * q), WHITE)
    return (540, 1000, 1.0)


def sc_cameras(cv, t, lt, i):
    cv.rect(0, 0, W, H, (10, 10, 14))
    n = min(32, int(1 + 31 * eout(prog(lt, 0.2, LINES[i]["dur"] * 0.7))))
    for k in range(32):
        r, c = divmod(k, 8)
        x0, y0 = 70 + c * 120, 440 + r * 150
        cv.rect(x0, y0, x0 + 110, y0 + 130, (30, 34, 40) if k < n else (16, 16, 20))
        if k < n:
            cv.circ(x0 + 16, y0 + 16, 7, (230, 40, 50) if int(t * 2 + k) % 2 else (90, 20, 24))
            cv.text((x0 + 55, y0 + 105), f"CAM {k + 1:02d}", "mono", 16, (120, 130, 140))
    cv.rrect(340, 260, 740, 380, 30, (200, 30, 44)); cv.text((540, 320), f"{n} CAMERAS", "anton", 70, WHITE)
    return (540, 980, 1.0)


def sc_released(cv, t, lt, i):
    cv.rect(0, 0, W, H, (8, 8, 16)); police_lights(cv, t, 540, 400, 0.6 if t < at(i, 2) else 0.15)
    victor(cv, 440, 1600, 0.6); elise(cv, 660, 1600, 0.6)
    stamp(cv, "ARRESTED", 540, 430, eout(prog(lt, 0.2, 0.5)))
    if t >= at(i, 2):
        stamp(cv, "RELEASED · NO CHARGES", 540, 680, eout(prog(t, at(i, 2), at(i, 2) + 0.3)), col=(255, 200, 60), rot=-5, size=70, w=900)
    return (540, 960, 1.0)


def sc_custody(cv, t, lt, i):
    bg(cv, BLUE, 28)
    n = int(1 + 20 * eout(prog(lt, 0.2, LINES[i]["dur"] - 0.4)))
    for k in range(n):
        r, c = divmod(k, 7)
        toddler(cv, 150 + c * 130, 760 + r * 230, 0.7, t * 3 + k)
    cv.text((540, 330), f"{n}", "anton", 180, WHITE)
    cv.text((540, 470), "CHILDREN · PROTECTIVE CUSTODY", "interx", 40, (190, 210, 255))
    return (540, 960, 1.0)


def sc_business(cv, t, lt, i):
    sc_police(cv, LINES[4]["start"] + 3, 3, 4)
    cv.rect(0, 0, W, H, (0, 0, 0)) if False else None
    u = prog(lt, 0.3, 0.7); y = 230 + slide(u)
    card(cv, 170, y, 910, y + 240, c=(236, 232, 224))
    cv.text((540, y + 70), "REGISTERED AT THIS ADDRESS", "mono", 26, (100, 96, 110))
    cv.text((540, y + 150), "A SURROGACY COMPANY", "interx", 52, INK)
    if t >= at(i, 4):
        stamp(cv, "SAME HOUSE", 540, 560, eout(prog(t, at(i, 4), at(i, 4) + 0.3)), rot=-6, size=110)
    return (540, 1000, 1.0)


def sc_lies(cv, t, lt, i):
    bg(cv, (255, 120, 170), 26)
    girl(cv, 300, 1400, s=0.6, bump=1.1); girl(cv, 780, 1400, s=0.6, bump=1.1)
    u = prog(t, at(i, 2), at(i, 2) + 0.4)
    if u > 0:
        y = 420 + slide(u)
        cv.rrect(170, y, 910, y + 200, 40, (52, 44, 66))
        cv.text((540, y + 75), "\"I'm struggling to", "interx", 46, WHITE); cv.text((540, y + 140), "get pregnant\"", "interx", 46, WHITE)
        cv.rrect(380, y + 230, 700, y + 300, 30, RED); cv.text((540, y + 265), "ALLEGEDLY TOLD", "interx", 32, WHITE)
    return (540, 960, 1.0)


def doc(cv, y, head, rows, hi=-1):
    cv.rect(160, y, 920, y + 140 + 90 * len(rows), (236, 232, 224))
    cv.text((540, y + 60), head, "mono", 30, (100, 96, 110))
    cv.rect(200, y + 100, 880, y + 104, (190, 186, 180))
    for k, r in enumerate(rows):
        yy = y + 150 + k * 90
        if k == hi: cv.rect(190, yy - 38, 890, yy + 38, (255, 226, 120))
        cv.text((210, yy), r, "interx", 40, INK, anchor="lm")


def sc_charged(cv, t, lt, i):
    bg(cv, BLUE, 26)
    u = prog(lt, 0.1, 0.5); y = 420 + slide(u)
    rows = ["People of California", "v. Xuan & Zhang", "Filed: October 2026"]
    doc(cv, y, "LOS ANGELES COUNTY · DISTRICT ATTORNEY", rows, hi=2 if t < at(i, 4) else -1)
    if t >= at(i, 4):
        stamp(cv, "CHARGED", 540, y + 560, eout(prog(t, at(i, 4), at(i, 4) + 0.3)), rot=-6)
        cv.text((540, y + 760), "conspiracy to commit child abuse", "interx", 42, WHITE)
    return (540, 960, 1.0)


def sc_alleged(cv, t, lt, i):
    cv.rect(0, 0, W, H, (8, 6, 12)); cv.glow_ell(540, 900, 500, 400, RED, int(50 + 30 * math.sin(t * 2)))
    for k in range(16):
        r, c = divmod(k, 8)
        col = (220, 60, 70) if (k < 15 and t >= at(i, 2)) else (220, 220, 230)
        cv.circ(160 + c * 108, 1000 + r * 110, 34, col)
    cv.text((540, 540), "15 OF 16", "anton", 200, WHITE)
    cv.text((540, 720), "ALLEGED", "anton", 110, RED)
    return (540, 900, lerp(1.0, 1.06, ease(prog(lt, 0, 3))))


def sc_witness(cv, t, lt, i):
    bg(cv, (200, 120, 220), 26)
    elise(cv, 540, 1450, 0.8)
    u = prog(lt, 0.2, 0.6); y = 380 + slide(u)
    card(cv, 170, y, 910, y + 200)
    cv.text((540, y + 70), "ALSO ACCUSED OF", "mono", 30, GREY)
    cv.text((540, y + 140), "dissuading witnesses", "interx", 52, WHITE)
    return (540, 960, 1.0)


def sc_plea(cv, t, lt, i):
    cv.rect(0, 0, W, H, (40, 28, 22)); cv.rect(0, 1150, W, H, (70, 48, 34))
    cv.rect(140, 520, 940, 760, (96, 64, 42)); cv.rect(160, 500, 920, 530, (120, 82, 54))    # bench
    cv.text((540, 640), "SUPERIOR COURT · LOS ANGELES", "mono", 28, (230, 210, 170))
    victor(cv, 430, 1450, 0.6); elise(cv, 650, 1450, 0.6)
    stamp(cv, "NOT GUILTY", 540, 900, eout(prog(t, at(i, 2), at(i, 2) + 0.3)), col=(240, 240, 250), rot=0, size=120)
    if t >= at(i, len(LINES[i]["chunks"]) - 1):
        cv.text((540, 420), "plea entered · allegations denied", "inters", 38, (230, 210, 170))
    return (540, 960, 1.0)


def sc_bail(cv, t, lt, i):
    bg(cv, GREEN, 26)
    v = int(20_000_000 * eout(prog(lt, 0.2, 1.4)))
    cv.text((540, 600), "BAIL", "anton", 110, WHITE)
    cv.text((540, 800), f"${v:,}", "anton", 130, GREEN)
    cv.text((540, 940), "each", "interx", 50, WHITE)
    if t >= at(i, 4):
        stamp(cv, "REDUCTION DENIED", 540, 1220, eout(prog(t, at(i, 4), at(i, 4) + 0.3)), rot=-5, size=80, w=900)
    return (540, 960, 1.0)


def sc_nanny(cv, t, lt, i):
    cv.rect(0, 0, W, H, (30, 26, 20)); cv.glow_ell(540, 800, 500, 500, (255, 220, 150), 30)
    u = prog(lt, 0.1, 0.5); y = 340 + slide(u)
    cv.rect(220, y, 860, y + 900, (232, 214, 170))
    cv.text((540, y + 120), "WANTED", "anton", 150, (110, 30, 20))
    cv.rect(330, y + 220, 750, y + 640, (200, 184, 146))
    cv.circ(540, y + 380, 90, (120, 104, 80)); cv.ell(540, y + 600, 160, 110, (120, 104, 80))
    cv.text((540, y + 720), "THE NANNY", "interx", 56, (60, 30, 20))
    cv.text((540, y + 800), "arrest warrant issued", "inters", 36, (90, 60, 40))
    return (540, 960, 1.0)


def sc_mothers(cv, t, lt, i):
    bg(cv, (255, 120, 170), 30)
    for k, x in enumerate((260, 540, 820)):
        girl(cv, x, 1350, s=0.55, look=0.0)
        crib(cv, x, 1430, 0.45)
    u = prog(t, at(i, 2), at(i, 2) + 0.4)
    if u > 0:
        cv.rrect(220, 500 + slide(u), 860, 620 + slide(u), 40, (40, 33, 52)); cv.text((540, 560 + slide(u)), "FIGHTING FOR CUSTODY", "interx", 46, WHITE)
    return (540, 960, 1.0)


def sc_sentence(cv, t, lt, i):
    cv.rect(0, 0, W, H, (10, 10, 18))
    for k in range(12): cv.rect(120 + k * 74, 300, 136 + k * 74, 1000, (60, 64, 80))      # bars
    cv.text((540, 1120), "IF CONVICTED", "mono", 40, GREY)
    if t >= at(i, 2):
        cv.text((540, 1260), "Guojun: up to 17 yrs", "interx", 58, WHITE)
    if t >= at(i, len(LINES[i]["chunks"]) - 1):
        cv.text((540, 1360), "Sylvia: up to ~12 yrs", "interx", 58, WHITE)
    return (540, 960, 1.0)


def sc_pending(cv, t, lt, i):
    cv.rect(0, 0, W, H, (40, 28, 22)); cv.rect(0, 1150, W, H, (70, 48, 34))
    cv.rect(140, 520, 940, 760, (96, 64, 42)); cv.rect(160, 500, 920, 530, (120, 82, 54))
    cv.text((540, 640), "SUPERIOR COURT · LOS ANGELES", "mono", 28, (230, 210, 170))
    stamp(cv, "TRIAL: PENDING", 540, 930, eout(prog(lt, 0.3, 0.7)), col=(255, 200, 60), rot=0, size=100, w=900)
    if t >= at(i, 4):
        cv.text((540, 1110), "innocent until proven guilty", "interx", 44, WHITE)
    return (540, 960, 1.0)


def sc_end3(cv, t, lt, i):
    bg(cv, RED, 36)
    cv.text((540, 640), "VERDICT", "anton", 170, WHITE)
    cv.text((540, 800), "COMING", "anton", 120, RED)
    u = prog(lt, 0.2, 0.6)
    cv.rrect(240, 1180 + slide(u, 30), 840, 1290 + slide(u, 30), 55, None, outline=WHITE, w=5)
    cv.text((540, 1235 + slide(u, 30)), "FOLLOW FOR PART 3", "interx", 46, WHITE)
    cv.text((540, 1420), "Sources: LA County DA, CBS, ABC7, CNN", "inters", 30, GREY)
    return (540, 960, 1.0)


SCENES = {"hook2": sc_hook2, "recap": sc_recap, "correct": sc_correct, "hospital": sc_hospital, "found": sc_found, "cameras": sc_cameras,
          "released": sc_released, "custody": sc_custody, "business": sc_business, "lies": sc_lies, "charged": sc_charged,
          "alleged": sc_alleged, "witness": sc_witness, "plea": sc_plea, "bail": sc_bail, "nanny": sc_nanny, "mothers": sc_mothers,
          "sentence": sc_sentence, "pending": sc_pending, "end3": sc_end3}


def line_at(t):
    k = 0
    for j, l in enumerate(LINES):
        if t >= l["start"] - 0.25: k = j
    return k


def frame(t):
    i = line_at(t); l = LINES[i]; lt = t - l["start"]
    cv = Cv(BG)
    cam = SCENES[l["scene"]](cv, t, lt, i)
    if lt < 0.25:
        cx, cy, z = cam; cam = (cx, cy, z * (1 + 0.05 * (1 - eout(lt / 0.25))))
    img = camera(cv, *cam)
    img = post(img, t)
    d = ImageDraw.Draw(img, "RGBA")                              # small series tag
    am.draw_caption(img, t)
    if t < 0.4: img = Image.blend(Image.new("RGB", (W, H)), img, t / 0.4)
    if t > DUR - 0.6: img = Image.blend(img, Image.new("RGB", (W, H)), clamp((t - (DUR - 0.6)) / 0.6))
    return img


if __name__ == "__main__":
    if sys.argv[1] == "--still":
        frame(float(sys.argv[2])).save(sys.argv[3]); sys.exit()
    a, b, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for fi in range(a, b):
        p.stdin.write(frame(fi / FPS).tobytes())
    p.stdin.close(); p.wait()
