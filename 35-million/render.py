"""35 MILLION — frame renderer. Reuses the drawing toolkit from ../last-bus/render.py.

usage: python render.py <start_frame> <end_frame> <out.mp4>
       python render.py --still <t> <out.png>
"""
import importlib.util, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("lb", os.path.join(HERE, "..", "last-bus", "render.py"))
lb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lb)

Cv, camera, to_screen, F = lb.Cv, lb.camera, lb.to_screen, lb.F
clamp, lerp, ease, eout, prog, mix, hrand = lb.clamp, lb.lerp, lb.ease, lb.eout, lb.prog, lb.mix, lb.hrand
draw_led, led_width, rain, glass_drops, gradient = lb.draw_led, lb.led_width, lb.rain, lb.glass_drops, lb.gradient
skyline_strip, paste_strip, stars = lb.skyline_strip, lb.paste_strip, lb.stars
post, chroma, flash, vhs, tilt_img, spaced, emoji, wrap = lb.post, lb.chroma, lb.flash, lb.vhs, lb.tilt_img, lb.spaced, lb.emoji, lb.wrap
parse_chunk = lb.parse_chunk
HOODIE, HOODIE_D, JOG, JOG_RIM = lb.HOODIE, lb.HOODIE_D, lb.JOG, lb.JOG_RIM
W, H, FPS, SS = lb.W, lb.H, lb.FPS, lb.SS
DUR = 92.0
SCR = lb.SCR

NAVY0, WHITE, RED, LIME, BLUE, ORANGE, BLACK = lb.NAVY0, lb.WHITE, lb.RED, lb.LIME, lb.BLUE, lb.ORANGE, lb.BLACK
GREEN = (61, 220, 132)          # money green #3DDC84
COP_R = (235, 30, 45)
COP_B = (40, 90, 255)
BULB = (255, 232, 180)          # weak bedsit bulb
SODIUM = (205, 220, 255)        # cold streetlight
GREY_B = (62, 64, 78)           # message bubble


# ================================================================ characters
def hoodie_body(cv, head, neck, hip, arms, legs, eyes=False, look=0.0, side=False, s=1.0):
    """main character (same as The Last Bus): white stick figure, red hoodie, black joggers.
    arms/legs: lists of joint lists [(x,y),...]; drawn back-to-front by list order."""
    hx, hy = head
    r = 60 * s
    # hood behind head
    if side:
        cv.ell(hx - 30 * s, hy + 30 * s, 62 * s, 58 * s, HOODIE_D)
    else:
        cv.ell(hx, hy + 34 * s, 82 * s, 66 * s, HOODIE_D)
    for leg in legs:
        cv.line(leg, JOG_RIM, 42 * s)
        cv.line(leg, JOG, 36 * s)
        fx, fy = leg[-1]
        dirx = 1 if (side or fx >= hip[0]) else -1
        cv.line([(fx - 4 * s * dirx, fy + 8 * s), (fx + 34 * s * dirx, fy + 10 * s)], WHITE, 18 * s)
    # torso
    nx, ny = neck
    px, py = hip
    wn, wh = (40 if side else 58) * s, (44 if side else 66) * s
    dx, dy = px - nx, py - ny
    ln = math.hypot(dx, dy) or 1
    ox, oy = -dy / ln, dx / ln
    body = [(nx + ox * wn, ny + oy * wn), (nx - ox * wn, ny - oy * wn), (px - ox * wh, py - oy * wh), (px + ox * wh, py + oy * wh)]
    cv.poly(body, HOODIE)
    if not side:
        cv.rrect(px - 66 * s, py - 6 * s, px + 66 * s, py + 22 * s, 8 * s, HOODIE_D)
        cv.rrect(px - 44 * s, py - 100 * s, px + 44 * s, py - 30 * s, 14 * s, HOODIE_D)
        cv.ell(nx, ny + 10 * s, 36 * s, 18 * s, HOODIE_D)
        for ddx in (-12, 12):
            cv.line([(nx + ddx * s, ny + 16 * s), (nx + ddx * 1.2 * s, ny + 80 * s)], WHITE, 4 * s)
    for arm in arms:
        cv.line(arm, HOODIE_D, 40 * s)
        cv.line(arm, HOODIE, 34 * s)
        ax, ay = arm[-1]
        cv.circ(ax, ay, 13 * s, WHITE)
    rx = r * (1 - 0.06 * abs(look))
    cv.ell(hx, hy, rx, r, WHITE)
    if eyes:
        ex = look * 28 * s
        for ddx in ((8, 30) if side else (-19, 19)):
            cv.circ(hx + ddx * s + ex, hy - 6 * s, 7.5 * s, NAVY0)


def you_stand(cv, x, fy, s=1.0, eyes=True, look=0.0, arms_up=0.0, hold=None):
    """front-facing standing. arms_up 0..1 (startled). hold: callback(hand_x, hand_y) for an item in right hand"""
    hip = (x, fy - 300 * s)
    neck = (x, hip[1] - 290 * s)
    head = (x, neck[1] - 60 * s)
    legs = [[(x - 14 * s, hip[1]), (x - 44 * s, fy - 150 * s), (x - 58 * s, fy)],
            [(x + 14 * s, hip[1]), (x + 44 * s, fy - 150 * s), (x + 58 * s, fy)]]
    sh = neck[1] + 30 * s
    arms = []
    for sg in (-1, 1):
        down = [(x + sg * 50 * s, sh), (x + sg * 82 * s, sh + 140 * s), (x + sg * 86 * s, sh + 270 * s)]
        up = [(x + sg * 50 * s, sh), (x + sg * 130 * s, sh - 30 * s), (x + sg * 150 * s, sh - 150 * s)]
        u = arms_up
        arms.append([(lerp(a[0], b[0], u), lerp(a[1], b[1], u)) for a, b in zip(down, up)])
    if hold:
        arms[1] = [(x + 50 * s, sh), (x + 110 * s, sh + 100 * s), (x + 170 * s, sh + 60 * s)]
    hoodie_body(cv, head, neck, hip, arms, legs, eyes=eyes, look=look, s=s)
    if hold:
        hold(*arms[1][-1])


def you_run(cv, x, fy, ph, s=1.0, eyes=True):
    """side view running to the right; ph = run phase (radians)"""
    bob = -abs(math.sin(ph)) * 18 * s
    hip = (x, fy - 290 * s + bob)
    neck = (x + 70 * s, hip[1] - 280 * s)
    head = (x + 96 * s, neck[1] - 58 * s)
    legs, arms = [], []
    for k in (0, 1):
        p = ph + k * math.pi
        a = 0.95 * math.sin(p)
        knee = (hip[0] + 150 * s * math.sin(a), hip[1] + 150 * s * math.cos(a))
        b = 0.25 + 1.1 * (0.5 + 0.5 * math.sin(p - 1.3))
        foot = (knee[0] + 150 * s * math.sin(a - b), knee[1] + 150 * s * math.cos(a - b))
        legs.append([hip, knee, foot])
        sa = -0.9 * math.sin(p)
        sh = (neck[0] - 6 * s, neck[1] + 30 * s)
        el = (sh[0] + 120 * s * math.sin(sa), sh[1] + 120 * s * math.cos(sa))
        hd = (el[0] + 110 * s * math.sin(sa + 1.5), el[1] + 110 * s * math.cos(sa + 1.5))
        arms.append([sh, el, hd])
    # far limbs first
    hoodie_body(cv, head, neck, hip, arms, legs, eyes=eyes, side=True, s=s)


def you_sit(cv, x, head_y, eyes=False, look=0.0):
    lb.you_seated(cv, x, head_y, eyes=eyes, look=look)


SUIT = (18, 20, 32)
SUIT_RIM = (70, 74, 120)
SKIN = (214, 214, 226)


def suit_man(cv, x, fy, s=1.0, badge_up=0.0, phone=False, shades=True, fbi_back=False, color=SUIT, rim=SUIT_RIM):
    """faceless man in a dark suit (front view). badge_up 0..1 raises right hand with badge."""
    hip = (x, fy - 310 * s)
    neck = (x, hip[1] - 300 * s)
    head = (x, neck[1] - 64 * s)
    for sg in (-1, 1):   # trousers
        leg = [(x + sg * 22 * s, hip[1]), (x + sg * 40 * s, fy - 150 * s), (x + sg * 46 * s, fy)]
        cv.line(leg, rim, 46 * s)
        cv.line(leg, color, 40 * s)
        cv.line([(x + sg * 40 * s, fy + 6 * s), (x + sg * 76 * s, fy + 8 * s)], (8, 8, 12), 18 * s)
    jacket = [(x - 74 * s, neck[1] + 6 * s), (x + 74 * s, neck[1] + 6 * s), (x + 80 * s, hip[1] + 40 * s), (x - 80 * s, hip[1] + 40 * s)]
    cv.poly([(px + (3 if px > x else -3), py) for px, py in jacket], rim)
    cv.poly(jacket, color)
    if fbi_back:
        cv.text((x, neck[1] + 120 * s), "FBI", "anton", 70 * s, (240, 240, 245))
    else:
        cv.poly([(x - 30 * s, neck[1] + 6 * s), (x + 30 * s, neck[1] + 6 * s), (x, neck[1] + 120 * s)], (232, 232, 240))
        cv.poly([(x - 8 * s, neck[1] + 14 * s), (x + 8 * s, neck[1] + 14 * s), (x + 10 * s, neck[1] + 110 * s), (x, neck[1] + 124 * s), (x - 10 * s, neck[1] + 110 * s)], (12, 12, 18))
    sh = neck[1] + 30 * s
    # left arm down
    cv.line([(x - 66 * s, sh), (x - 90 * s, sh + 150 * s), (x - 86 * s, sh + 280 * s)], rim, 38 * s)
    cv.line([(x - 66 * s, sh), (x - 90 * s, sh + 150 * s), (x - 86 * s, sh + 280 * s)], color, 32 * s)
    cv.circ(x - 86 * s, sh + 290 * s, 14 * s, SKIN)
    # right arm (raises)
    u = badge_up
    el = (lerp(x + 90 * s, x + 150 * s, u), lerp(sh + 150 * s, sh + 20 * s, u))
    hd = (lerp(x + 86 * s, x + 170 * s, u), lerp(sh + 280 * s, sh - 130 * s, u))
    cv.line([(x + 66 * s, sh), el, hd], rim, 38 * s)
    cv.line([(x + 66 * s, sh), el, hd], color, 32 * s)
    if u > 0.3 and not phone:
        bx, by = hd[0], hd[1] - 40 * s
        shield = [(bx - 40 * s, by - 50 * s), (bx + 40 * s, by - 50 * s), (bx + 40 * s, by + 10 * s), (bx, by + 52 * s), (bx - 40 * s, by + 10 * s)]
        cv.poly(shield, (200, 204, 220))
        cv.poly([(px * 0.8 + bx * 0.2, py * 0.8 + by * 0.2) for px, py in shield], (150, 156, 180))
        cv.text((bx, by - 6 * s), "FBI", "interx", 22 * s, (30, 32, 50))
        cv.glow(bx, by, 70 * s, (200, 210, 255), 70)
    if u > 0.3 and phone:
        cv.rrect(hd[0] - 26 * s, hd[1] - 100 * s, hd[0] + 26 * s, hd[1] - 4 * s, 8 * s, (10, 10, 14))
        cv.rrect(hd[0] - 20 * s, hd[1] - 94 * s, hd[0] + 20 * s, hd[1] - 12 * s, 5 * s, GREEN + (90,))
        cv.glow(hd[0], hd[1] - 52 * s, 50 * s, GREEN, 120)
    cv.circ(hd[0], hd[1], 14 * s, SKIN)
    cv.ell(x, head[1], 58 * s, 64 * s, SKIN)
    if shades:
        cv.rrect(x - 46 * s, head[1] - 18 * s, x + 46 * s, head[1] + 4 * s, 8 * s, (8, 8, 12))


def man_shadow(cv, x, fy, s, holds_phone=True, a=200):
    """shadow silhouette on a wall; raised hand holds a phone (not a badge)"""
    c = (4, 4, 10, a)
    hip_y = fy - 310 * s
    neck_y = hip_y - 300 * s
    cv.ell(x, neck_y - 64 * s, 58 * s, 64 * s, c)
    cv.poly([(x - 76 * s, neck_y), (x + 76 * s, neck_y), (x + 82 * s, hip_y + 40 * s), (x - 82 * s, hip_y + 40 * s)], c)
    for sg in (-1, 1):
        cv.line([(x + sg * 22 * s, hip_y), (x + sg * 46 * s, fy)], c, 42 * s)
    sh = neck_y + 30 * s
    cv.line([(x - 66 * s, sh), (x - 90 * s, sh + 150 * s), (x - 86 * s, sh + 280 * s)], c, 34 * s)
    hd = (x + 170 * s, sh - 130 * s)
    cv.line([(x + 66 * s, sh), (x + 150 * s, sh + 20 * s), hd], c, 34 * s)
    if holds_phone:
        cv.rrect(hd[0] - 26 * s, hd[1] - 104 * s, hd[0] + 26 * s, hd[1], 8 * s, c)


# ================================================================ phone + apps
def phone_frame(cv, x0, y0, w, h):
    cv.rrect(x0 - 6, y0 - 6, x0 + w + 6, y0 + h + 6, 70, (70, 74, 110))
    cv.rrect(x0, y0, x0 + w, y0 + h, 64, (10, 10, 16))
    sx0, sy0, sx1, sy1 = x0 + 22, y0 + 22, x0 + w - 22, y0 + h - 22
    cv.rrect(sx0, sy0, sx1, sy1, 48, (14, 16, 26))
    cv.rrect((x0 + x0 + w) / 2 - 60, sy0 + 14, (x0 + x0 + w) / 2 + 60, sy0 + 46, 16, (4, 4, 8))   # notch
    return sx0, sy0, sx1, sy1


def money_str(v):
    return "${:,.2f}".format(v)


BAL_T0, BAL_T1 = 10.9, 13.0
TARGET = "$35,000,003.12"


def balance_text(t):
    """slot-machine roll from $3.12 to $35,000,003.12"""
    if t < BAL_T0:
        return "$3.12", False
    if t >= BAL_T1:
        return TARGET, True
    u = (t - BAL_T0) / (BAL_T1 - BAL_T0)
    out = []
    n = len(TARGET)
    for i, ch in enumerate(TARGET):
        settle = 0.25 + 0.75 * i / n
        if ch.isdigit() and u < settle:
            out.append(str(int(hrand(i, int(t * 40)) * 10)))
        else:
            out.append(ch)
    return "".join(out), False


def northpay_screen(cv, box, t, banner=0.0):
    sx0, sy0, sx1, sy1 = box
    cx = (sx0 + sx1) / 2
    cv.rrect(sx0, sy0, sx1, sy0 + 230, 48, (16, 60, 44))
    cv.rect(sx0, sy0 + 180, sx1, sy0 + 230, (16, 60, 44))
    cv.circ(sx0 + 80, sy0 + 140, 30, GREEN)
    cv.text((sx0 + 80, sy0 + 141), "N", "interx", 34, (10, 40, 26))
    cv.text((sx0 + 126, sy0 + 140), "NorthPay", "interx", 40, (230, 255, 240), anchor="lm")
    cv.text((cx, sy0 + 300), "AVAILABLE BALANCE", "inters", 24, (140, 146, 170), spacing=4)
    bal, done = balance_text(t)
    size = 120 if len(bal) < 8 else 66
    cv.text((cx, sy0 + 400), bal, "interx", size, GREEN if done else WHITE)
    cv.text((cx, sy0 + 480), "Checking  ••4417", "inters", 26, (120, 126, 150))
    rows = [("Noodles", "-$1.29"), ("Bus fare", "-$2.75"), ("Laundry", "-$4.00")]
    if t >= BAL_T0:
        rows = [("Transfer", "+$35,000,000.00")] + rows[:2]
    for i, (a, b) in enumerate(rows):
        y = sy0 + 580 + i * 110
        cv.rrect(sx0 + 30, y, sx1 - 30, y + 90, 20, (24, 26, 40))
        cv.text((sx0 + 60, y + 45), a, "inters", 28, (210, 212, 230), anchor="lm")
        cv.text((sx1 - 60, y + 45), b, "interx", 28, GREEN if b.startswith("+") else (200, 120, 120), anchor="rm")
    if banner > 0:
        by = sy0 + 60 - 260 * (1 - eout(banner))
        cv.rrect(sx0 + 18, by, sx1 - 18, by + 170, 30, (40, 44, 62))
        cv.circ(sx0 + 76, by + 60, 26, GREEN)
        cv.text((sx0 + 76, by + 61), "N", "interx", 28, (10, 40, 26))
        cv.text((sx0 + 116, by + 50), "NorthPay", "interx", 28, WHITE, anchor="lm")
        cv.text((sx1 - 50, by + 50), "now", "inters", 22, (150, 154, 180), anchor="rm")
        cv.text((sx0 + 50, by + 112), "Incoming transfer", "inters", 28, (220, 222, 236), anchor="lm")
        cv.text((sx0 + 50, by + 146), "+$35,000,000.00", "interx", 30, GREEN, anchor="lm")


MSGS = [(20.1, "Don't touch it."), (21.2, "Don't call the bank."), (22.4, "They're already coming."), (23.4, "3 rules.")]


def messages_screen(cv, box, t):
    sx0, sy0, sx1, sy1 = box
    cx = (sx0 + sx1) / 2
    cv.rect(sx0, sy0 + 60, sx1, sy0 + 200, (20, 22, 34))
    cv.circ(cx, sy0 + 112, 34, (70, 72, 90))
    cv.text((cx, sy0 + 114), "?", "interx", 38, (200, 200, 215))
    cv.text((cx, sy0 + 176), "Unknown number", "inters", 26, (200, 202, 220))
    y = sy0 + 260
    shown = [m for m in MSGS if t >= m[0]]
    f = F("inters", 34 * SS)
    for t0, txt in shown:
        p = eout((t - t0) / 0.2)
        tw = f.getlength(txt) / SS
        bw = tw + 60
        x0 = sx0 + 30
        yy = y + 30 * (1 - p)
        cv.rrect(x0, yy, x0 + bw * (0.7 + 0.3 * p), yy + 84, 34, GREY_B)
        if p > 0.6:
            col = RED if txt == "3 rules." else WHITE
            cv.text((x0 + 30, yy + 42), txt, "inters", 34, col, anchor="lm")
        y += 108
    # typing indicator before each new message
    nxt = [m for m in MSGS if m[0] > t]
    if nxt and nxt[0][0] - t < 0.9 and t > 19.0:
        x0 = sx0 + 30
        cv.rrect(x0, y, x0 + 130, y + 70, 34, GREY_B)
        for k in range(3):
            a = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 9 - k))
            cv.circ(x0 + 38 + k * 28, y + 35, 9, mix(GREY_B, WHITE, a))
    cv.rrect(sx0 + 24, sy1 - 110, sx1 - 24, sy1 - 40, 34, (26, 28, 42))
    cv.text((sx0 + 60, sy1 - 75), "Text message", "inters", 26, (100, 104, 130), anchor="lm")


def map_screen(cv, box, t):
    sx0, sy0, sx1, sy1 = box
    cv.rect(sx0, sy0 + 50, sx1, sy1 - 40, (22, 26, 44))
    for i in range(-2, 12):     # streets
        x = sx0 + i * 120 + 40
        cv.line([(x, sy0 + 50), (x + 200, sy1 - 40)], (44, 50, 80), 18, caps=False)
    for j in range(0, 10):
        y = sy0 + 120 + j * 150
        cv.line([(sx0, y), (sx1, y + 60)], (44, 50, 80), 14, caps=False)
    cx, cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
    cv.rect(cx - 70, cy - 40, cx + 70, cy + 60, (60, 66, 110))     # your building
    pulse = (t * 1.6) % 1.0
    cv.circ(cx, cy + 10, 40 + 160 * pulse, None, outline=RED + (int(220 * (1 - pulse)),), w=6)
    blink = (int(t * 3) % 2) == 0
    pc = RED if blink else (150, 20, 30)
    cv.circ(cx, cy - 90, 46, pc)
    cv.poly([(cx - 34, cy - 66), (cx + 34, cy - 66), (cx, cy + 4)], pc)
    cv.circ(cx, cy - 92, 18, (250, 240, 240))
    cv.glow(cx, cy - 70, 140, COP_R, 170 if blink else 60)
    cv.rrect(sx0 + 30, sy0 + 70, sx1 - 30, sy0 + 160, 24, (14, 16, 26, 230))
    cv.text((sx0 + 60, sy0 + 115), "Location shared  •  LIVE", "interx", 26, RED, anchor="lm")


# ================================================================ scenes
def bedsit(cv, t, fig="sit", bulb_flick=1.0, tv=None, phone_glow=0.0, wash=0.0, steam=True, eyes=False, look=0.0,
           noodles=None, phone_on_table=True, figure_x=520):
    cv.rect(0, 0, W, H, (24, 26, 60))
    for i in range(0, W, 90):   # tired wallpaper stripes
        cv.rect(i, 0, i + 6, 1460, (28, 30, 66))
    cv.rect(0, 0, W, 90, (16, 18, 44))
    # damp patch
    cv.ell(180, 330, 120, 70, (30, 32, 66))
    # window with rain + city
    WX0, WY0, WX1, WY1 = 640, 360, 980, 880
    cv.rect(WX0 - 18, WY0 - 18, WX1 + 18, WY1 + 18, (40, 44, 92))
    cv.im.paste(gradient(WX1 - WX0, WY1 - WY0, (6, 8, 26), (26, 26, 70), "bsky"), (WX0 * SS, WY0 * SS))
    for i in range(8):
        bx = WX0 + i * 44
        bh = 120 + hrand(i, 81) * 260
        cv.rect(bx, WY1 - bh, bx + 40, WY1, (12, 14, 38))
        for wy in range(int(WY1 - bh + 16), WY1 - 10, 30):
            if hrand(i * 31 + wy, 82) > 0.7:
                cv.rect(bx + 12, wy, bx + 20, wy + 10, (110, 120, 150))
    rain(cv, t, (WX0, WY0, WX1, WY1), alpha=70, n=110, slant=0.1)
    glass_drops(cv, t, (WX0, WY0, WX1, WY1), n=26)
    cv.rect(WX0 + (WX1 - WX0) / 2 - 6, WY0, WX0 + (WX1 - WX0) / 2 + 6, WY1, (40, 44, 92))
    cv.rect(WX0, WY0 + (WY1 - WY0) / 2 - 6, WX1, WY0 + (WY1 - WY0) / 2 + 6, (40, 44, 92))
    if wash > 0:
        ph = (t * 2.6) % 1.0
        col = COP_R if ph < 0.5 else COP_B
        a = math.sin((ph % 0.5) / 0.5 * math.pi)
        cv.rect(WX0, WY0, WX1, WY1, col + (int(150 * wash * a),))
        cv.glow_poly([(WX0, WY0), (WX1, WY0), (WX1 - 300, 1460), (WX0 - 600, 1460)], col, int(170 * wash * a))
        cv.rect(0, 0, W, H, col + (int(30 * wash * a),))
    # floor
    cv.rect(0, 1460, W, H, (16, 17, 40))
    for k in range(7):
        cv.rect(0, 1500 + k * 64, W, 1503 + k * 64, (22, 23, 50))
    # mattress on the floor
    cv.rrect(30, 1370, 380, 1470, 20, (60, 64, 104))
    cv.rrect(50, 1340, 170, 1390, 18, (86, 90, 130))
    # old CRT tv on a crate
    cv.rect(780, 1300, 1040, 1460, (50, 40, 46))
    cv.rect(790, 1310, 1030, 1316, (64, 52, 58))
    cv.rrect(770, 1050, 1050, 1300, 22, (60, 62, 82))
    cv.rrect(796, 1076, 990, 1274, 30, (18, 22, 30))
    cv.circ(1020, 1120, 10, (40, 42, 60))
    cv.circ(1020, 1160, 10, (40, 42, 60))
    cv.line([(860, 1050), (820, 960)], (90, 92, 120), 4)
    cv.line([(920, 1050), (970, 970)], (90, 92, 120), 4)
    if tv:
        tv(cv, (796, 1076, 990, 1274))
    # figure behind the table
    if fig == "sit":
        you_sit(cv, figure_x, 880, eyes=eyes, look=look)
    elif fig == "stand":
        you_stand(cv, figure_x, 1460, eyes=True, look=look, arms_up=noodles.get("arms", 0) if noodles else 0,
                  hold=noodles.get("hold") if noodles else None)
    # table
    cv.rect(300, 1180, 740, 1206, (64, 52, 62))
    cv.rect(320, 1206, 336, 1460, (50, 40, 50))
    cv.rect(704, 1206, 720, 1460, (50, 40, 50))
    if fig == "sit":
        cup(cv, 430, 1180, t, steam)
    if phone_on_table:
        cv.poly([(560, 1182), (690, 1182), (700, 1172), (570, 1172)], (14, 14, 20))
        if phone_glow > 0:
            cv.poly([(575, 1180), (685, 1180), (694, 1173), (580, 1173)], mix((14, 14, 20), (200, 255, 220), phone_glow))
            cv.glow(630, 1170, 90, GREEN, int(160 * phone_glow))
    # single bulb
    cv.line([(480, 0), (480, 300)], (10, 10, 20), 4, caps=False)
    cv.rect(468, 296, 492, 318, (40, 40, 50))
    b = bulb_flick
    cv.circ(480, 336, 24, mix((60, 56, 50), BULB, b))
    cv.glow(480, 340, 190, BULB, int(110 * b))
    cv.glow(480, 340, 70, BULB, int(200 * b))
    cv.poly([(470, 340), (490, 340), (900, 1460), (60, 1460)], BULB + (int(16 * b),))


def cup(cv, x, base_y, t, steam=True, ang=0.0):
    """instant noodle pot. x = centre, base_y = bottom"""
    if ang == 0:
        cv.poly([(x - 52, base_y - 120), (x + 52, base_y - 120), (x + 40, base_y), (x - 40, base_y)], (232, 232, 240))
        cv.rect(x - 49, base_y - 86, x + 49, base_y - 56, RED)
        cv.ell(x, base_y - 120, 52, 12, (250, 236, 200))
        for k in range(4):
            cv.line([(x - 30 + k * 18, base_y - 124), (x - 26 + k * 18, base_y - 112)], (220, 200, 140), 4, caps=False)
        if steam:
            for k in range(3):
                ph = (t * 0.6 + k / 3) % 1
                pts = [(x - 20 + k * 20 + 12 * math.sin(ph * 8 + i * 0.8), base_y - 140 - ph * 160 - i * 20) for i in range(5)]
                cv.line(pts, (220, 220, 240, int(90 * (1 - ph))), 6)
    else:
        ca, sa = math.cos(ang), math.sin(ang)
        def R(px, py):
            return (x + px * ca - py * sa, base_y + px * sa + py * ca)
        cv.poly([R(-52, -120), R(52, -120), R(40, 0), R(-40, 0)], (232, 232, 240))
        cv.poly([R(-49, -86), R(49, -86), R(49, -56), R(-49, -56)], RED)


def tv_off(cv, box):
    pass


def tv_news(t0):
    def fn(cv, box, t=None):
        x0, y0, x1, y1 = box
        cv.rect(x0, y0, x1, y1, (24, 28, 50))
        cv.rect(x0, y0, x1, y0 + 34, RED)
        cv.text((x0 + 8, y0 + 17), "BREAKING NEWS", "interx", 18, WHITE, anchor="lm")
        cv.rrect(x0 + 16, y0 + 46, x0 + 98, y0 + 150, 6, (40, 46, 80))
        cv.ell(x0 + 57, y0 + 112, 34, 26, HOODIE_D)
        cv.circ(x0 + 57, y0 + 92, 26, WHITE)
        cv.circ(x0 + 49, y0 + 90, 3.5, NAVY0)
        cv.circ(x0 + 65, y0 + 90, 3.5, NAVY0)
        cv.text((x0 + 146, y0 + 70), "WANTED", "anton", 30, RED)
        cv.text((x0 + 146, y0 + 106), "$35M", "anton", 30, WHITE)
        cv.text((x0 + 146, y0 + 138), "BANK FRAUD", "interx", 14, WHITE)
        cv.rect(x0, y1 - 30, x1, y1, (10, 12, 22))
        cv.text((x0 + 8, y1 - 15), "FBI SEEKING SUSPECT  •  ROUTE 9 DISTRICT", "interx", 12, (220, 220, 230), anchor="lm")
        for yy in range(int(y0), int(y1), 6):
            cv.rect(x0, yy, x1, yy + 2, (0, 0, 0, 50))
        cv.glow_rect(x0, y0, x1, y1, (150, 160, 255), 90)
    return fn


def tv_full_news(cv, t):
    """the news broadcast filling the frame (close-up on the TV)"""
    cv.rect(0, 0, W, H, (30, 34, 60))
    cv.rrect(40, 420, 1040, 1300, 40, (60, 62, 82))
    x0, y0, x1, y1 = 90, 470, 990, 1250
    cv.rrect(x0, y0, x1, y1, 50, (22, 26, 48))
    cv.rect(x0, y0 + 30, x1, y0 + 130, RED)
    cv.text((x0 + 40, y0 + 80), "BREAKING NEWS", "anton", 64, WHITE, anchor="lm")
    blink = int(t * 2) % 2 == 0
    cv.circ(x1 - 70, y0 + 80, 16, WHITE if blink else (120, 20, 30))
    # mugshot
    cv.rrect(x0 + 50, y0 + 170, x0 + 400, y0 + 600, 18, (44, 50, 88))
    for k in range(6):
        cv.rect(x0 + 50, y0 + 200 + k * 70, x0 + 400, y0 + 203 + k * 70, (60, 66, 110))
    cv.ell(x0 + 225, y0 + 520, 150, 110, HOODIE_D)
    cv.poly([(x0 + 100, y0 + 600), (x0 + 350, y0 + 600), (x0 + 330, y0 + 480), (x0 + 120, y0 + 480)], HOODIE)
    cv.circ(x0 + 225, y0 + 380, 100, WHITE)
    cv.circ(x0 + 192, y0 + 372, 11, NAVY0)
    cv.circ(x0 + 258, y0 + 372, 11, NAVY0)
    cv.text((x0 + 450, y0 + 240), "WANTED", "anton", 120, RED, anchor="lm")
    cv.text((x0 + 450, y0 + 380), "$35M BANK", "anton", 84, WHITE, anchor="lm")
    cv.text((x0 + 450, y0 + 480), "FRAUD", "anton", 84, WHITE, anchor="lm")
    cv.text((x0 + 452, y0 + 560), "FBI: DO NOT APPROACH", "interx", 26, (230, 232, 245), anchor="lm")
    cv.rect(x0, y1 - 90, x1, y1 - 20, (10, 12, 22))
    tick = "  •  SUSPECT LAST SEEN NEAR CENTRAL STATION  •  REWARD OFFERED  •  FBI INVESTIGATION ONGOING"
    off = (t * 220) % 1400
    cv.text((x0 + 20 - off, y1 - 55), tick * 2, "interx", 30, (230, 232, 245), anchor="lm")
    cv.rect(x0 - 50, y0, x0, y1, (60, 62, 82))
    cv.rect(x1, y0, x1 + 50, y1, (60, 62, 82))
    cv.rect(0, y0, 40, y1, (30, 34, 60))
    cv.rect(1040, y0, W, y1, (30, 34, 60))
    for yy in range(y0, y1, 8):
        cv.rect(x0, yy, x1, yy + 3, (0, 0, 0, 45))
    cv.glow_rect(x0, y0, x1, y1, (150, 160, 255), 70)
    cv.rect(0, 1300, W, H, (16, 17, 40))


def building_ext(cv, t, pin=0.0, suvs=0.0, wash=0.0, agents=0.0):
    cv.im.paste(gradient(W, 1500, (5, 7, 24), (26, 26, 72), "bext"), (0, 0))
    stars(cv, (0, 0, W, 500), seed=33)
    paste_strip(cv, skyline_strip("sky35", 2400, 200, 600, 70, 180, (15, 17, 48), (110, 120, 150), 640, 7, 0.06), 150, 700, 2400)
    # your block
    cv.rect(180, 380, 900, 1500, (34, 36, 80))
    cv.rect(160, 360, 920, 390, (44, 48, 100))
    for r in range(9):
        for c in range(5):
            x, y = 230 + c * 130, 440 + r * 110
            lit = hrand(r * 5 + c, 91) > 0.62
            mine = (r == 4 and c == 2)
            col = BULB if mine else ((90, 96, 130) if lit else (16, 18, 40))
            cv.rect(x, y, x + 80, y + 70, col if not mine else mix((40, 36, 30), BULB, 0.7))
            if mine:
                cv.glow(x + 40, y + 35, 90, BULB, 140)
    cv.rect(480, 1360, 600, 1500, (14, 16, 36))      # door
    cv.rect(0, 1500, W, 1540, (40, 42, 86))
    cv.rect(0, 1540, W, H, (14, 15, 36))
    for k in range(6):
        cv.rect(k * 220 - 40, 1720, k * 220 + 80, 1730, (60, 62, 100))
    if pin > 0:
        x, y = 520 + 40, 840
        blink = (int(t * 3) % 2) == 0
        pc = RED if blink else (150, 20, 30)
        sc = 0.6 + 0.4 * eout(pin)
        cv.circ(x, y - 160 * sc, 70 * sc, pc)
        cv.poly([(x - 52 * sc, y - 120 * sc), (x + 52 * sc, y - 120 * sc), (x, y)], pc)
        cv.circ(x, y - 162 * sc, 26 * sc, (250, 240, 240))
        cv.glow(x, y - 130, 220, COP_R, 200 if blink else 80)
        pulse = (t * 1.4) % 1.0
        cv.ell(x, y + 10, 60 + 260 * pulse, (60 + 260 * pulse) * 0.35, None, outline=RED + (int(200 * (1 - pulse)),), w=5)
    if suvs > 0:
        for k, (x_end, delay) in enumerate(((60, 0.0), (560, 0.35))):
            u = eout(clamp((suvs - delay) / 0.65))
            x = lerp(-900 - k * 300, x_end, u)
            suv(cv, x, 1700, t + k)
    if agents > 0:
        for k, x in enumerate((300, 430, 760)):
            a = clamp((agents - k * 0.2) / 0.4)
            if a > 0:
                suit_man(cv, x, 1690 - 20 * (1 - a), s=0.42, shades=False, fbi_back=True, color=(10, 10, 16))
    rain(cv, t, (0, 0, W, H), alpha=60, n=220)
    if wash > 0:
        ph = (t * 2.6) % 1.0
        col = COP_R if ph < 0.5 else COP_B
        a = math.sin((ph % 0.5) / 0.5 * math.pi)
        cv.glow_rect(0, 900, W, 1800, col, int(110 * wash * a))


def suv(cv, x, ground, t):
    cv.rrect(x, ground - 230, x + 460, ground - 50, 26, (8, 8, 14))
    cv.poly([(x + 80, ground - 230), (x + 380, ground - 230), (x + 350, ground - 320), (x + 120, ground - 320)], (8, 8, 14))
    cv.poly([(x + 140, ground - 300), (x + 230, ground - 300), (x + 230, ground - 236), (x + 110, ground - 236)], (40, 44, 70))
    cv.poly([(x + 240, ground - 300), (x + 335, ground - 300), (x + 360, ground - 236), (x + 240, ground - 236)], (40, 44, 70))
    for wx in (x + 100, x + 360):
        cv.circ(wx, ground - 40, 50, (4, 4, 8))
        cv.circ(wx, ground - 40, 22, (50, 52, 70))
    on = int(t * 8) % 2
    cv.rect(x + 250, ground - 248, x + 290, ground - 236, COP_R if on else (80, 10, 14))
    cv.rect(x + 292, ground - 248, x + 332, ground - 236, COP_B if not on else (10, 20, 80))
    cv.glow(x + 290, ground - 242, 140, COP_R if on else COP_B, 200)
    cv.ell(x + 450, ground - 130, 14, 10, (255, 250, 230))
    cv.glow(x + 470, ground - 130, 100, (230, 230, 255), 140)


def stairwell(cv, t, run_u):
    """switchback stairs seen from the side; figure runs down. returns camera"""
    cv.rect(0, 0, W, H * 1, (22, 24, 56))
    # draw 4 flights downward in scene coordinates (tall scene: use y up to H)
    flights = []
    for k in range(4):
        y0 = 200 + k * 440
        if k % 2 == 0:
            flights.append(((120, y0), (900, y0 + 440)))
        else:
            flights.append(((900, y0), (120, y0 + 440)))
    for (x0, y0), (x1, y1) in flights:
        cv.poly([(x0, y0 + 30), (x1, y1 + 30), (x1, y1 + 70), (x0, y0 + 70)], (14, 16, 40))
        cv.poly([(x0, y0), (x1, y1), (x1, y1 + 30), (x0, y0 + 30)], (40, 44, 96))
        n = 12
        for i in range(n):
            ax = lerp(x0, x1, i / n)
            bx = lerp(x0, x1, (i + 1) / n)
            ay = lerp(y0, y1, i / n)
            by = lerp(y0, y1, (i + 1) / n)
            cv.poly([(ax, ay), (bx, ay), (bx, by), (ax, by)], (46, 50, 108))
            cv.rect(min(ax, bx), ay - 4, max(ax, bx), ay + 4, (110, 116, 180))
        cv.line([(x0, y0 - 160), (x1, y1 - 160)], (120, 124, 170), 8)
        cv.line([(x0, y0), (x1, y1)], (14, 16, 40), 30, caps=False)
    # EXIT signs (green)
    for y in (180, 1060):
        cv.rrect(470, y, 610, y + 60, 8, (16, 60, 40))
        cv.text((540, y + 31), "EXIT", "interx", 34, GREEN)
        cv.glow(540, y + 30, 120, GREEN, 120)
    # runner position along the zigzag
    u = clamp(run_u) * 3.0
    k = min(int(u), 2)
    f = u - k
    (x0, y0), (x1, y1) = flights[k]
    x = lerp(x0, x1, f)
    y = lerp(y0, y1, f)
    going_right = x1 > x0
    ph = run_u * 60
    if going_right:
        you_run(cv, x - 40, y - 4, ph, s=0.7)
    else:
        you_run_left(cv, x + 40, y - 4, ph, s=0.7)
    return x, y


def you_run_left(cv, x, fy, ph, s=1.0):
    class Mirror:
        def __init__(m, cv, cx):
            m.cv, m.cx = cv, cx
        def _mx(m, pts):
            return [(2 * m.cx - px, py) for px, py in pts]
        def line(m, pts, c, w, caps=True):
            m.cv.line(m._mx(pts), c, w, caps)
        def poly(m, pts, c):
            m.cv.poly(m._mx(pts), c)
        def ell(m, cx, cy, rx, ry, c=None, outline=None, w=0):
            m.cv.ell(2 * m.cx - cx, cy, rx, ry, c, outline, w)
        def circ(m, cx, cy, r, c=None, outline=None, w=0):
            m.cv.circ(2 * m.cx - cx, cy, r, c, outline, w)
        def rrect(m, x0, y0, x1, y1, r, c=None, outline=None, w=0):
            m.cv.rrect(2 * m.cx - x1, y0, 2 * m.cx - x0, y1, r, c, outline, w)
    you_run(Mirror(cv, x), x, fy, ph, s=s)


def alley(cv, t, speed=1300, door=None, wash=0.4):
    """side-scrolling rainy alley. figure runs at x≈430"""
    dist = t * speed
    cv.im.paste(gradient(W, 900, (5, 7, 24), (24, 24, 66), "alsky"), (0, 0))
    paste_strip(cv, skyline_strip("al_far", 2400, 300, 700, 80, 200, (16, 18, 50), (100, 110, 140), 900, 12, 0.05), dist * 0.15, 260, 2400)
    # brick walls (near), scrolling
    seg = 520
    for k in range(-1, 4):
        x = k * seg - (dist * 0.7) % seg
        shade = (30, 26, 52) if (k + int(dist * 0.7 // seg)) % 2 == 0 else (34, 30, 60)
        cv.rect(x, 520, x + seg - 30, 1500, shade)
        for row in range(20):
            y = 540 + row * 48
            off = 30 if row % 2 else 0
            for c in range(6):
                bx = x + off + c * 90
                cv.rect(bx, y, bx + 84, y + 42, (shade[0] + 6, shade[1] + 4, shade[2] + 10))
        # fire escape
        cv.rect(x + 80, 640, x + 360, 650, (12, 12, 26))
        cv.rect(x + 80, 900, x + 360, 910, (12, 12, 26))
        cv.line([(x + 100, 650), (x + 340, 900)], (12, 12, 26), 6, caps=False)
        # window
        cv.rect(x + 160, 700, x + 260, 820, (14, 16, 36))
    # streetlights (parallax 1.0)
    for k in range(-1, 4):
        lx = k * 640 - dist % 640 + 200
        cv.rect(lx - 6, 520, lx + 6, 1500, (18, 20, 44))
        cv.rect(lx - 6, 520, lx + 70, 532, (18, 20, 44))
        cv.ell(lx + 70, 540, 26, 10, SODIUM)
        cv.glow(lx + 70, 560, 170, SODIUM, 120)
        cv.poly([(lx + 50, 545), (lx + 90, 545), (lx + 230, 1500), (lx - 90, 1500)], SODIUM + (22,))
    # ground + puddles
    cv.rect(0, 1500, W, H, (14, 15, 36))
    for k in range(-1, 5):
        px = k * 380 - dist % 380
        cv.ell(px + 100, 1640 + (k % 2) * 60, 120, 14, (60, 70, 120, 120))
    # dumpsters (parallax 1.0)
    for k in range(-1, 3):
        dx = k * 1100 - dist % 1100 + 700
        cv.rrect(dx, 1330, dx + 260, 1500, 10, (20, 50, 44))
        cv.rect(dx - 10, 1320, dx + 270, 1340, (16, 40, 36))
    if door is not None:
        dx = 260 - door * 900
        cv.rect(dx - 20, 1060, dx + 180, 1500, (10, 10, 24))
        cv.poly([(dx, 1080), (dx + 160, 1080), (dx + 160, 1500), (dx, 1500)], (230, 236, 255, 60))
        cv.glow(dx + 80, 1280, 200, (220, 230, 255), 150)
        cv.rrect(dx + 30, 1000, dx + 130, 1040, 6, (16, 60, 40))
        cv.text((dx + 80, 1021), "EXIT", "interx", 24, GREEN)
    you_run(cv, 430, 1560, t * 13, s=0.95)
    rain(cv, t, (0, 0, W, H), alpha=65, n=240, slant=0.3, speed=1.2)
    if wash > 0:
        ph = (t * 2.6) % 1.0
        col = COP_R if ph < 0.5 else COP_B
        a = math.sin((ph % 0.5) / 0.5 * math.pi)
        cv.glow_rect(0 if ph < 0.5 else W * 0.5, 0, W * 0.5 if ph < 0.5 else W, H, col, int(90 * wash * a))


def platform(cv, t, you_x=300, agent=None, badge=0.0, screen=None, doors=1.0, eyes=True, look=0.0):
    """train platform, train behind with open doors. agent: x position or None"""
    # station wall above train
    cv.rect(0, 0, W, 640, (28, 32, 70))
    for yy in range(0, 640, 56):
        for xx in range(0, W, 90):
            cv.rect(xx + 2, yy + 2, xx + 88, yy + 54, (34, 38, 82))
    cv.rect(0, 620, W, 660, (16, 18, 40))
    # train body
    cv.rect(0, 660, W, 1400, (54, 60, 104))
    cv.rect(0, 1000, W, 1040, GREEN)      # livery stripe
    cv.rect(0, 1350, W, 1400, (30, 34, 66))
    # windows
    for wx in (40, 760, 960):
        cv.rrect(wx, 760, wx + 160, 960, 20, (170, 190, 220))
        cv.glow_rect(wx, 760, wx + 160, 960, (180, 200, 240), 50)
    # doors: open gap with lit interior
    gx0, gx1 = 330, 690
    op = ease(doors)
    cv.rect(gx0, 720, gx1, 1350, (40, 44, 80))
    cv.rect(gx0 + 10, 730, gx1 - 10, 1350, (190, 205, 230))
    cv.rect(gx0 + 10, 1150, gx1 - 10, 1350, (140, 150, 180))
    cv.rect(gx0 + 40, 1050, gx1 - 40, 1100, (60, 70, 120))   # seats inside
    cv.rect(gx0 + 175, 730, gx0 + 185, 1350, (230, 220, 160))  # pole
    cv.glow_rect(gx0, 730, gx1, 1350, (200, 215, 255), 90)
    leaf = (gx1 - gx0) / 2 * (1 - op)
    cv.rect(gx0, 720, gx0 + leaf + 2, 1350, (64, 70, 118))
    cv.rect(gx1 - leaf - 2, 720, gx1, 1350, (64, 70, 118))
    # platform screen (LED) hanging from the ceiling
    cv.rect(536, 0, 544, 400, (14, 14, 24))
    cv.rrect(170, 390, 910, 590, 18, (6, 6, 12), outline=(46, 50, 110), w=5)
    if screen is None:
        rem = max(0, 59 - int(t - 62))
        layers = [("12:00 CENTRAL", GREEN, "c", 1), ("DEPARTS 0:%02d" % rem, GREEN, "c", 9)]
        fl = 1.0
    else:
        layers, fl = screen
    draw_led(cv, 540 - 52 * 13 / 2, 410, 52, 17, 13, layers, off_col=(16, 22, 18), flick=fl)
    # platform floor
    cv.rect(0, 1400, W, H, (26, 28, 56))
    for k in range(0, W, 60):
        cv.rect(k, 1420, k + 34, 1436, (220, 220, 230))     # edge line
    for k in range(5):
        cv.rect(0, 1520 + k * 90, W, 1523 + k * 90, (32, 34, 66))
    # ceiling lights wash
    cv.glow_rect(0, 1400, W, 1500, (180, 200, 240), 40)
    if agent is not None:
        suit_man(cv, agent, 1780, s=0.95, badge_up=badge)
    you_stand(cv, you_x, 1780, s=0.9, eyes=eyes, look=look)


def shadow_wall(cv, t, badge=1.0):
    """tiled wall with a hard light from the left: the agent's shadow holds a phone"""
    cv.rect(0, 0, W, H, (40, 46, 92))
    for yy in range(0, 1500, 70):
        for xx in range(0, W, 110):
            cv.rect(xx + 3, yy + 3, xx + 107, yy + 67, (46, 52, 102))
    cv.glow(0, 700, 700, (200, 215, 255), 120)
    cv.rect(0, 1500, W, H, (26, 28, 56))
    man_shadow(cv, 720, 1600, 1.25, holds_phone=True, a=215)
    # the faint glow of a screen in the shadow's hand
    cv.glow(720 + 170 * 1.25, 1600 - 610 * 1.25 - 130 * 1.25 - 50, 60, GREEN, int(80 + 60 * math.sin(t * 6)))
    suit_man(cv, 330, 1700, s=1.0, badge_up=badge)


# ================================================================ captions / HUD / rules
VO = json.load(open(f"{SCR}/vo35/vo.json"))
CAPS = []
for i, ln in enumerate(VO):
    if not ln["cap"]:
        continue
    chunks = ln["cap"].split("|")
    wts = [max(3, len(c.replace("*", "").replace("_", ""))) for c in chunks]
    tot = sum(wts)
    nxt = VO[i + 1]["start"] if i + 1 < len(VO) else 999
    tt = ln["start"]
    for c, w in zip(chunks, wts):
        d = ln["dur"] * w / tot
        CAPS.append([tt, tt + d, parse_chunk(c)])
        tt += d
    CAPS[-1][1] = min(tt + 0.45, nxt - 0.02)


def draw_captions(img, t, y=1340, size=112):
    lb.CAPS[:] = CAPS
    lb.draw_captions(img, t, y=y, size=size)


def clock_str(t):
    if t < 16:
        return "11:42 PM"
    if t < 31:
        return "11:43 PM"
    if t < 38:
        return "11:45 PM"
    if t < 42.6:
        return "11:46 PM"
    if t < 45:
        return "11:47 PM"
    if t < 62:
        m = 47 + int((t - 45) / 17 * 12)
        return f"11:{min(m, 58):02d} PM"
    if t < 88:
        return "11:59 PM"
    return "12:00 AM"


def draw_hud(img, t):
    d = ImageDraw.Draw(img, "RGBA")
    pulse = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 4))
    d.ellipse([60, 101, 82, 123], fill=(232, 36, 46, int(255 * pulse)))
    d.text((96, 112), "DAY 1", font=F("interx", 34), fill=WHITE, anchor="lm")
    cs = clock_str(t)
    f = F("mono", 92)
    fast = 45 <= t < 62
    if fast and int(t * 6) % 2 == 0:
        d.text((60 + 4, 140), cs, font=f, fill=(232, 36, 46, 150), anchor="lt")
    d.text((60 + 3, 143), cs, font=f, fill=(0, 0, 0, 140), anchor="lt")
    d.text((60, 140), cs, font=f, fill=WHITE, anchor="lt")
    bal, done = balance_text(t)
    rolling = BAL_T0 <= t < BAL_T1
    col = GREEN if (done or rolling) else (170, 174, 210)
    x = 63
    fnt = F("inters", 26 if (done or rolling) else 24)
    for ch in "BALANCE: " + bal:
        d.text((x, 262), ch, font=fnt, fill=col, anchor="lm")
        x += fnt.getlength(ch) + 3


RULES = {
    1: (24.0, 27.2, "LEAVE YOUR PHONE."),
    2: (31.0, 34.5, "DON'T TRUST ANYONE IN A SUIT."),
    3: (38.0, 41.6, "BE ON THE 12:00 TRAIN."),
}


def draw_rule(img, t, n):
    lb.RULES.update({n: RULES[n]})
    lb.draw_rule(img, t, n)


def police_wash(img, t, amt):
    ph = (t * 2.6) % 1.0
    col = np.array(COP_R if ph < 0.5 else COP_B, np.float32)
    a = math.sin((ph % 0.5) / 0.5 * math.pi) * amt
    xs = np.linspace(1, 0, W) if ph < 0.5 else np.linspace(0, 1, W)
    m = (xs[None, :, None] ** 1.5) * a * 0.38
    arr = np.asarray(img).astype(np.float32)
    arr = arr + col[None, None, :] * m
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ================================================================ timeline
CUTS = [4.0, 8.0, 9.6, 12.6, 16.0, 24.0, 27.2, 29.5, 31.0, 34.5, 38.0, 41.6, 45.0, 48.5, 51.2, 53.4, 56.4,
        62.0, 65.8, 69.0, 76.0, 78.4, 82.0]
TENSE = [(45.0, 62.0), (65.8, 82.0)]


def frame(t):
    cv = Cv()
    cam = (540, 960, 1.0)
    extra, fl_a, chrom, shake, wash = [], 0.0, 0, 0.0, 0.0
    cap_y = 1340

    def cut_flash(t0, d=0.16, a=0.6):
        return a * (1 - (t - t0) / d) if t0 <= t < t0 + d else 0.0

    if t < 4.0:
        bedsit(cv, t, fig="sit", phone_glow=0.4)
        u = ease(prog(t, 0, 4.0))
        cam = (lerp(540, 520, u), lerp(1000, 1000, u), lerp(1.0, 1.15, u))
    elif t < 8.0:
        # close on the phone in hand: balance $3.12
        cv.rect(0, 0, W, H, (20, 22, 52))
        cv.glow(540, 300, 500, BULB, 60)
        box = phone_frame(cv, 250, 300, 580, 1160)
        northpay_screen(cv, box, t)
        u = ease(prog(t, 4.0, 8.0))
        cam = (540, lerp(900, 880, u), lerp(1.0, 1.06, u))
        cap_y = 1700
    elif t < 9.6:
        # phone buzzes on the table
        bz = (int(t * 30) % 2) * 2 - 1 if 8.3 <= t < 9.3 else 0
        bedsit(cv, t, fig="sit", phone_glow=1.0 if t >= 8.3 else 0.4, eyes=t > 8.6, look=0.5)
        cam = (620 + bz * 3, 1120, lerp(2.4, 2.6, prog(t, 8.0, 9.6)))
        shake = 3 if bz else 0
    elif t < 12.6:
        cv.rect(0, 0, W, H, (20, 22, 52))
        cv.glow(540, 300, 500, BULB, 60)
        box = phone_frame(cv, 250, 300, 580, 1160)
        northpay_screen(cv, box, t, banner=prog(t, 9.7, 10.1))
        u = ease(prog(t, 9.6, 12.6))
        cam = (540, lerp(880, 860, u), lerp(1.04, 1.08, u))
        cap_y = 1700
        if BAL_T0 <= t < BAL_T1:
            chrom = 3
    elif t < 16.0:
        # stands up, drops the noodles
        lt = t - 12.6
        if t < 13.4:
            def hold(hx, hy):
                cup(cv, hx + 20, hy + 70, t, steam=True)
            bedsit(cv, t, fig="stand", noodles={"arms": 0.0, "hold": hold}, steam=False, phone_glow=0.8, figure_x=470)
        else:
            u = clamp((t - 13.4) / 0.55)
            arms = eout(u * 1.6)
            bedsit(cv, t, fig="stand", noodles={"arms": arms}, steam=False, phone_glow=0.8, figure_x=470)
            hx, hy = 470 + 170, 1460 - 300 - 290 + 30 + 60
            if u < 1:
                cup(cv, hx + 20, hy + 70 + (1460 - hy - 70) * u * u, t, steam=False, ang=u * 2.2)
            else:
                cup(cv, hx + 60, 1470, t, steam=False, ang=1.57)
                for k in range(7):    # noodle splat
                    sx = hx - 40 + k * 26
                    cv.line([(sx, 1468), (sx + 10, 1458), (sx + 22, 1470), (sx + 30, 1460)], (240, 225, 170), 5)
                cv.ell(hx + 30, 1478, 130 * eout((t - 13.95) / 0.4), 16, (170, 120, 60, 170))
            if 13.9 <= t < 14.05:
                shake = 6
        u = ease(prog(t, 12.6, 16.0))
        cam = (lerp(520, 540, u), lerp(1060, 1100, u), lerp(1.05, 1.15, u))
        fl_a = cut_flash(12.6, a=0.3)
    elif t < 24.0:
        cv.rect(0, 0, W, H, (16, 18, 46))
        cv.glow(540, 300, 500, BULB, 50)
        box = phone_frame(cv, 250, 300, 580, 1160)
        messages_screen(cv, box, t)
        if 16.0 <= t < 16.6:
            shake = 2 if int(t * 30) % 2 else 0
        u = ease(prog(t, 16.0, 24.0))
        cam = (540, lerp(900, 880, u), lerp(1.0, 1.06, u))
        cap_y = 1700
    elif t < 27.2:
        bedsit(cv, t, fig="sit", phone_glow=0.8, eyes=True)
        cam = (540, 980, lerp(1.1, 1.2, prog(t, 24.0, 27.2)))
        extra.append(lambda im: draw_rule(im, t, 1))
        fl_a = cut_flash(24.0, a=0.7)
    elif t < 29.5:
        cv.rect(0, 0, W, H, (16, 18, 46))
        box = phone_frame(cv, 250, 300, 580, 1160)
        map_screen(cv, box, t)
        cam = (540, 880, lerp(1.0, 1.1, ease(prog(t, 27.2, 29.5))))
        cap_y = 1700
    elif t < 31.0:
        building_ext(cv, t, pin=prog(t, 29.5, 29.9))
        cam = (540, lerp(1000, 900, ease(prog(t, 29.5, 31.0))), lerp(1.0, 1.08, prog(t, 29.5, 31.0)))
    elif t < 34.5:
        bedsit(cv, t, fig="sit", eyes=True, look=0.4, phone_on_table=False)
        cam = (540, 980, lerp(1.1, 1.2, prog(t, 31.0, 34.5)))
        extra.append(lambda im: draw_rule(im, t, 2))
        fl_a = cut_flash(31.0, a=0.7)
    elif t < 38.0:
        # peephole: a man in a suit outside your door
        cv.rect(0, 0, W, H, (30, 30, 52))
        cv.rect(0, 1300, W, H, (22, 22, 40))
        cv.rect(0, 420, W, 440, (40, 40, 64))
        cv.glow(540, 300, 400, (220, 220, 255), 110)
        suit_man(cv, 560, 1620, s=1.15, shades=True)
        u = ease(prog(t, 34.5, 38.0))
        cam = (540, 1000, lerp(1.0, 1.1, u))

        def peephole(im):
            yy, xx = np.ogrid[0:H, 0:W]
            r = np.sqrt((xx - W / 2) ** 2 + (yy - 960) ** 2)
            m = np.clip((r - 470) / 40, 0, 1)
            arr = np.asarray(im).astype(np.float32) * (1 - m[..., None]) + np.array([4, 4, 10], np.float32) * m[..., None]
            im.paste(Image.fromarray(arr.astype(np.uint8)))
        extra.append(peephole)
    elif t < 41.6:
        bedsit(cv, t, fig="sit", eyes=True, phone_on_table=False)
        cam = (540, 980, lerp(1.1, 1.2, prog(t, 38.0, 41.6)))
        extra.append(lambda im: draw_rule(im, t, 3))
        fl_a = cut_flash(38.0, a=0.7)
    elif t < 45.0:
        cv.rect(0, 0, W, H, (8, 9, 22))
        cam = (540, 960, 1.0)

        def flipclock(im, t=t):
            d = ImageDraw.Draw(im, "RGBA")
            mins = "46" if t < 42.6 else "47"
            flip = clamp((t - 42.6) / 0.25)
            for i, (txt, cx) in enumerate((("11", 330), (mins, 750))):
                d.rounded_rectangle([cx - 190, 520, cx + 190, 1060], radius=30, fill=(26, 28, 44))
                d.text((cx, 790), txt, font=F("mono", 300), fill=WHITE, anchor="mm")
                d.rectangle([cx - 190, 786, cx + 190, 794], fill=(8, 9, 22))
                if i == 1 and 0 < flip < 1:   # falling flap
                    hgt = int(270 * abs(1 - 2 * flip))
                    d.rectangle([cx - 190, 520 + (270 - hgt), cx + 190, 790], fill=(36, 38, 58))
            d.text((540, 790), ":", font=F("mono", 220), fill=WHITE, anchor="mm")
            d.text((540, 1130), "PM", font=F("mono", 70), fill=(170, 174, 210), anchor="mm")
            if t >= 42.8:
                a = int(255 * eout((t - 42.8) / 0.3))
                d.text((540, 440), "13 MINUTES TO THE TRAIN", font=F("interx", 40), fill=(232, 36, 46, a), anchor="mm")
        extra.append(flipclock)
        fl_a = cut_flash(41.6, a=0.5) + cut_flash(42.6, d=0.1, a=0.3)
    elif t < 48.5:
        tv_full_news(cv, t)
        u = ease(prog(t, 45.0, 48.5))
        cam = (540, 880, lerp(1.0, 1.15, u))
        fl_a = cut_flash(45.0, a=0.6)
        chrom = 4 if t < 45.4 else 0
    elif t < 51.2:
        bedsit(cv, t, fig="stand", wash=1.0, eyes=True, look=0.7 * ease(prog(t, 48.6, 49.4)), tv=tv_news(45),
               phone_on_table=True, phone_glow=0.6, figure_x=420)
        u = ease(prog(t, 48.5, 51.2))
        cam = (lerp(560, 600, u), lerp(1000, 960, u), lerp(1.0, 1.1, u))
        wash = 0.8
    elif t < 53.4:
        building_ext(cv, t, suvs=(t - 51.2) / 1.2, wash=1.0, agents=(t - 52.3) / 0.8)
        cam = (540, lerp(1150, 1200, prog(t, 51.2, 53.4)), lerp(1.05, 1.12, prog(t, 51.2, 53.4)))
        wash = 0.9
    elif t < 56.4:
        x, y = stairwell(cv, t, prog(t, 53.4, 56.4))
        cam = (x, y - 40, 1.3)
        wash = 0.35
    elif t < 62.0:
        alley(cv, t, door=prog(t, 56.4, 57.4) if t < 57.5 else None, wash=0.5)
        cam = (520, 1080, lerp(1.05, 1.15, ease(prog(t, 56.4, 62.0))))
        wash = 0.5
    elif t < 65.8:
        you_x = lerp(-120, 300, eout(prog(t, 62.0, 63.2)))
        platform(cv, t, you_x=you_x, eyes=True, look=0.6)
        u = ease(prog(t, 62.0, 65.8))
        cam = (lerp(540, 520, u), lerp(1000, 1060, u), lerp(1.0, 1.08, u))
        fl_a = cut_flash(62.0, a=0.4)
    elif t < 76.0:
        ax = lerp(1300, 640, eout(prog(t, 66.0, 67.0)))
        badge = ease(prog(t, 67.2, 67.7))
        platform(cv, t, you_x=300, agent=ax, badge=badge, eyes=True, look=0.5)
        u = ease(prog(t, 65.8, 76.0))
        cam = (lerp(520, 480, u), lerp(1060, 1040, u), lerp(1.08, 1.3, u))

        def agent_label(im, t=t, cam=cam, ax=ax):
            a = eout(prog(t, 67.3, 67.8))
            if a <= 0:
                return
            d = ImageDraw.Draw(im, "RGBA")
            x, y = to_screen(cam, ax, 780)
            x = clamp(x, 330, 750)
            d.rounded_rectangle([x - 320, y - 30, x + 320, y + 30], radius=30, fill=(5, 6, 18, int(170 * a)))
            spaced(d, (x, y), "— AGENT · ON THE PLATFORM —", "interx", 28, ORANGE + (int(255 * a),), 3)
        extra.append(agent_label)
    elif t < 78.4:
        rows = [("HE'S THE ONE", RED, "c", 1), ("WHO SENT IT.", RED, "c", 9)]
        fl = lb.flicker(t, 76.0, 76.6, 41)
        if t < 76.25:
            rows = [("12:00 CENTRAL", GREEN, "c", 1), ("DEPARTS 0:45", GREEN, "c", 9)]
        platform(cv, t, you_x=300, agent=640, badge=1.0, screen=(rows, fl), eyes=True, look=0.5)
        cam = (540, 560, lerp(1.25, 1.33, prog(t, 76.0, 78.4)))
        chrom = 6 if fl < 1 else 0
        fl_a = cut_flash(76.0, a=0.6)
    elif t < 82.0:
        shadow_wall(cv, t)
        u = ease(prog(t, 78.4, 82.0))
        cam = (lerp(600, 760, u), lerp(1000, 820, u), lerp(1.0, 1.25, u))
        fl_a = cut_flash(78.4, d=0.12, a=0.8)
        if 79.6 <= t < 80.4:
            shake = 2 if int(t * 30) % 2 else 0
    elif t < 88.0:
        return choice_frame(t)
    else:
        return outro_frame(t)

    img = camera(cv, *cam)
    if shake:
        img = ImageChops.offset(img, int((hrand(int(t * 60), 3) - 0.5) * 2 * shake), int((hrand(int(t * 60), 4) - 0.5) * 2 * shake))
    if any(a <= t < b for a, b in TENSE):
        img = tilt_img(img, 0.7 * math.sin(t * 0.7) + 0.3 * math.sin(t * 1.9))
    if wash:
        img = police_wash(img, t, wash)
    if chrom:
        img = chroma(img, chrom)
    for c in CUTS:
        if c <= t < c + 0.08:
            img = vhs(img, t, 18)
    for fn in extra:
        fn(img)
    img = post(img, t)
    draw_hud(img, t)
    draw_captions(img, t, y=cap_y)
    return flash(img, fl_a)


def choice_frame(t):
    cv = Cv()
    platform(cv, t, you_x=-400, agent=None)
    left = camera(cv, 510, 1040, 1.05)
    cv2 = Cv()
    cv2.rect(0, 0, W, H, (40, 46, 92))
    for yy in range(0, 1500, 70):
        for xx in range(0, W, 110):
            cv2.rect(xx + 3, yy + 3, xx + 107, yy + 67, (46, 52, 102))
    cv2.rect(0, 1500, W, H, (26, 28, 56))
    suit_man(cv2, 540, 1700, s=1.0, badge_up=1.0)
    right = camera(cv2, 560, 1000, 1.15)
    img = Image.new("RGB", (W, H))
    img.paste(left.crop((270, 0, 810, H)), (0, 0))
    img.paste(right.crop((270, 0, 810, H)), (540, 0))
    sl = eout(prog(t, 82.0, 82.4))
    if sl < 1:
        img = Image.blend(Image.new("RGB", (W, H)), img, sl)
    img = post(img, t)
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(1080, H, 6):
        gd.rectangle([0, y, W, y + 6], fill=(4, 5, 16, int(clamp((y - 1080) / 260) * 235)))
    img.paste(Image.alpha_composite(img.convert("RGBA"), grad).convert("RGB"))
    d = ImageDraw.Draw(img, "RGBA")
    jit = int((hrand(int(t * 20), 4) - 0.5) * 6)
    d.rectangle([538 + jit, 0, 542 + jit, 1180], fill=(232, 36, 46, 230))
    spaced(d, (270, 1060), "THE TRAIN", "interx", 26, (126, 204, 255), 6)
    spaced(d, (810, 1060), "THE AGENT", "interx", 26, ORANGE, 6)
    q = eout(prog(t, 82.3, 82.7))
    if q > 0:
        ft = F("anton", int(150 * (1.15 - 0.15 * q)))
        d.text((546, 1278), "TRAIN OR AGENT?", font=ft, fill=(0, 0, 0, int(200 * q)), anchor="mm")
        d.text((540, 1270), "TRAIN OR AGENT?", font=ft, fill=(246, 246, 250, int(255 * q)), anchor="mm")
    for i, (lab, em, col, cx, tt) in enumerate([("TRAIN", "🚆", (64, 150, 255), 290, 82.8), ("AGENT", "🕴", ORANGE, 790, 83.05)]):
        p = eout(prog(t, tt, tt + 0.25))
        if p <= 0:
            continue
        pulse = 1 + 0.03 * math.sin((t - tt) * 5 + i * 2)
        bw, bh = 430 * p * pulse, 128 * p * pulse
        cy = 1460
        d.rounded_rectangle([cx - bw / 2, cy - bh / 2 + 8, cx + bw / 2, cy + bh / 2 + 8], radius=bh / 2, fill=(0, 0, 0, 120))
        d.rounded_rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], radius=bh / 2, fill=col)
        if p > 0.8:
            fnt = F("interx", 54)
            e = emoji(em, 60)
            total = e.width + 16 + fnt.getlength(lab)
            x0 = int(cx - total / 2)
            img.paste(e, (x0, int(cy - e.height / 2)), e)
            d.text((x0 + e.width + 16, cy + 2), lab, font=fnt, fill=WHITE, anchor="lm")
    draw_hud(img, t)
    draw_captions(img, t, y=1690, size=84)
    if t < 82.15:
        img = flash(img, 0.7 * (1 - (t - 82.0) / 0.15))
    return img


def outro_frame(t):
    from PIL import ImageFilter
    lt = t - 88.0
    img = Image.new("RGB", (W, H), (5, 5, 14))
    gl = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(gl)
    q = eout(prog(t, 88.3, 88.9))
    flick = 1.0 if hrand(int(t * 15), 19) > 0.08 else 0.5
    a = q * flick
    gd.text((540, 930), "DAY 2", font=F("anton", 300), fill=(int(232 * a), int(30 * a), int(40 * a)), anchor="mm")
    gl = gl.filter(ImageFilter.GaussianBlur(28))
    img = ImageChops.add(img, gl)
    img = ImageChops.add(img, gl)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((540, 930), "DAY 2", font=F("anton", 300), fill=(255, 60, 66, int(255 * a)), anchor="mm")
    spaced(d, (540, 690), "35 MILLION", "inters", 34, (200, 204, 230, int(255 * eout(prog(t, 88.1, 88.6)))), 22)
    d.text((540, 1160), "12:00 AM", font=F("mono", 70), fill=(220, 222, 240, int(255 * eout(prog(t, 88.8, 89.3)))), anchor="mm")
    q4 = eout(prog(t, 89.4, 89.8))
    if q4 > 0:
        pulse = 1 + 0.025 * math.sin((t - 89.4) * 4)
        bw, bh = 600 * pulse, 120 * pulse
        d.rounded_rectangle([540 - bw / 2, 1400 - bh / 2, 540 + bw / 2, 1400 + bh / 2], radius=bh / 2,
                            outline=(246, 246, 250, int(255 * q4)), width=5)
        spaced(d, (540, 1402), "FOLLOW FOR DAY 2", "interx", 44, (246, 246, 250, int(255 * q4)), 3)
    img = post(img, t)
    draw_hud(img, t)
    if lt < 0.6:
        img = Image.blend(Image.new("RGB", (W, H)), img, eout(lt / 0.6))
    if t > 91.4:
        img = Image.blend(img, Image.new("RGB", (W, H)), clamp((t - 91.4) / 0.6))
    return img


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
