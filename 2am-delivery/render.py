"""THE 2AM DELIVERY — frame renderer (Pillow, flat 2D). Original story and designs; the main character is
the house character (white stick figure, red hoodie, black joggers) from ../35-million/render.py.

usage: python render.py <start_frame> <end_frame> <out.mp4>
       python render.py --still <t> <out.png>
"""
import importlib.util, json, math, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
m35 = _load("m35", os.path.join(HERE, "..", "35-million", "render.py"))
lb = m35.lb
Cv, camera, F, post = lb.Cv, lb.camera, lb.F, lb.post
clamp, lerp, ease, eout, prog, hrand, wrap = lb.clamp, lb.lerp, lb.ease, lb.eout, lb.prog, lb.hrand, lb.wrap
you_stand, you_sit, man_shadow, phone_frame = m35.you_stand, m35.you_sit, m35.man_shadow, m35.phone_frame
W, H, FPS, SS = lb.W, lb.H, lb.FPS, lb.SS

TL = json.load(open(os.path.join(HERE, "timeline.json")))
LINES = TL["lines"]; DUR = TL["duration"]
BG = (14, 10, 18)
CARD = (30, 24, 36)
CARD2 = (40, 33, 48)
WHITE = (244, 242, 248)
GREY = (150, 140, 160)
RED = (240, 66, 92)
BLUE = (98, 168, 255)
AMBER = (255, 172, 64)
GREEN = (72, 214, 130)
PAPER = (236, 230, 214)
INK = (28, 24, 30)
CASHG = (118, 170, 120)

LABELS = {"spend": "THOUGHT #1 · SPEND IT", "report": "THOUGHT #1 · SPEND IT", "dial": "THOUGHT #2 · CALL THE POLICE",
          "burner": "THOUGHT #2 · CALL THE POLICE", "search": "THOUGHT #3 · FIND THE OWNER", "missing": "THOUGHT #3 · FIND THE OWNER",
          "keep": "EVERY MOVE IS A PROBLEM", "bring": "EVERY MOVE IS A PROBLEM", "police": "EVERY MOVE IS A PROBLEM", "final": "YOUR CALL"}
CLOCK = ["02:14", "02:15", "02:16", "02:17", "02:22", "02:31", "02:47", "02:48", "02:52", "03:20", "03:21", "03:40",
         "04:05", "05:10", "05:20", "05:30", "05:59"]
RISK = [0, 5, 10, 15, 25, 35, 40, 55, 65, 70, 80, 88, 94, 95, 96, 97, 99]


def line_at(t):
    k = 0
    for i, l in enumerate(LINES):
        if t >= l["start"] - 0.25: k = i
    return k


def chunk_t(i, n):
    return LINES[i]["chunks"][min(n, len(LINES[i]["chunks"]) - 1)][0]


# ---------------------------------------------------------------- shared drawing
def bg(cv, glow=RED, ga=40):
    cv.rect(0, 0, W, H, BG)
    cv.glow_ell(540, 700, 700, 600, glow, ga)


def card(cv, x0, y0, x1, y1, c=CARD, r=28, outline=(60, 50, 70)):
    cv.rrect(x0 + 6, y0 + 10, x1 + 6, y1 + 10, r, (6, 4, 8))
    cv.rrect(x0, y0, x1, y1, r, c, outline=outline, w=2)


def slide(u, dy=70):
    return (1 - eout(u)) * dy


def cash_stack(cv, x, y, w=170, h=70, rot_seed=0):
    cv.rrect(x - w / 2, y - h / 2, x + w / 2, y + h / 2, 8, CASHG)
    cv.rrect(x - w / 2 + 10, y - h / 2 + 10, x + w / 2 - 10, y + h / 2 - 10, 6, None, outline=(82, 128, 88), w=3)
    cv.circ(x, y, h * 0.28, (96, 148, 100))
    cv.rect(x - 16, y - h / 2, x + 16, y + h / 2, (214, 186, 110))


def box_open(cv, cx, cy, s=1.0, fill=1.0, burner=0.0):
    """top-down open cardboard box with cash stacks; burner = glow of a small phone inside"""
    bw, bh = 560 * s, 420 * s
    cv.poly([(cx - bw / 2 - 90 * s, cy - bh / 2 - 60 * s), (cx + bw / 2 + 90 * s, cy - bh / 2 - 60 * s), (cx + bw / 2, cy - bh / 2), (cx - bw / 2, cy - bh / 2)], (150, 112, 70))
    cv.rect(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2, (120, 86, 52))
    cv.rect(cx - bw / 2 + 18 * s, cy - bh / 2 + 18 * s, cx + bw / 2 - 18 * s, cy + bh / 2 - 18 * s, (70, 48, 30))
    cv.poly([(cx - bw / 2, cy + bh / 2), (cx + bw / 2, cy + bh / 2), (cx + bw / 2 + 60 * s, cy + bh / 2 + 70 * s), (cx - bw / 2 - 60 * s, cy + bh / 2 + 70 * s)], (168, 126, 80))
    n = int(12 * fill)
    for k in range(n):
        r, c = divmod(k, 3)
        cash_stack(cv, cx - 160 * s + c * 160 * s, cy - 130 * s + r * 88 * s, 150 * s, 66 * s)
    if burner > 0:
        px, py = cx + 150 * s, cy + 120 * s
        cv.rrect(px - 46 * s, py - 70 * s, px + 46 * s, py + 70 * s, 12 * s, (16, 16, 22))
        cv.rrect(px - 36 * s, py - 58 * s, px + 36 * s, py + 10 * s, 6 * s, (int(60 + 140 * burner), int(80 + 120 * burner), int(110 + 140 * burner)))
        for r in range(3):
            for c in range(3):
                cv.circ(px - 22 * s + c * 22 * s, py + 26 * s + r * 14 * s, 4 * s, (60, 60, 70))
        cv.glow(px, py - 24 * s, 160 * s, (120, 170, 255), int(150 * burner))


def label_tag(cv, x, y, s=1.0, name="D. CROSS", hi=0.0):
    cv.rrect(x - 170 * s, y - 95 * s, x + 170 * s, y + 95 * s, 10 * s, PAPER)
    cv.text((x - 150 * s, y - 62 * s), "DELIVER TO", "mono", 22 * s, (110, 100, 96), anchor="lm")
    cv.text((x - 150 * s, y - 22 * s), name, "interx", 40 * s, INK, anchor="lm")
    if hi > 0:
        cv.rrect(x - 158 * s, y + 8 * s, x - 158 * s + 230 * s * eout(hi), y + 62 * s, 6 * s, (255, 220, 90, 180))
    cv.text((x - 150 * s, y + 36 * s), "APT 4B", "interx", 40 * s, INK, anchor="lm")
    for k in range(14):
        cv.rect(x + 60 * s + k * 7 * s, y + 10 * s, x + 63 * s + k * 7 * s + (k % 3) * s, y + 70 * s, INK)


def note_card(cv, cx, cy, u1, u2, rot=-3):
    im = Image.new("RGBA", (760, 560), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 30, 740, 540], fill=PAPER + (255,))
    for y in range(110, 540, 56): d.line([(40, y), (720, y)], fill=(200, 196, 210, 255), width=2)
    d.rectangle([300, 0, 460, 60], fill=(230, 220, 170, 200))
    f = F("anton", 92)
    if u1 > 0: d.text((380, 210), "HOLD IT 48 HOURS."[:int(17 * clamp(u1 * 1.4))], font=f, fill=INK + (255,), anchor="mm")
    if u2 > 0: d.text((380, 360), "TELL NO ONE."[:int(12 * clamp(u2 * 1.6))], font=f, fill=(170, 30, 40, 255), anchor="mm")
    im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
    im = im.resize((im.width * SS, im.height * SS))
    cv.im.paste(im, (int((cx - im.width / SS / 2) * SS), int((cy - im.height / SS / 2) * SS)), im)


def bubble(cv, x0, y, text, u, who="UNKNOWN", c=(52, 44, 60), tc=WHITE, size=40, maxw=600):
    if u <= 0: return y
    f = F("inters", size)
    lines = wrap(text, f, maxw)
    h = 34 + len(lines) * (size + 12)
    y0 = y + slide(u, 40)
    w = max(f.getlength(l) for l in lines) + 60
    cv.rrect(x0, y0, x0 + w, y0 + h, 30, c)
    for k, l in enumerate(lines):
        cv.text((x0 + 30, y0 + 18 + k * (size + 12)), l, "inters", size, tc, anchor="lt")
    if who: cv.text((x0 + 8, y0 - 26), who, "mono", 22, GREY, anchor="lm")
    return y + h + 56


# ---------------------------------------------------------------- scenes
def sc_door(cv, t, lt, i):
    bg(cv, AMBER, 26)
    cv.rect(0, 1240, W, H, (22, 16, 22))                      # floor
    cv.rect(0, 1232, W, 1242, (40, 30, 38))
    open_u = ease(prog(lt, 0.0, 0.6)) if i == 1 else 0.0
    dx0, dx1, dy0, dy1 = 330, 750, 470, 1240
    cv.rect(dx0 - 26, dy0 - 26, dx1 + 26, dy1, (58, 44, 52))   # frame
    cv.rect(dx0, dy0, dx1, dy1, (10, 8, 12))                  # dark hallway behind
    cv.glow_ell(540, 560, 160, 80, (255, 200, 130), 90 * (1 if i == 1 else 0))
    if i == 1:
        cv.circ(540, 520, 14, (255, 220, 160)); cv.glow(540, 520, 120, (255, 200, 130), 160)
        # courier silhouette holding the box out
        hand = clamp((lt - 0.8) / 1.0)
        man_shadow(cv, 520, 1240, 0.8, holds_phone=False, a=255)
        bx = lerp(660, 720, ease(hand)); by = lerp(820, 900, ease(hand))
        cv.rrect(bx - 120, by - 80, bx + 120, by + 80, 6, (150, 112, 70))
        cv.rect(bx - 120, by - 10, bx + 120, by + 8, (200, 170, 110))
        if lt > 1.6:
            label_tag(cv, bx - 20, by + 20, 0.42, hi=prog(t, chunk_t(1, 2), chunk_t(1, 2) + 0.4))
    # the door leaf (opens inward, toward us, on the right)
    w = (dx1 - dx0) * (1 - 0.8 * open_u)
    shake = (math.sin(t * 90) * 4 if any(a <= lt < a + 0.12 for a in (1.5, 1.85, 2.2)) and i == 0 else 0)
    cv.poly([(dx1 + shake, dy0), (dx1 - w + shake, dy0 + 30 * open_u), (dx1 - w + shake, dy1 - 30 * open_u), (dx1 + shake, dy1)], (92, 52, 44))
    if open_u < 0.5:
        cv.circ(dx0 + 50 + shake, 870, 14, (210, 180, 110))
        cv.circ(540 + shake, 690, 9, (30, 24, 28))            # peephole
        cv.glow_rect(dx0, 1228, dx1, 1240, (255, 200, 130), 200)   # light under the door
        for k in range(2):                                      # feet shadows under the door
            fx = 470 + k * 120 + math.sin(t * 1.3 + k) * 10
            cv.rect(fx, 1229, fx + 60, 1240, (10, 8, 12))
    # you
    you_stand(cv, 210 if i == 1 else 220, 1420, s=0.95, eyes=True, look=0.6 if i == 0 else 0.9)
    cam = (540, 960, 1.0)
    if i == 1:
        u = ease(prog(t, chunk_t(1, 1), chunk_t(1, 2) + 0.6))
        cam = (lerp(540, 690, u), lerp(960, 900, u), lerp(1.0, 2.0, u))
    else:
        cam = (540, 960, lerp(1.0, 1.08, ease(prog(lt, 0, 4))))
    return cam


def sc_cash(cv, t, lt, i):
    bg(cv, AMBER, 50)
    u = ease(prog(lt, 0.2, 1.2))
    box_open(cv, 540, 980, 1.25, fill=u)
    c0 = chunk_t(2, 1)
    if t >= c0 - 0.1:
        q = eout(prog(t, c0 - 0.1, c0 + 0.9))
        v = int(250000 * q) // 1000 * 1000 if q < 1 else 250000
        cv.glow_ell(540, 520, 420, 140, AMBER, int(160 * q))
        cv.text((540, 420), "INSIDE THE BOX", "mono", 30, GREY)
        cv.text((540, 530), "${:,}".format(v), "interx", 150, AMBER)
        if t >= chunk_t(2, 2):
            cv.rrect(430, 620, 650, 680, 30, (60, 44, 30)); cv.text((540, 650), "IN CASH", "mono", 30, AMBER)
    return (540, 900, lerp(1.0, 1.06, prog(lt, 0, 6)))


def sc_note(cv, t, lt, i):
    bg(cv, RED, 30)
    note_card(cv, 540, 860, prog(t, chunk_t(3, 2), chunk_t(3, 2) + 1.0), prog(t, chunk_t(3, 3), chunk_t(3, 3) + 0.7))
    return (540, 880, lerp(1.0, 1.1, ease(prog(lt, 0, 5))))


def sc_spend(cv, t, lt, i):
    bg(cv, GREEN, 26)
    you_stand(cv, 300, 1420, s=0.95, eyes=True, look=0.8)
    items = [("RENT", "$1,850"), ("DEBT", "$14,200"), ("NEW CAR", "$38,000")]
    for k, (a, b) in enumerate(items):
        t0 = chunk_t(4, 2) if k < 2 else chunk_t(4, 3)
        t0 += 0.45 * k if k < 2 else 0
        u = prog(t, t0, t0 + 0.4)
        if u <= 0: continue
        y = 520 + k * 190 + slide(u)
        card(cv, 520, y, 1000, y + 150)
        cv.text((560, y + 75), a, "interx", 44, WHITE, anchor="lm")
        cv.text((960, y + 75), b, "mono", 44, GREEN, anchor="rm")
    return (540, 960, 1.0)


def sc_report(cv, t, lt, i):
    bg(cv, RED, 34)
    u = prog(lt, 0, 0.5)
    y0 = 430 + slide(u)
    card(cv, 150, y0, 930, y0 + 760, c=(236, 232, 226), outline=(190, 186, 180))
    cv.text((540, y0 + 70), "DEALERSHIP · CASH PAYMENT", "mono", 30, (90, 84, 96))
    cv.rect(190, y0 + 110, 890, y0 + 113, (200, 196, 190))
    rows = [("Vehicle", "Sedan 2.0"), ("Amount", "$38,000.00"), ("Paid in", "CASH")]
    for k, (a, b) in enumerate(rows):
        cv.text((200, y0 + 175 + k * 80), a, "inters", 36, (110, 104, 116), anchor="lm")
        cv.text((880, y0 + 175 + k * 80), b, "interx", 36, INK, anchor="rm")
    if t >= chunk_t(5, 1):
        q = eout(prog(t, chunk_t(5, 1), chunk_t(5, 1) + 0.4))
        cv.rrect(190, y0 + 410, 890, y0 + 500, 14, (255, 226, 228))
        cv.text((540, y0 + 455), "Over $10,000 → report filed", "interx", 36, (200, 30, 50))
    if t >= chunk_t(5, 2):
        q = eout(prog(t, chunk_t(5, 2), chunk_t(5, 2) + 0.25))
        sz = lerp(160, 96, q)
        im = Image.new("RGBA", (700, 240), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle([20, 20, 680, 220], radius=14, outline=(220, 30, 50, 230), width=10)
        d.text((350, 122), "REPORTED", font=F("anton", int(sz * 1.1)), fill=(220, 30, 50, 235), anchor="mm")
        im = im.rotate(8, expand=True, resample=Image.BICUBIC).resize((int(im.width * 0.62 * SS), int(im.height * 0.62 * SS)))
        cv.im.paste(im, (int(540 * SS - im.width / 2), int((y0 + 640) * SS - im.height / 2)), im)
    if t >= chunk_t(5, 4):
        bubble(cv, 200, 1250, "Where did this money come from?", prog(t, chunk_t(5, 4), chunk_t(5, 4) + 0.35), who="BANK · COMPLIANCE", c=(60, 30, 40))
    return (540, 960, 1.0)


def sc_dial(cv, t, lt, i):
    bg(cv, BLUE, 30)
    sx0, sy0, sx1, sy1 = phone_frame(cv, 250, 330, 580, 1120)
    cx = (sx0 + sx1) / 2
    n = int(clamp((lt - 0.5) / 0.35) * 1) + int(clamp((lt - 0.85) / 0.35)) + int(clamp((lt - 1.2) / 0.35))
    cv.text((cx, sy0 + 200), "911"[:n] if n else " ", "interx", 96, WHITE)
    keys = "123456789*0#"
    for k, ch in enumerate(keys):
        r, c = divmod(k, 3)
        kx, ky = cx - 150 + c * 150, sy0 + 380 + r * 140
        hot = (ch == "9" and 0.5 <= lt < 0.7) or (ch == "1" and (0.85 <= lt < 1.05 or 1.2 <= lt < 1.4))
        cv.circ(kx, ky, 56, (70, 74, 96) if hot else (34, 36, 50))
        cv.text((kx, ky), ch, "inters", 50, WHITE)
    cv.circ(cx, sy1 - 120, 62, GREEN)
    cv.text((cx, sy1 - 120), "CALL", "mono", 24, (10, 40, 20))
    return (540, 900, 1.0)


def sc_burner(cv, t, lt, i):
    bg(cv, BLUE, 30)
    glow = 0.0 if t < chunk_t(7, 1) else 0.6 + 0.4 * math.sin(t * 12) ** 2
    box_open(cv, 540, 1020, 1.25, fill=1.0, burner=glow)
    if t >= chunk_t(7, 2):
        bubble(cv, 230, 500, "We see your light is on.", prog(t, chunk_t(7, 2), chunk_t(7, 2) + 0.35), who="UNKNOWN · BURNER", c=(48, 40, 58), size=52, maxw=700)
    z = lerp(1.0, 1.12, ease(prog(t, chunk_t(7, 1), chunk_t(7, 2))))
    return (lerp(540, 620, ease(prog(t, chunk_t(7, 1), chunk_t(7, 2)))), lerp(960, 900, ease(prog(t, chunk_t(7, 1), chunk_t(7, 2)))), z)


def sc_window(cv, t, lt, i):
    cv.rect(0, 0, W, H, (10, 10, 20))
    cv.rect(80, 0, 1000, 1150, (34, 30, 44))                 # building facade
    for r in range(4):
        for c in range(3):
            x0, y0 = 160 + c * 290, 140 + r * 270
            lit = (r, c) == (1, 1)
            cv.rect(x0, y0, x0 + 190, y0 + 190, (255, 214, 150) if lit else (20, 20, 30))
            if lit:
                cv.glow(x0 + 95, y0 + 95, 260, (255, 200, 130), 120)
    # you at the lit window (head and shoulders)
    you_stand(cv, 545, 690, s=0.42, eyes=True, look=0.0)
    cv.rect(440, 600, 650, 700, (34, 30, 44))                 # wall below the window hides his legs
    cv.rect(160 + 290, 140 + 270 + 150, 160 + 290 + 190, 140 + 270 + 190, (60, 50, 60))  # sill
    # street + car
    cv.rect(0, 1150, W, H, (16, 16, 24)); cv.rect(0, 1190, W, 1202, (40, 40, 56))
    car_x = 700
    cv.rrect(car_x - 230, 1290, car_x + 230, 1430, 40, (8, 8, 12))
    cv.rrect(car_x - 150, 1220, car_x + 120, 1310, 40, (8, 8, 12))
    cv.rrect(car_x - 130, 1235, car_x + 100, 1300, 30, (22, 26, 40))
    for wx in (car_x - 150, car_x + 150):
        cv.circ(wx, 1435, 48, (4, 4, 6))
    cv.rect(car_x - 236, 1330, car_x - 220, 1360, (200, 30, 40)); cv.glow(car_x - 230, 1345, 60, (220, 30, 40), 180)
    for k in range(4):                                       # exhaust puffs
        ph = (t * 0.6 + k * 0.25) % 1
        cv.circ(car_x - 260 - ph * 120, 1410 - ph * 40, 20 + ph * 40, (90, 90, 110, int(110 * (1 - ph))))
    cv.rect(930, 830, 944, 1190, (40, 40, 56)); cv.rect(860, 820, 944, 834, (40, 40, 56)); cv.rrect(840, 820, 900, 842, 8, (255, 210, 150))
    cv.glow_ell(800, 1290, 330, 200, (255, 190, 120), 70)
    u = ease(prog(t, chunk_t(8, 1), chunk_t(8, 2) + 0.4))
    return (lerp(540, 600, u), lerp(560, 1150, u), lerp(1.6, 1.3, u))


def sc_search(cv, t, lt, i):
    bg(cv, BLUE, 26)
    card(cv, 110, 480, 970, 600, c=(240, 238, 244), r=60, outline=(200, 196, 210))
    q = "daniel cross"
    n = int(len(q) * clamp((t - chunk_t(9, 1)) / 0.9))
    cv.circ(180, 540, 22, None, outline=(120, 116, 130), w=6); cv.line([(196, 556), (214, 574)], (120, 116, 130), 6)
    cv.text((240, 540), q[:n] + ("|" if int(t * 3) % 2 else ""), "inters", 46, INK, anchor="lm")
    cv.rrect(140, 650, 940, 1220, 24, None, outline=(50, 44, 60), w=2)
    if t > chunk_t(9, 2) + 0.2:
        for k in range(4):
            y = 700 + k * 130
            cv.rrect(180, y, 180 + 300 + (k * 97) % 300, y + 30, 8, (70, 64, 84))
            cv.rrect(180, y + 50, 860, y + 70, 6, (44, 40, 54))
    return (540, 900, 1.0)


def sc_missing(cv, t, lt, i):
    bg(cv, RED, 40)
    u = prog(t, chunk_t(10, 1), chunk_t(10, 1) + 0.45)
    if u <= 0:
        return sc_search(cv, t, lt, i)
    y0 = 380 + slide(u, 120)
    cv.rect(190, y0, 890, y0 + 980, (238, 234, 224))
    cv.text((540, y0 + 110), "MISSING", "anton", 150, (200, 30, 44))
    cv.rect(320, y0 + 210, 760, y0 + 640, (180, 176, 170))
    cv.circ(540, y0 + 340, 70, (120, 116, 112)); cv.rrect(440, y0 + 420, 640, y0 + 640, 40, (120, 116, 112))
    cv.text((540, y0 + 720), "DANIEL CROSS", "interx", 64, INK)
    cv.text((540, y0 + 800), "Age 31 · 5'10\"", "inters", 38, (90, 84, 90))
    if t >= chunk_t(10, 2):
        cv.rrect(250, y0 + 850, 830, y0 + 930, 14, (200, 30, 44))
        cv.text((540, y0 + 890), "LAST SEEN 3 DAYS AGO", "interx", 40, WHITE)
    return (540, lerp(900, 860, ease(prog(lt, 0, 5))), lerp(1.0, 1.06, prog(lt, 0, 5)))


def sc_reveal(cv, t, lt, i):
    cv.rect(0, 0, W, H, (12, 6, 10))
    pulse = 0.5 + 0.5 * math.sin(t * 3)
    cv.glow_ell(540, 1100, 700, 500, (200, 20, 40), int(60 + 50 * pulse))
    cv.rect(0, 1380, W, H, (20, 10, 14))
    you_sit(cv, 380, 900, eyes=True, look=0.7, pal=m35.HOODIE_PAL)
    cv.rrect(600, 1180, 900, 1390, 8, (120, 86, 52)); cv.rect(600, 1260, 900, 1280, (160, 130, 80))
    label_tag(cv, 750, 1240, 0.5)
    if t >= chunk_t(11, 2):
        q = eout(prog(t, chunk_t(11, 2), chunk_t(11, 2) + 0.4))
        cv.text((540, 520), "THEY THINK", "mono", 34, GREY)
        cv.text((540, 620), "YOU = DANIEL CROSS", "interx", 70, (int(lerp(244, 240, q)), int(lerp(242, 66, q)), int(lerp(248, 92, q))))
    return (540, 1000, lerp(1.0, 1.12, ease(prog(lt, 0, 5.5))))


def sc_garage(cv, t, lt, i):
    cv.rect(0, 0, W, H, (10, 8, 14))
    cv.glow_ell(540, 1500, 600, 300, RED, 40)
    cv.rrect(350, 980, 730, 1320, 30, (30, 12, 18), outline=(200, 30, 50), w=6)
    cv.text((540, 1150), "P −2", "anton", 190, (230, 50, 70)); cv.glow(540, 1150, 240, (220, 30, 50), 90)
    y = 360
    y = bubble(cv, 140, y, "Parking garage.", prog(t, chunk_t(12, 1), chunk_t(12, 1) + 0.3), who="UNKNOWN · BURNER", size=50)
    y = bubble(cv, 140, y, "Level −2. 6 AM.", prog(t, chunk_t(12, 1) + 0.9, chunk_t(12, 1) + 1.2), who="", size=50)
    bubble(cv, 140, y, "Come alone.", prog(t, chunk_t(12, 2) + 0.6, chunk_t(12, 2) + 0.9), who="", c=(90, 24, 36), size=50)
    return (540, 960, 1.0)


CHOICES = [("KEEP IT", "they come looking for it", 13), ("BRING IT", "you walk into an empty garage, alone", 14), ("CALL THE POLICE", "you explain why you opened it", 15)]


def sc_choices(cv, t, lt, i):
    bg(cv, RED, 30)
    for k, (a, b, li) in enumerate(CHOICES):
        t0 = LINES[li]["start"]
        u = prog(t, t0, t0 + 0.4)
        if u <= 0: continue
        y = 420 + k * 300 + slide(u)
        card(cv, 110, y, 970, y + 240)
        cv.text((160, y + 85), a, "interx", 60, WHITE, anchor="lm")
        cv.text((160, y + 165), b, "inters", 34, GREY, anchor="lm")
        xu = prog(t, chunk_t(li, 1), chunk_t(li, 1) + 0.25)
        if xu > 0:
            r = 48 * eout(xu)
            cv.circ(880, y + 120, r, (200, 30, 44))
            cv.line([(880 - r * 0.42, y + 120 - r * 0.42), (880 + r * 0.42, y + 120 + r * 0.42)], WHITE, 9)
            cv.line([(880 - r * 0.42, y + 120 + r * 0.42), (880 + r * 0.42, y + 120 - r * 0.42)], WHITE, 9)
    return (540, 960, 1.0)


def sc_final(cv, t, lt, i):
    bg(cv, BLUE, 30)
    cols = [(BLUE, "KEEP IT"), (AMBER, "BRING IT"), (RED, "CALL THE POLICE")]
    for k, (c, txt) in enumerate(cols):
        u = prog(lt, 0.9 + k * 0.4, 1.3 + k * 0.4)
        if u <= 0: continue
        p = 1 + 0.02 * math.sin(t * 4 + k)
        y = 560 + k * 220 + slide(u)
        w2, h2 = 380 * p, 78 * p
        cv.rrect(540 - w2, y - h2, 540 + w2, y + h2, h2, c)
        cv.glow_ell(540, y, w2, h2, c, 60)
        cv.text((540, y), txt, "interx", 62, (12, 10, 18))
    u = prog(t, LINES[16]["start"] + LINES[16]["dur"] + 0.3, LINES[16]["start"] + LINES[16]["dur"] + 0.8)
    if u > 0:
        cv.text((540, 1300 + slide(u, 30)), "Comment what you'd do", "interx", 56, WHITE)
    return (540, 960, 1.0)


SCENES = {"door": sc_door, "door2": sc_door, "cash": sc_cash, "note": sc_note, "spend": sc_spend, "report": sc_report,
          "dial": sc_dial, "burner": sc_burner, "window": sc_window, "search": sc_search, "missing": sc_missing,
          "reveal": sc_reveal, "garage": sc_garage, "keep": sc_choices, "bring": sc_choices, "police": sc_choices, "final": sc_final}


# ================================================================ the ending (lines 16-26)
DANIEL = m35.NEW_PAL


def small_box(cv, x, y, s=1.0):
    cv.rrect(x - 90 * s, y - 60 * s, x + 90 * s, y + 60 * s, 6 * s, (150, 112, 70))
    cv.rect(x - 90 * s, y - 8 * s, x + 90 * s, y + 8 * s, (200, 170, 110))


def garage_bg(cv, t, flick=True, flood=0.0):
    cv.rect(0, 0, W, H, (16, 16, 20))
    cv.rect(0, 1300, W, H, (30, 30, 34))
    for k in range(6):                                          # parking lines on the floor
        x = 40 + k * 210
        cv.poly([(x, 1300), (x + 14, 1300), (x - 40 + 14, H), (x - 40, H)], (70, 70, 60))
    for px in (120, 960):                                       # pillars
        cv.rect(px - 70, 250, px + 70, 1320, (44, 44, 50)); cv.rect(px - 70, 980, px + 70, 1060, (200, 170, 40))
        cv.text((px, 760), "P−2", "anton", 70, (190, 40, 50))
    for k, lx in enumerate((300, 780)):                         # fluorescent tubes
        on = 1.0 if not flick else (0.2 if hrand(int(t * 9) + k * 7, 4) < 0.16 else 1.0)
        cv.rrect(lx - 110, 370, lx + 110, 388, 8, (int(220 * on), int(235 * on), int(255 * on)))
        cv.glow_ell(lx, 400, 260, 140, (190, 210, 255), int(80 * on))
    if flood > 0:
        cv.glow_ell(0, 1000, 820 * flood, 400 * flood, (255, 250, 230), int(200 * flood))
        cv.circ(30, 1000, 46 * flood, (255, 255, 240)); cv.circ(30, 1140, 46 * flood, (255, 255, 240))


def sc_choose(cv, t, lt, i):
    bg(cv, BLUE, 30)
    pick = eout(prog(t, chunk_t(16, 2), chunk_t(16, 2) + 0.35))
    for k, (c, txt) in enumerate([(BLUE, "KEEP IT"), (AMBER, "BRING IT"), (RED, "CALL THE POLICE")]):
        sel = k == 1
        p = 1 + (0.08 * pick if sel else 0)
        y = 560 + k * 220
        cc = c if (sel or pick < 0.01) else tuple(int(v * (1 - 0.7 * pick) + 30 * 0.7 * pick) for v in c)
        w2, h2 = 380 * p, 78 * p
        cv.rrect(540 - w2, y - h2, 540 + w2, y + h2, h2, cc)
        if sel: cv.glow_ell(540, y, w2 * 1.1, h2 * 1.4, c, int(60 + 120 * pick))
        cv.text((540, y), txt, "interx", 62 * p, (12, 10, 18))
    return (540, 960, 1.0)


def sc_garage_in(cv, t, lt, i):
    garage_bg(cv, t)
    you_stand(cv, 540, 1330, s=0.9, eyes=True, look=0.0, hold=lambda hx, hy: small_box(cv, hx - 10, hy + 20, 0.9))
    return (540, 900, lerp(1.0, 1.12, ease(prog(lt, 0, 5))))


def sc_steps(cv, t, lt, i):
    garage_bg(cv, t)
    small_box(cv, 600, 1290, 1.0)
    turn = ease(prog(t, chunk_t(18, 1), chunk_t(18, 1) + 0.4))
    you_stand(cv, 420, 1330, s=0.9, eyes=True, look=lerp(0.3, 0.95, turn))
    if t > chunk_t(18, 1):                                      # a long shadow creeping in from the right
        u = ease(prog(t, chunk_t(18, 1), chunk_t(18, 2) + 0.8))
        man_shadow(cv, lerp(1250, 1020, u), 1330, 0.9, holds_phone=False, a=230)
    return (540, 950, lerp(1.0, 1.08, ease(prog(lt, 0, 4))))


def sc_daniel(cv, t, lt, i):
    garage_bg(cv, t)
    small_box(cv, 540, 1290, 1.0)
    you_stand(cv, 290, 1330, s=0.9, eyes=True, look=0.95)
    u = ease(prog(lt, 0.0, 1.6))
    you_stand(cv, lerp(1150, 790, u), 1330, s=0.92, eyes=True, look=-0.6, pal=DANIEL)
    if t >= chunk_t(19, 1):                                     # the poster, for comparison
        q = eout(prog(t, chunk_t(19, 1), chunk_t(19, 1) + 0.35))
        x0, y0 = 640, 380 + slide(q, 40)
        cv.rect(x0, y0, x0 + 330, y0 + 420, (238, 234, 224))
        cv.text((x0 + 165, y0 + 60), "MISSING", "anton", 60, (200, 30, 44))
        cv.rect(x0 + 75, y0 + 110, x0 + 255, y0 + 300, (180, 176, 170))
        cv.circ(x0 + 165, y0 + 170, 34, (120, 116, 112)); cv.rrect(x0 + 115, y0 + 210, x0 + 215, y0 + 300, 20, (120, 116, 112))
        cv.text((x0 + 165, y0 + 350), "DANIEL CROSS", "interx", 32, INK)
        if t >= chunk_t(19, 2):
            a = eout(prog(t, chunk_t(19, 2), chunk_t(19, 2) + 0.3))
            cv.rrect(x0 + 30, y0 + 160, x0 + 300, y0 + 240, 12, (40, 170, 90))
            cv.text((x0 + 165, y0 + 200), "ALIVE", "anton", 64 * (0.8 + 0.2 * a), WHITE)
    return (540, 960, 1.0)


def sc_daniel_says(cv, t, lt, i):
    garage_bg(cv, t)
    small_box(cv, 540, 1290, 1.0)
    you_stand(cv, 300, 1330, s=0.9, eyes=True, look=0.9)
    jit = math.sin(t * 13) * 3                                  # he's shaking
    you_stand(cv, 780 + jit, 1330, s=0.92, eyes=True, look=-0.8, pal=DANIEL)
    return (lerp(600, 680, ease(prog(lt, 0, 4))), 900, lerp(1.05, 1.25, ease(prog(lt, 0, 4))))


def sc_headlights(cv, t, lt, i):
    f = ease(prog(lt, 0.0, 0.5))
    garage_bg(cv, t, flick=False, flood=f)
    small_box(cv, 540, 1290, 1.0)
    you_stand(cv, 300, 1330, s=0.9, eyes=True, look=-0.9, arms_up=0.4 * f)
    you_stand(cv, 780, 1330, s=0.92, eyes=True, look=-0.9, pal=DANIEL, arms_up=0.6 * f)
    return (540 + math.sin(t * 40) * 4 * (lt < 0.6), 960, 1.0)


def sc_run(cv, t, lt, i):
    garage_bg(cv, t, flick=False, flood=1.0 - 0.6 * ease(prog(t, chunk_t(22, 2), chunk_t(22, 2) + 1.0)))
    you_stand(cv, 300, 1330, s=0.9, eyes=True, look=0.9)
    u = prog(lt, 0.3, 4.2)
    if u < 1:
        old = m35.HOODIE_PAL; m35.HOODIE_PAL = DANIEL
        dx = lerp(720, 1260, u)
        m35.you_run(cv, dx, 1330, t * 14, s=0.9)
        m35.HOODIE_PAL = old
        small_box(cv, dx + 130, 910, 0.7)
    else:
        pass
    if t >= chunk_t(22, 1):                                     # the car tears past after him
        cu = prog(t, chunk_t(22, 1), chunk_t(22, 1) + 1.6)
        cx = lerp(-500, 1700, ease(cu))
        cv.rrect(cx - 260, 1110, cx + 260, 1260, 40, (8, 8, 12)); cv.rrect(cx - 170, 1030, cx + 130, 1130, 40, (8, 8, 12))
        for wx in (cx - 170, cx + 170): cv.circ(wx, 1270, 54, (4, 4, 6))
        cv.glow(cx + 270, 1160, 200, (255, 250, 230), 200)
        for k in range(6):
            y = 1050 + k * 40; cv.line([(cx - 300 - 260 * hrand(k, 3), y), (cx - 300, y)], (120, 120, 140), 4)
    return (540, 960, 1.0)


def sc_burner_end(cv, t, lt, i):
    cv.rect(0, 0, W, H, (12, 10, 16))
    cv.glow_ell(540, 900, 500, 500, (120, 170, 255), int(70 + 40 * math.sin(t * 10) ** 2))
    cv.rrect(330, 520, 750, 1290, 40, (16, 16, 22)); cv.rrect(360, 560, 720, 960, 16, (150, 190, 255))
    for r in range(4):
        for c in range(3):
            cv.circ(420 + c * 120, 1030 + r * 62, 22, (50, 50, 60))
    cv.text((540, 610), "UNKNOWN", "mono", 26, (20, 30, 60))
    if t >= chunk_t(23, 1):
        q = prog(t, chunk_t(23, 1), chunk_t(23, 1) + 0.3)
        cv.rrect(385, 660 + slide(q, 20), 695, 900 + slide(q, 20), 16, (230, 236, 250))
        for k, w in enumerate(("Thank you", "for finding", "him.")):
            cv.text((410, 710 + k * 62 + slide(q, 20)), w, "interx", 44, INK, anchor="lm")
    shake = math.sin(t * 70) * 6 if lt < 1.2 else 0
    return (540 + shake, 900, lerp(1.0, 1.1, ease(prog(lt, 0, 4))))


def sc_realize(cv, t, lt, i):
    cv.rect(0, 0, W, H, (10, 6, 10))
    cv.glow_ell(540, 1300, 600, 400, (200, 20, 40), 60)
    cv.text((540, 560), "YOU DIDN'T DELIVER", "interx", 64, GREY)
    cv.text((540, 650), "THE MONEY.", "interx", 64, GREY)
    if t >= chunk_t(24, 1):
        q = eout(prog(t, chunk_t(24, 1), chunk_t(24, 1) + 0.4))
        cv.text((540, 820), "YOU DELIVERED", "anton", 120 * (0.9 + 0.1 * q), RED)
        cv.text((540, 950), "HIM.", "anton", 150 * (0.9 + 0.1 * q), RED); cv.glow(540, 880, 360, (220, 30, 50), int(80 * q))
    return (540, 960, 1.0)


def sc_mailbox(cv, t, lt, i):
    cv.rect(0, 0, W, H, (40, 46, 70)); cv.glow_ell(800, 300, 700, 500, (255, 200, 150), 70)
    cv.rect(0, 1350, W, H, (54, 50, 60))
    open_u = ease(prog(t, chunk_t(25, 2), chunk_t(25, 2) + 0.5))
    if open_u < 1:                                              # mailbox on the wall
        cv.rrect(330, 700, 750, 1000, 30, (70, 74, 96)); cv.rrect(370, 760, 710, 800, 10, (30, 30, 40))
        cv.rrect(420, 730 - 40 * ease(prog(lt, 0.4, 1.4)), 660, 790, 6, (236, 230, 214))
        cv.text((540, 900), "4B", "interx", 60, (200, 204, 230))
    if open_u > 0:                                              # the envelope: cash and a note
        y = 560 + slide(open_u, 80)
        cv.rrect(220, y, 860, y + 520, 20, (226, 214, 186))
        for k in range(4): cash_stack(cv, 360 + (k % 2) * 300, y + 130 + (k // 2) * 110, 240, 90)
        cv.text((540, y + 400), "$10,000", "interx", 90, (40, 120, 60))
        if t >= chunk_t(25, 4):
            nu = eout(prog(t, chunk_t(25, 4), chunk_t(25, 4) + 0.4))
            cv.rect(300, y + 600 + slide(nu, 40), 780, y + 760 + slide(nu, 40), PAPER)
            cv.text((540, y + 680 + slide(nu, 40)), "TELL NO ONE.", "anton", 80, (170, 30, 40))
    you_stand(cv, 150, 1650, s=0.6, eyes=True, look=0.8)
    return (540, 960, 1.0)


def sc_end(cv, t, lt, i):
    bg(cv, RED, 30)
    for k, (c, txt) in enumerate([(GREEN, "KEEP IT"), (RED, "GIVE IT BACK")]):
        u = prog(lt, 0.2 + k * 0.3, 0.6 + k * 0.3)
        if u <= 0: continue
        p = 1 + 0.02 * math.sin(t * 4 + k)
        y = 620 + k * 230 + slide(u)
        w2, h2 = 360 * p, 80 * p
        cv.rrect(540 - w2, y - h2, 540 + w2, y + h2, h2, c); cv.glow_ell(540, y, w2, h2, c, 60)
        cv.text((540, y), txt, "interx", 62, (12, 10, 18))
    u = prog(lt, 1.6, 2.1)
    if u > 0: cv.text((540, 1180 + slide(u, 30)), "Comment what you'd do", "interx", 56, WHITE)
    u = prog(lt, 2.6, 3.4)
    if u > 0: cv.text((540, 380), "THE END", "anton", 90, (200, 200, 214))
    return (540, 960, 1.0)


SCENES.update({"choose": sc_choose, "garage_in": sc_garage_in, "steps": sc_steps, "daniel": sc_daniel, "daniel_says": sc_daniel_says,
               "headlights": sc_headlights, "run": sc_run, "burner_end": sc_burner_end, "realize": sc_realize, "mailbox": sc_mailbox, "end": sc_end})
LABELS.update({"choose": "YOUR CALL", "garage_in": "6:00 AM · LEVEL −2", "steps": "6:00 AM · LEVEL −2", "daniel": "6:00 AM · LEVEL −2",
               "daniel_says": "6:00 AM · LEVEL −2", "headlights": "6:00 AM · LEVEL −2", "run": "6:00 AM · LEVEL −2",
               "mailbox": "THE NEXT MORNING", "end": "THE NEXT MORNING"})
LABELS.pop("final", None)
CLOCK += ["05:59", "06:00", "06:01", "06:02", "06:02", "06:03", "06:03", "06:05", "06:06", "08:40", "08:41"]
RISK[:] = RISK[:16] + [97, 97, 98, 99, 99, 100, 100, 60, 40, 20, 20, 20]


# ---------------------------------------------------------------- overlays
def draw_hud(img, t, i):
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([40, 44, 1040, 176], radius=18, fill=(24, 18, 28, 235))
    d.line([(40, 176), (1040, 176)], fill=RED + (200,), width=3)
    l = LINES[i]
    u = clamp((t - l["start"]) / max(0.1, l["dur"]))
    risk = lerp(RISK[i], RISK[min(i + 1, len(RISK) - 1)], u) if i < len(RISK) - 1 else 99
    for x, lab in ((80, "TIME"), (360, "CASH"), (640, "RISK")):
        d.text((x, 84), lab, font=F("inters", 22), fill=GREY, anchor="lm")
    d.text((80, 132), CLOCK[i], font=F("mono", 50), fill=WHITE, anchor="lm")
    c0 = chunk_t(2, 1)
    cash = 0 if t < c0 else (250000 if t > c0 + 0.9 else int(250000 * eout(prog(t, c0, c0 + 0.9))) // 1000 * 1000)
    if t >= chunk_t(22, 0) + 1.0: cash = 0
    if t >= chunk_t(25, 2): cash = 10000
    d.text((360, 132), "${:,}".format(cash), font=F("mono", 46), fill=AMBER, anchor="lm")
    risk = min(risk, 100)
    d.text((640, 132), f"{int(risk)}%", font=F("mono", 46), fill=RED, anchor="lm")
    d.rounded_rectangle([790, 122, 1000, 142], radius=10, fill=(60, 50, 66))
    d.rounded_rectangle([790, 122, 790 + max(20, 210 * risk / 100), 142], radius=10, fill=RED)


def draw_label(img, t, i):
    lab = LABELS.get(LINES[i]["scene"])
    if not lab: return
    first = i
    while first > 0 and LABELS.get(LINES[first - 1]["scene"]) == lab: first -= 1
    a = clamp((t - LINES[first]["start"] + 0.3) / 0.3)
    d = ImageDraw.Draw(img, "RGBA")
    f = F("mono", 32)
    d.text((540, 262), lab, font=f, fill=RED + (int(255 * a),), anchor="mm")
    w = f.getlength(lab)
    d.line([(540 - w / 2, 290), (540 + w / 2, 290)], fill=RED + (int(160 * a),), width=3)


def parse(ch):
    out, cur = [], None
    for w in ch.split():
        if cur is None and w.lstrip('"')[:1] in "*_":
            cur = RED if w.lstrip('"')[0] == "*" else BLUE
        col = cur or WHITE
        core = w.rstrip('.,?…!"')
        if cur is not None and len(core) > 1 and core[-1] in "*_":
            cur = None
        out.append((w.replace("*", "").replace("_", ""), col))
    return out


def draw_caption(img, t):
    cur = None
    for l in LINES:
        for k, (c0, c1, cap) in enumerate(l["chunks"]):
            end = l["chunks"][k + 1][0] if k + 1 < len(l["chunks"]) else l["start"] + l["dur"] + 0.35
            if c0 - 0.04 <= t < end and cap:
                cur = (cap, c0)
    if not cur: return
    cap, c0 = cur
    words = parse(cap)
    f = F("interx", 66)
    lines, line, wl = [], [], 0
    for w, c in words:
        ww = f.getlength(w + " ")
        if wl + ww > 900 and line:
            lines.append(line); line, wl = [], 0
        line.append((w, c)); wl += ww
    lines.append(line)
    d = ImageDraw.Draw(img, "RGBA")
    a = clamp((t - c0 + 0.04) / 0.08)
    sc = 1 + 0.06 * (1 - eout(clamp((t - c0) / 0.15)))
    fs = F("interx", int(66 * sc))
    for li, ln in enumerate(lines):
        tot = sum(fs.getlength(w + " ") for w, _ in ln) - fs.getlength(" ")
        x = 540 - tot / 2; y = 1500 + li * 82 - (len(lines) - 1) * 41
        for w, c in ln:
            d.text((x + 3, y + 4), w, font=fs, fill=(0, 0, 0, int(170 * a)), anchor="lm")
            d.text((x, y), w, font=fs, fill=c + (int(255 * a),), anchor="lm")
            x += fs.getlength(w + " ")


def frame(t):
    i = line_at(t)
    l = LINES[i]
    lt = t - l["start"]
    cv = Cv(BG)
    cam = SCENES[l["scene"]](cv, t, lt, i)
    # punch-in on every scene change
    if lt < 0.25 and l["scene"] not in ("door2", "bring", "police", "steps", "daniel", "daniel_says", "headlights", "run"):
        cx, cy, z = cam; cam = (cx, cy, z * (1 + 0.05 * (1 - eout(lt / 0.25))))
    img = camera(cv, *cam)
    img = post(img, t)
    draw_hud(img, t, i)
    draw_label(img, t, i)
    draw_caption(img, t)
    if t < 0.5: img = Image.blend(Image.new("RGB", (W, H)), img, t / 0.5)
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
