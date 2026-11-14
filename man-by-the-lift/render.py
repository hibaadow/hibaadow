"""THE MAN BY THE LIFT — frame renderer (same toolkit and look as ../35-million and ../last-bus).

usage: python render.py <start_frame> <end_frame> <out.mp4>
       python render.py --still <t> <out.png>
"""
import importlib.util, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageChops, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("m35", os.path.join(HERE, "..", "35-million", "render.py"))
m35 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m35)
lb = m35.lb

Cv, camera, to_screen, F = lb.Cv, lb.camera, lb.to_screen, lb.F
clamp, lerp, ease, eout, prog, mix, hrand = lb.clamp, lb.lerp, lb.ease, lb.eout, lb.prog, lb.mix, lb.hrand
post, chroma, flash, vhs, tilt_img, spaced, wrap, parse_chunk = lb.post, lb.chroma, lb.flash, lb.vhs, lb.tilt_img, lb.spaced, lb.wrap, lb.parse_chunk
W, H, FPS, SS = lb.W, lb.H, lb.FPS, lb.SS
NAVY0, WHITE, RED, LIME, BLUE, ORANGE, BLACK = lb.NAVY0, lb.WHITE, lb.RED, lb.LIME, lb.BLUE, lb.ORANGE, lb.BLACK
HOODIE, HOODIE_D = lb.HOODIE, lb.HOODIE_D
SCR = lb.SCR
HAIR = (44, 30, 28)
COAT, COAT_RIM, PALE = (16, 16, 26), (64, 66, 108), (200, 200, 214)
LIGHT = (225, 232, 255)
GREY_B = (62, 64, 78)

VO = json.load(open(f"{SCR}/vo_lift/vo.json"))

# ---------------------------------------------------------------- shot timeline from the voiceover
SHOTS = []
for m in VO:
    if not SHOTS or SHOTS[-1][0] != m["shot"]:
        SHOTS.append([m["shot"], max(0.0, m["start"] - 0.15), None])
for k in range(len(SHOTS) - 1):
    SHOTS[k][2] = SHOTS[k + 1][1]
DUR = VO[-1]["start"] + VO[-1]["dur"] + 3.0
SHOTS[-1][2] = DUR
SHOT_AT = {s[0]: (s[1], s[2]) for s in SHOTS}


def items(shot):
    return [m for m in VO if m["shot"] == shot]


def chunk_t(i, k, edge=0):
    """absolute time of caption chunk k of VO item i (edge 0=start, 1=end)"""
    m = VO[i]
    return m["start"] + m["chunks"][k][edge]


# ---------------------------------------------------------------- characters
def girl(cv, x, fy, s=1.0, eyes=True, look=0.0, back=False, arms_up=0.0, hold=None):
    """main character: the same white stick figure, red hoodie, black joggers — with long dark hair"""
    hy = fy - (300 + 290 + 60) * s
    r = 60 * s
    if back:
        cv.rrect(x - r - 6 * s, hy - 10 * s, x + r + 6 * s, hy + r + 150 * s, 30 * s, HAIR)
    m35.you_stand(cv, x, fy, s=s, eyes=eyes and not back, look=look, arms_up=arms_up, hold=hold)
    if back:
        cv.ell(x, hy, r + 6 * s, r + 6 * s, HAIR)
        cv.rrect(x - r - 6 * s, hy, x + r + 6 * s, hy + r + 150 * s, 30 * s, HAIR)
        return
    ex = look * 28 * s
    for sg in (-1, 1):
        cv.rrect(x + sg * (r - 2 * s) - 16 * s, hy - 24 * s, x + sg * (r - 2 * s) + 16 * s, hy + r + 110 * s, 14 * s, HAIR)
    cv.d.chord([(x - r - 6 * s) * SS, (hy - r - 10 * s) * SS, (x + r + 6 * s) * SS, (hy + r * 0.45) * SS], 180, 360, fill=HAIR)


def coat_man(cv, x, fy, s=1.0, a=255, rim=True):
    """the man in the dark coat: tall, no face, nothing distinctive"""
    c, cr, pale = COAT + (a,), COAT_RIM + (a,), PALE + (a,)
    neck = fy - 640 * s
    hem = fy - 210 * s
    for sg in (-1, 1):
        cv.line([(x + sg * 26 * s, hem - 20 * s), (x + sg * 34 * s, fy)], (8, 8, 14, a), 30 * s)
        cv.line([(x + sg * 34 * s, fy + 4 * s), (x + sg * 62 * s, fy + 6 * s)], (6, 6, 10, a), 16 * s)
    coat = [(x - 72 * s, neck + 8 * s), (x + 72 * s, neck + 8 * s), (x + 96 * s, hem), (x - 96 * s, hem)]
    if rim:
        cv.poly([(px + (4 if px > x else -4), py) for px, py in coat], cr)
    cv.poly(coat, c)
    cv.poly([(x - 24 * s, neck + 8 * s), (x + 24 * s, neck + 8 * s), (x, neck + 90 * s)], (24, 24, 36, a))
    for sg in (-1, 1):
        arm = [(x + sg * 66 * s, neck + 30 * s), (x + sg * 92 * s, neck + 200 * s), (x + sg * 90 * s, neck + 330 * s)]
        cv.line(arm, cr if rim else c, 38 * s)
        cv.line(arm, c, 32 * s)
        cv.circ(x + sg * 90 * s, neck + 340 * s, 14 * s, pale)
    cv.ell(x, neck - 66 * s, 56 * s, 66 * s, pale)


def neighbour(cv, x, fy, s=1.0, look=0.0):
    pal = dict(top=(110, 116, 136), top_d=(84, 88, 106), pants=(40, 60, 110), rim=(70, 90, 140), hood=False, hair=True, glasses=False)
    m35.you_stand(cv, x, fy, s=s, eyes=True, look=look, pal=pal)


def receptionist(cv, x, fy, s=1.0):
    pal = dict(top=(40, 50, 100), top_d=(30, 36, 80), pants=(30, 32, 50), rim=(60, 64, 100), hood=False, hair=False, glasses=False)
    m35.you_stand(cv, x, fy, s=s, eyes=True, look=-0.4, pal=pal)
    hy = fy - 650 * s
    cv.d.chord([(x - 66 * s) * SS, (hy - 70 * s) * SS, (x + 66 * s) * SS, (hy + 20 * s) * SS], 180, 360, fill=HAIR)
    cv.circ(x, hy - 70 * s, 26 * s, HAIR)


# ---------------------------------------------------------------- sets
def hallway(cv, t, man=True, lift_open=0.0, girl_at_door=False, pal=None, door_open=0.0, door_no="604",
            neighbour_out=None, man_in_door=0.0, girl_out=None, lights=1.0):
    p = pal or dict(wall=(40, 44, 88), side=(30, 33, 70), floor=(36, 26, 52), ceil=(16, 18, 40), door=(70, 60, 92))
    cv.rect(0, 0, W, H, p["side"])
    cv.poly([(0, 0), (W, 0), (750, 520), (330, 520)], p["ceil"])
    for k in range(4):                                   # ceiling light strips in perspective
        f = k / 4
        y = lerp(20, 500, f ** 0.7)
        w = lerp(300, 60, f ** 0.7)
        cv.rect(540 - w, y, 540 + w, y + lerp(18, 4, f), mix((60, 64, 100), LIGHT, lights))
        cv.glow(540, y + 10, lerp(260, 80, f), LIGHT, int(110 * lights))
    cv.poly([(330, 1200), (750, 1200), (W, H), (0, H)], p["floor"])
    for k in range(10):
        f = k / 10
        y = lerp(1200, H, f ** 1.6)
        cv.rect(0, y, W, y + 3, mix(p["floor"], (60, 44, 80), 0.5))
    cv.rect(330, 520, 750, 1200, p["wall"])
    # lift
    cv.rect(400, 600, 680, 1200, (24, 26, 50))
    cv.rect(420, 640, 660, 1200, (150, 156, 186))
    if lift_open > 0:
        o = ease(lift_open) * 120
        cv.rect(540 - o, 640, 540 + o, 1200, (230, 236, 250))
        cv.glow_rect(540 - o, 640, 540 + o, 1200, LIGHT, 160)
        cv.rect(420, 640, 540 - o, 1200, (150, 156, 186))
        cv.rect(540 + o, 640, 660, 1200, (150, 156, 186))
    cv.rect(538, 640, 542, 1200, (110, 116, 146))
    cv.rrect(500, 568, 580, 610, 8, (10, 10, 16))
    cv.text((540, 590), "6", "mono", 30, (255, 90, 90))
    cv.circ(700, 900, 12, (200, 200, 220))
    # doors on the side walls
    def side_door(x_near, x_far, y_top_near, y_top_far, y_bot_near, y_bot_far, col, label, op=0.0):
        cv.poly([(x_near, y_top_near), (x_far, y_top_far), (x_far, y_bot_far), (x_near, y_bot_near)], col)
        if op > 0:
            dark = [(x_near, y_top_near), (x_far, y_top_far), (x_far, y_bot_far), (x_near, y_bot_near)]
            cv.poly(dark, (8, 8, 16))
            cv.glow_poly(dark, (120, 130, 180), int(60 * op))
            sw = lerp(x_far, x_near + (x_near - x_far) * 0.6, ease(op))
            cv.poly([(x_far, y_top_far), (sw, y_top_near - 20), (sw, y_bot_near + 20), (x_far, y_bot_far)], col)
        lx, ly = lerp(x_near, x_far, 0.5), lerp(y_top_near, y_top_far, 0.5) + 60
        cv.rrect(lx - 40, ly - 22, lx + 40, ly + 22, 6, (210, 200, 160))
        cv.text((lx, ly + 1), label, "interx", 22, (30, 30, 40))
    side_door(1000, 820, 560, 660, 1640, 1350, p["door"], door_no, door_open)
    side_door(80, 260, 560, 660, 1640, 1350, (52, 50, 80), "604B" if door_no == "604" else "1205")
    if man:
        coat_man(cv, 560, 1220, s=0.62)
    if neighbour_out is not None:
        neighbour(cv, lerp(540, 470, ease(neighbour_out)), lerp(1210, 1330, ease(neighbour_out)), s=lerp(0.6, 0.72, neighbour_out), look=0.5)
    if man_in_door > 0:
        coat_man(cv, 930, 1500, s=0.85, a=int(255 * man_in_door))
    if girl_at_door:
        girl(cv, 760, 1900, s=1.0, back=True)
    if girl_out is not None:
        girl(cv, lerp(900, 760, ease(girl_out)), 1780, s=0.9, back=True)


def door_inside(cv, t, states, newdoor=False, knock=None, hand=True):
    """inside of the front door, close. states: list of (time, locked) for the deadbolt"""
    cv.rect(0, 0, W, H, (26, 28, 60))
    col = (84, 92, 136) if newdoor else (70, 62, 96)
    cv.rect(140, 0, 940, H, col)
    cv.rect(140, 0, 160, H, mix(col, (0, 0, 0), 0.3))
    cv.rect(920, 0, 940, H, mix(col, (0, 0, 0), 0.3))
    for y in (180, 1100):
        cv.rect(220, y, 860, y + 700, mix(col, (255, 255, 255), 0.05))
    cv.circ(540, 380, 26, (20, 20, 30))                       # peephole
    cv.circ(540, 380, 34, None, outline=(150, 150, 170), w=6)
    locked = True
    for tt, st in states:
        if t >= tt:
            locked = st
    locks = [(540, 860)] + ([(540, 640)] if newdoor else [])
    for k, (lx, ly) in enumerate(locks):
        cv.circ(lx, ly, 70, (190, 186, 170))
        cv.circ(lx, ly, 58, (160, 156, 140))
        is_top = k == 1
        ang = 0 if (locked and not is_top) else math.pi / 2
        if is_top:
            ang = 0 if t > SHOT_AT.get("lock2", (0, 0))[0] + 3.0 else math.pi / 2
        dx, dy = 50 * math.cos(ang), 50 * math.sin(ang)
        cv.line([(lx - dx, ly - dy), (lx + dx, ly + dy)], (90, 86, 74), 26)
        if newdoor and is_top and t < SHOT_AT.get("lock2", (0, 0))[0] + 3.0:
            cv.circ(lx, ly, 88, None, outline=RED, w=6)
    cv.rect(700, 700, 760, 724, (190, 186, 170))              # chain
    for k in range(6):
        cv.circ(700 - k * 22, 712 + k * 14, 9, None, outline=(190, 186, 170), w=4)
    cv.rrect(500, 1080, 560, 1140, 10, (190, 186, 170))     # handle
    cv.rrect(520, 1090, 780, 1130, 18, (190, 186, 170))
    if hand:
        lx, ly = locks[0]
        cv.line([(lx + 400, ly + 520), (lx + 120, ly + 90)], HOODIE_D, 70)
        cv.line([(lx + 400, ly + 520), (lx + 120, ly + 90)], HOODIE, 60)
        cv.circ(lx + 80, ly + 50, 44, WHITE)
    if knock is not None:
        for kt in knock:
            if kt <= t < kt + 0.5:
                u = (t - kt) / 0.5
                cv.circ(540, 760, 80 + 260 * u, None, outline=(255, 255, 255, int(160 * (1 - u))), w=6)


def phone_screen(cv, t, msgs, header="Unknown number", lock_screen=False):
    box = m35.phone_frame(cv, 250, 300, 580, 1160)
    sx0, sy0, sx1, sy1 = box
    cx = (sx0 + sx1) / 2
    if lock_screen:
        cv.text((cx, sy0 + 220), "11:47", "interx", 120, WHITE)
        cv.text((cx, sy0 + 300), "Friday", "inters", 30, (180, 184, 210))
    else:
        cv.rect(sx0, sy0 + 60, sx1, sy0 + 200, (20, 22, 34))
        cv.circ(cx, sy0 + 112, 34, (70, 72, 90))
        cv.text((cx, sy0 + 114), "?", "interx", 38, (200, 200, 215))
        cv.text((cx, sy0 + 176), header, "inters", 26, (200, 202, 220))
    y = sy0 + (380 if lock_screen else 260)
    f = F("inters", 32 * SS)
    for t0, txt in msgs:
        if t < t0:
            continue
        p = eout((t - t0) / 0.2)
        lines = wrap(txt, f, (sx1 - sx0 - 120) * SS)
        bh = 40 + 44 * len(lines)
        bw = max(f.getlength(l) for l in lines) / SS + 60
        x0 = sx0 + 30
        yy = y + 30 * (1 - p)
        if lock_screen:
            cv.rrect(sx0 + 20, yy, sx1 - 20, yy + bh + 40, 24, (40, 44, 62, 230))
            cv.text((sx0 + 50, yy + 30), "Unknown Number", "interx", 24, WHITE, anchor="lm")
            for k, l in enumerate(lines):
                cv.text((sx0 + 50, yy + 74 + 44 * k), l, "inters", 30, (220, 222, 236), anchor="lm")
            y += bh + 60
        else:
            cv.rrect(x0, yy, x0 + bw * (0.7 + 0.3 * p), yy + bh, 30, GREY_B)
            if p > 0.6:
                for k, l in enumerate(lines):
                    cv.text((x0 + 30, yy + 42 + 44 * k), l, "inters", 32, WHITE, anchor="lm")
            y += bh + 26
    cv.rrect(sx0 + 24, sy1 - 110, sx1 - 24, sy1 - 40, 34, (26, 28, 42))
    cv.text((sx0 + 60, sy1 - 75), "Text message", "inters", 26, (100, 104, 130), anchor="lm")


def lobby(cv, t):
    cv.rect(0, 0, W, H, (54, 60, 104))
    cv.rect(0, 0, W, 300, (44, 48, 90))
    for k in range(3):
        cv.rect(80 + k * 330, 330, 300 + k * 330, 900, (150, 170, 220))
        cv.glow_rect(80 + k * 330, 330, 300 + k * 330, 900, LIGHT, 60)
    cv.text((540, 960), "RECEPTION", "interx", 46, (200, 206, 235), spacing=10)
    receptionist(cv, 640, 1500, s=0.9)
    cv.rrect(260, 1150, 1040, 1700, 20, (34, 36, 70))
    cv.rect(260, 1150, 1040, 1180, (90, 96, 140))
    cv.rect(700, 1020, 900, 1150, (20, 20, 30))        # monitor back
    cv.rect(790, 1150, 810, 1170, (20, 20, 30))
    cv.rect(0, 1700, W, H, (30, 32, 64))
    girl(cv, 170, 1960, s=1.05, back=True)


def floorplan(cv, t, i_plan):
    cv.rect(0, 0, W, H, (14, 16, 30))
    cv.rrect(60, 420, 1020, 1300, 24, (26, 28, 44), outline=(80, 84, 120), w=6)
    cv.rect(90, 450, 990, 1270, (230, 234, 242))
    cv.text((540, 490), "FLOOR 6 — RESIDENT PLAN", "interx", 28, (40, 44, 70))
    cv.rect(130, 820, 950, 900, (200, 204, 216))        # corridor
    cv.text((540, 862), "CORRIDOR          LIFT ▸", "inters", 22, (90, 94, 120))
    rooms = [("601", 130, 560), ("602", 410, 560), ("603", 690, 560), ("604B", 130, 920), ("604", 410, 920), ("605", 690, 920)]
    for lab, x, y in rooms:
        cv.rect(x, y, x + 260, y + 240, (244, 246, 250))
        cv.rect(x, y, x + 260, y + 240, None)
        cv.d.rectangle([x * SS, y * SS, (x + 260) * SS, (y + 240) * SS], outline=(60, 64, 90), width=3 * SS)
        cv.text((x + 130, y + 120), lab, "interx", 40, (40, 44, 70))
    if t >= chunk_t(i_plan, 0):
        cv.d.rectangle([410 * SS, 920 * SS, 670 * SS, 1160 * SS], outline=BLUE, width=8 * SS)
        cv.text((540, 1200), "YOU", "interx", 24, (40, 120, 200))
    if t >= chunk_t(i_plan, 1):
        cv.d.rectangle([130 * SS, 920 * SS, 390 * SS, 1160 * SS], outline=RED, width=8 * SS)
        cv.text((260, 1110), "VACANT", "interx", 30, RED)
    if t >= chunk_t(i_plan, 2):
        a = eout((t - chunk_t(i_plan, 2)) / 0.3)
        cv.rrect(160, 1320, 920, 1460, 18, (30, 10, 14, int(230 * a)), outline=RED + (int(255 * a),), w=4)
        cv.text((540, 1365), "PREVIOUS TENANT (604B)", "interx", 30, (255, 200, 200))
        cv.text((540, 1415), "MALE  ·  LEFT 8 MONTHS AGO", "inters", 28, WHITE)


def group_feed(cv, t, i_reply):
    box = m35.phone_frame(cv, 250, 300, 580, 1160)
    sx0, sy0, sx1, sy1 = box
    cv.rect(sx0, sy0 + 60, sx1, sy0 + 170, (24, 30, 60))
    cv.text((sx0 + 40, sy0 + 115), "Riverside Tower Residents", "interx", 26, WHITE, anchor="lm")
    def post_card(y, name, txt, sub="8 months ago", grey=False):
        lines = wrap(txt, F("inters", 28 * SS), (sx1 - sx0 - 100) * SS)
        hgt = 90 + 38 * len(lines)
        cv.rrect(sx0 + 20, y, sx1 - 20, y + hgt, 20, (30, 32, 48) if not grey else (24, 24, 30))
        cv.circ(sx0 + 60, y + 40, 20, (90, 96, 130) if not grey else (60, 60, 70))
        cv.text((sx0 + 92, y + 32), name, "interx", 24, WHITE if not grey else (130, 130, 140), anchor="lm")
        cv.text((sx0 + 92, y + 58), sub, "inters", 18, (130, 134, 160), anchor="lm")
        for k, l in enumerate(lines):
            cv.text((sx0 + 50, y + 100 + 38 * k), l, "inters", 28, (220, 222, 236) if not grey else (130, 130, 140), anchor="lm")
        return y + hgt + 20
    y = post_card(sy0 + 190, "Maria (5th floor)", "Has anyone seen Daniel from 604? His family has been trying to contact him.")
    if t >= chunk_t(i_reply, 1) - 0.1:
        y = post_card(y, "Tom K.", "I saw him by the lift last night.")
        cv.d.rectangle([(sx0 + 20) * SS, (y - 140) * SS, (sx1 - 20) * SS, (y - 20) * SS], outline=LIME, width=4 * SS)
    if t >= chunk_t(i_reply, 1) + 1.0:
        post_card(y, "Deleted account", "Please stop talking about Daniel. He's gone.", grey=True)


def xmas_photo(cv, t, t_comment):
    cv.rect(0, 0, W, H, (14, 16, 30))
    cv.rect(60, 300, 1020, 1300, (240, 238, 230))
    x0, y0, x1, y1 = 90, 330, 990, 1180
    cv.rect(x0, y0, x1, y1, (36, 34, 70))
    cv.rect(x0, y0 + 600, x1, y1, (50, 40, 70))
    for k in range(26):                                  # fairy lights
        x = x0 + 20 + k * 34
        y = y0 + 60 + 30 * math.sin(k * 0.7)
        col = [RED, LIME, BLUE, WHITE][k % 4]
        cv.circ(x, y, 7, col)
        cv.glow(x, y, 26, col, 160)
    cv.poly([(230, 900), (330, 600), (430, 900)], (40, 110, 70))   # tree
    cv.rect(320, 900, 340, 950, (80, 60, 50))
    for k, x in enumerate((420, 520, 620)):             # party guests
        pal = dict(top=[(150, 60, 70), (60, 90, 150), (90, 120, 80)][k], top_d=(40, 40, 60), pants=(40, 40, 60),
                   rim=(70, 70, 100), hood=False, hair=k != 1, glasses=False)
        m35.you_stand(cv, x, 1130, s=0.42, eyes=True, pal=pal)
    cv.rect(800, 560, 960, 1150, (24, 26, 50))           # lift at the far end
    cv.rect(812, 590, 948, 1150, (130, 136, 166))
    coat_man(cv, 880, 1150, s=0.45)
    cv.text((540, 1240), "Christmas party! 🎄", "inters", 32, (60, 60, 70))
    cv.rect(60, 1320, 1020, 1520, (30, 32, 48))
    cv.circ(120, 1380, 26, (90, 96, 130))
    cv.text((160, 1370), "Uploaded by Daniel (604)", "interx", 30, WHITE, anchor="lm")
    cv.text((160, 1410), "8 months ago", "inters", 22, (130, 134, 160), anchor="lm")
    if t >= t_comment:
        a = int(255 * eout((t - t_comment) / 0.25))
        cv.rrect(100, 1450, 760, 1510, 26, GREY_B + (a,))
        cv.text((130, 1480), "1 comment:  You missed one.", "interx", 28, (255, 210, 210, a), anchor="lm")


def cctv_scene(cv, t, door_open, girl_out, man_in_door):
    hallway(cv, t, man=False, door_open=door_open, girl_out=girl_out, man_in_door=man_in_door)


def cctv_post(img, t, label="CAM 06  ·  FLOOR 6"):
    g = img.convert("L").convert("RGB")
    arr = np.asarray(g).astype(np.float32)
    arr = arr * np.array([0.75, 1.0, 0.82]) * 0.95 + 8
    arr[::4] *= 0.82
    noise = np.random.default_rng(int(t * 30)).normal(0, 9, (H // 2, W // 2))
    arr += np.repeat(np.repeat(noise, 2, 0), 2, 1)[..., None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img, "RGBA")
    secs = int(3 + (t - SHOT_AT["cctv"][0]))
    d.text((60, 1520), f"{label}", font=F("mono", 34), fill=(230, 240, 230), anchor="lm")
    d.text((60, 1570), f"11:47:{secs:02d}", font=F("mono", 44), fill=(230, 240, 230), anchor="lm")
    if int(t * 2) % 2 == 0:
        d.ellipse([60, 330, 84, 354], fill=(232, 36, 46))
    d.text((96, 342), "REC", font=F("mono", 30), fill=(232, 36, 46), anchor="lm")
    return img


def wardrobe(cv, t, u):
    if u < 0.5:
        cv.rect(0, 0, W, H, (34, 36, 70))
        cv.rect(0, 1500, W, H, (26, 26, 52))
        cv.rect(200, 300, 880, 1520, (60, 50, 70))
        cv.rect(230, 330, 850, 1500, (16, 16, 30))
        cv.rect(250, 420, 830, 432, (140, 140, 160))
        for k in range(8):
            x = 290 + k * 70
            cv.line([(x, 432), (x, 470)], (140, 140, 160), 4)
            cv.poly([(x - 30, 470), (x + 30, 470), (x + 34, 860), (x - 34, 860)], [(80, 90, 140), (120, 60, 70), (60, 80, 70)][k % 3])
        cv.rect(390, 960, 690, 1490, (90, 94, 110))          # maintenance door
        cv.rect(400, 970, 680, 1480, (70, 74, 90))
        cv.poly([(400, 970), (560, 1000), (560, 1450), (400, 1480)], (6, 6, 12))
        cv.rect(640, 1210, 660, 1250, (180, 180, 190))
        cv.text((540, 1020), "SERVICE ACCESS", "interx", 20, (200, 200, 210))
    else:
        cv.rect(0, 0, W, H, (6, 6, 14))
        for k in range(12, 0, -1):                          # narrow passage
            f = k / 12
            w = lerp(60, 520, f ** 1.4)
            hgt = lerp(90, 900, f ** 1.4)
            cv.rect(540 - w, 960 - hgt, 540 + w, 960 + hgt, mix((50, 54, 80), (8, 8, 16), 1 - f))
            cv.rect(540 - w + 10, 960 - hgt + 10, 540 + w - 10, 960 + hgt - 10, mix((30, 32, 56), (6, 6, 12), 1 - f))
        cv.line([(40, 300), (480, 900)], (90, 94, 120), 12)
        cv.line([(1040, 340), (600, 900)], (90, 94, 120), 12)
        cv.rect(500, 900, 580, 1030, (90, 94, 110))
        cv.text((540, 930), "604B", "interx", 16, (230, 230, 240))
        cv.glow(540, 960, 90, LIGHT, 80)


def lair(cv, t, wall_close=False):
    cv.rect(0, 0, W, H, (28, 30, 50))
    cv.rect(0, 1400, W, H, (22, 22, 38))
    # photo wall
    for r in range(6):
        for c in range(5):
            x, y = 90 + c * 190, 180 + r * 190
            ang = (hrand(r * 5 + c, 4) - 0.5) * 0.2
            cv.rect(x, y, x + 150, y + 170, (236, 236, 228))
            cv.rect(x + 10, y + 10, x + 140, y + 130, (40, 44, 80))
            scene = (r * 5 + c) % 4
            hx, hy = x + 75, y + 60
            cv.ell(hx, hy + 36, 26, 26, HOODIE)
            cv.circ(hx, hy, 18, WHITE)
            cv.ell(hx, hy - 6, 22, 14, HAIR)
            if scene == 0:
                cv.rect(x + 20, y + 100, x + 130, y + 120, (90, 90, 120))   # bed
    if not wall_close:
        cv.rrect(80, 1420, 640, 1560, 30, (120, 124, 140))     # mattress
        cv.rrect(90, 1400, 260, 1460, 20, (160, 164, 180))
        cv.rect(760, 1350, 1000, 1540, (40, 42, 60))            # tv
        cv.rect(780, 1370, 980, 1500, (160, 180, 220))
        cv.glow_rect(780, 1370, 980, 1500, LIGHT, 140)
        for k in range(5):                                     # food containers
            cv.rect(680 + k * 18 - 10, 1600 + (k % 2) * 30, 680 + k * 18 + 30, 1640 + (k % 2) * 30, (200, 196, 180))


def wall_writing(cv, t, t_line):
    cv.rect(0, 0, W, H, (34, 36, 58))
    for k, ln in enumerate(["MON  7:40  BUS 41", "TUE  SHOPPING  18:30", "WED  SHIFT 9-5", "THU  LAUNDRY", "FRI  HOME BY 11"]):
        cv.text((180, 420 + k * 90), ln, "mono", 46, (210, 214, 230), anchor="lm")
        cv.line([(170, 452 + k * 90), (900, 452 + k * 90)], (70, 74, 100), 3)
    if t >= t_line:
        n = int(clamp((t - t_line) / 1.2) * 32)
        txt = "SHE ALWAYS LOCKS IT THREE TIMES."[:n]
        lines = ["SHE ALWAYS LOCKS", "IT THREE TIMES."]
        shown = 0
        for li, l in enumerate(lines):
            seg = txt[shown:shown + len(l) + (1 if li == 0 else 0)]
            shown += len(l) + 1
            x = 110
            for ci, ch in enumerate(seg.strip()):
                cv.text((x, 1060 + li * 150 + (hrand(ci + li * 40, 5) - 0.5) * 16), ch, "anton", 120, RED, anchor="lm")
                x += F("anton", 120 * SS).getlength(ch) / SS + 4


def polaroid(cv, t, t_zoom):
    cv.rect(0, 0, W, H, (16, 16, 30))
    cv.rect(110, 260, 970, 1420, (240, 240, 232))
    x0, y0, x1, y1 = 150, 300, 930, 1200
    cv.rect(x0, y0, x1, y1, (56, 60, 96))
    cv.rect(x0, y0 + 650, x1, y1, (44, 40, 64))
    cv.rect(560, 380, 900, 900, (130, 140, 170))          # mirror
    cv.rect(580, 400, 880, 880, (80, 88, 120))
    coat_man(cv, 720, 1060, s=0.62, rim=False)           # his reflection, right behind her shoulder
    cv.rect(560, 380, 900, 400, (130, 140, 170))
    cv.rect(560, 880, 900, 900, (130, 140, 170))
    cv.rect(0, 0, 560, 0, (0, 0, 0))
    girl(cv, 420, 1300, s=0.62, eyes=True, look=0.2, hold=lambda hx, hy: cv.rect(hx - 10, hy - 40, hx + 40, hy + 10, WHITE))
    cv.text((540, 1300), "this morning", "inters", 34, (60, 60, 70))
    if t >= t_zoom:
        a = int(255 * eout((t - t_zoom) / 0.3))
        cv.circ(720, 560, 120, None, outline=RED + (a,), w=8)


def two_doors(cv, t, turn):
    cv.rect(0, 0, W, H, (30, 34, 66))
    cv.rect(0, 1500, W, H, (24, 26, 50))
    cv.rect(80, 400, 420, 1500, (84, 92, 136))          # front door (locked)
    cv.circ(380, 950, 16, (190, 186, 170))
    cv.circ(380, 820, 22, (190, 186, 170))
    cv.circ(380, 700, 22, (190, 186, 170))
    cv.rect(660, 400, 1000, 1500, (24, 26, 48))          # the second door frame
    cv.rect(680, 420, 980, 1500, (70, 76, 116))
    cv.circ(940, 950, 16, (190, 186, 170))
    girl(cv, 520, 1880, s=0.95, eyes=turn > 0.3, look=turn * 0.9, back=turn < 0.3)


def open_door(cv, t, u):
    cv.rect(0, 0, W, H, (30, 34, 66))
    cv.rect(0, 1500, W, H, (24, 26, 50))
    cv.rect(260, 300, 820, 1520, (24, 26, 48))
    cv.rect(280, 320, 800, 1500, (4, 4, 10))             # open, dark
    cv.poly([(800, 320), (1000, 260), (1000, 1580), (800, 1500)], (70, 76, 116))   # door swung open
    a = int(90 * ease(u))
    coat_man(cv, 540, 1500, s=1.0, a=a, rim=False)
    cv.glow(540, 900, 300, (60, 70, 120), int(30 * u))


# ---------------------------------------------------------------- chapter cards, HUD, captions
CARDS = {"card1": ("CHAPTER 1", "THE MISSING LOCK"), "card2": ("CHAPTER 2", "APARTMENT 604"),
         "card3": ("CHAPTER 3", "THE PREVIOUS TENANT"), "card4": ("CHAPTER 4", "THE ROUTINE"),
         "card5": ("CHAPTER 5", "THE DOOR"), "card6": ("FINAL CHAPTER", "ONE MORE TIME")}


def draw_card(img, t, shot):
    t0, _ = SHOT_AT[shot]
    lt = t - t0
    lab, title = CARDS[shot]
    ov = Image.new("RGBA", (W, H), (4, 5, 16, 175))
    img.paste(Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"))
    d = ImageDraw.Draw(img, "RGBA")
    p = eout(lt / 0.22)
    f = F("interx", 46)
    pw, ph = (f.getlength(lab) + 70) * (0.6 + 0.4 * p), 82 * (0.6 + 0.4 * p)
    d.rounded_rectangle([W / 2 - pw / 2, 760 - ph / 2, W / 2 + pw / 2, 760 + ph / 2], radius=ph / 2, fill=(232, 36, 46, int(255 * p)))
    if p > 0.5:
        d.text((W / 2, 762), lab, font=F("interx", int(46 * (0.6 + 0.4 * p))), fill=WHITE, anchor="mm")
    fb = F("anton", 150)
    for i, ln in enumerate(wrap(title, fb, 960)):
        q = eout((lt - 0.12 - i * 0.12) / 0.3)
        if q > 0:
            y = 860 + i * 168 + 40 * (1 - q)
            d.text((W / 2 + 6, y + 8), ln, font=fb, fill=(0, 0, 0, int(200 * q)), anchor="mt")
            d.text((W / 2, y), ln, font=fb, fill=(246, 246, 250, int(255 * q)), anchor="mt")


HUD_STATES = [("card1", "NIGHT 1", "11:47 PM", "APT 604"), ("phone1", "NIGHT 1", "11:48 PM", "APT 604"),
              ("card2", "DAY 2", "9:12 AM", "APT 604"), ("card3", "NIGHT 2", "10:58 PM", "APT 604"),
              ("card4", "NIGHT 5", "11:47 PM", "APT 604"), ("card5", "DAY 6", "8:30 AM", "APT 604"),
              ("card6", "MONTHS LATER", "11:47 PM", "APT 1207")]


def hud_state(t):
    st = HUD_STATES[0]
    for s in HUD_STATES:
        if t >= SHOT_AT[s[0]][0]:
            st = s
    return st[1:]


def draw_hud(img, t):
    lab, clk, sub = hud_state(t)
    d = ImageDraw.Draw(img, "RGBA")
    pulse = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 4))
    d.ellipse([60, 101, 82, 123], fill=(232, 36, 46, int(255 * pulse)))
    d.text((96, 112), lab, font=F("interx", 34), fill=WHITE, anchor="lm")
    f = F("mono", 92)
    d.text((63, 143), clk, font=f, fill=(0, 0, 0, 140), anchor="lt")
    d.text((60, 140), clk, font=f, fill=WHITE, anchor="lt")
    x = 63
    for ch in sub:
        d.text((x, 262), ch, font=F("inters", 24), fill=(170, 174, 210), anchor="lm")
        x += F("inters", 24).getlength(ch) + 5


CAPS = []
for i, m in enumerate(VO):
    nxt = VO[i + 1]["start"] if i + 1 < len(VO) else 999
    have = False
    for c0, c1, cap in m["chunks"]:
        if not cap:
            continue
        for sub in cap.split("|"):
            pass
        subs = cap.split("|")
        span = (c1 - c0) / len(subs)
        wts = [max(3, len(s_.replace("*", "").replace("_", ""))) for s_ in subs]
        tot = sum(wts)
        tt = m["start"] + c0
        for s_, w_ in zip(subs, wts):
            d_ = (c1 - c0) * w_ / tot
            CAPS.append([tt, tt + d_, parse_chunk(s_)])
            tt += d_
        have = True
    if have:
        CAPS[-1][1] = min(m["start"] + m["dur"] + 0.35, nxt - 0.02)


def draw_captions(img, t, y=1340, size=112):
    lb.CAPS[:] = CAPS
    lb.draw_captions(img, t, y=y, size=size)


# ---------------------------------------------------------------- frame
def shot_at(t):
    for name, a, b in SHOTS:
        if a <= t < b:
            return name, a, b
    return SHOTS[-1]


def idx(shot, k=0):
    return items(shot)[k]["i"]


def peephole(img, r0=480):
    yy, xx = np.ogrid[0:H, 0:W]
    r = np.sqrt((xx - W / 2) ** 2 + (yy - 960) ** 2)
    m = np.clip((r - r0) / 40, 0, 1)
    arr = np.asarray(img).astype(np.float32) * (1 - m[..., None]) + np.array([4, 4, 10], np.float32) * m[..., None]
    return Image.fromarray(arr.astype(np.uint8))


def frame(t):
    shot, a, b = shot_at(t)
    lt, u = t - a, clamp((t - a) / max(0.01, b - a))
    cv = Cv()
    cam = (540, 960, 1.0)
    fl_a, shake, chrom, cap_y = 0.0, 0.0, 0, 1340
    post_fns, after = [], []

    if shot.startswith("card"):
        prev = {"card1": "hall", "card2": "recep", "card3": "group", "card4": "phone4", "card5": "wardrobe", "card6": "newhall"}[shot]
        if prev in ("hall", "newhall"):
            hallway(cv, t, man=(shot == "card1"))
        elif prev == "recep":
            lobby(cv, t)
        elif prev == "wardrobe":
            wardrobe(cv, t, 0.2)
        else:
            phone_screen(cv, t, [])
        cam = (540, 960, lerp(1.05, 1.12, u))
        after.append(lambda im: draw_card(im, t, shot))
        fl_a = 0.6 * (1 - lt / 0.16) if lt < 0.16 else 0
    elif shot == "hall":
        i_man = idx("hall", 1)
        hallway(cv, t, man=True, girl_at_door=True)
        cam = (lerp(560, 600, ease(u)), lerp(1060, 1000, ease(u)), lerp(1.0, 1.12, ease(u)))
        if t >= VO[i_man]["start"]:
            cam = (560, 1000, lerp(1.6, 1.75, prog(t, VO[i_man]["start"], b)))
    elif shot == "lock":
        i0 = idx("lock", 0)
        c0, c1 = chunk_t(i0, 1, 0), chunk_t(i0, 1, 1)
        third = (c1 - c0) / 3
        states = [(0, True), (c0, True), (c0 + third, False), (c0 + 2 * third, True)]
        door_inside(cv, t, states)
        cam = (540, 900, lerp(1.0, 1.25, ease(u)))
        for k in range(3):
            if c0 + k * third <= t < c0 + k * third + 0.06:
                shake = 3
    elif shot == "peep":
        i_open = idx("peep", 1)
        lo = clamp((t - VO[i_open]["start"]) / 0.8) if t < VO[i_open]["start"] + 2.0 else clamp(1 - (t - VO[i_open]["start"] - 2.0) / 0.8)
        hallway(cv, t, man=True, lift_open=lo)
        cam = (540, 930, lerp(1.25, 1.45, ease(u)))
        post_fns.append(lambda im: peephole(im))
    elif shot in ("phone1", "phone2", "phone3", "phone4"):
        msgs = []
        for s_ in ("phone1", "phone2", "phone3"):
            for m in items(s_):
                if m["voice"] == "him":
                    msgs.append((m["start"], m["text"]))
        if shot == "phone4":
            msgs = [(SHOT_AT["phone4"][0] + 0.3, "You didn't check the handle.")]
            for m in items("phone4"):
                if m["voice"] == "him":
                    msgs += [(m["start"], "You left the top lock."), (m["start"] + m["dur"] * 0.5, "You forgot the chain.")]
        phone_screen(cv, t, msgs, header="Unknown number" if shot != "phone4" else "Unknown number (new)")
        bz = shot == "phone1" and lt < 1.0 or any(abs(t - mt) < 0.25 for mt, _ in msgs)
        cam = (540 + (3 if bz and int(t * 30) % 2 else 0), 880, lerp(1.0, 1.06, u))
        cap_y = 1700
    elif shot == "knock":
        i0 = idx("knock", 0)
        k0 = chunk_t(i0, 0, 1) + 0.05
        knocks = [k0, k0 + 0.32, k0 + 0.64]
        door_inside(cv, t, [(0, True)], knock=knocks, hand=False)
        cam = (540, 800, lerp(1.1, 1.3, ease(u)))
        if any(k <= t < k + 0.08 for k in knocks):
            shake = 5
    elif shot == "peep2":
        hallway(cv, t, man=False)
        cam = (540, 930, lerp(1.25, 1.4, ease(u)))
        post_fns.append(lambda im: peephole(im))
    elif shot == "recep":
        lobby(cv, t)
        cam = (lerp(560, 600, u), 1100, lerp(1.0, 1.12, ease(u)))
    elif shot == "plan":
        floorplan(cv, t, idx("plan"))
        cam = (540, 900, lerp(1.0, 1.08, ease(u)))
        cap_y = 1640
    elif shot == "group":
        group_feed(cv, t, idx("group", 1))
        cam = (540, 880, lerp(1.0, 1.05, u))
        cap_y = 1700
    elif shot == "xmas":
        i_dark = idx("xmas", 0)
        xmas_photo(cv, t, VO[idx("xmas", 2)]["start"])
        zt = chunk_t(i_dark, 1, 0)
        if t < zt:
            cam = (540, 800, lerp(1.0, 1.05, prog(t, a, zt)))
        elif t < VO[idx("xmas", 1)]["start"]:
            z = eout(prog(t, zt, zt + 0.8))
            cam = (lerp(540, 880, z), lerp(800, 900, z), lerp(1.05, 3.0, z))
        else:
            cam = (540, 1100, 1.0)
            cap_y = 1700
    elif shot in ("cctv", "cctv2"):
        if shot == "cctv":
            i0 = idx("cctv")
            dop = prog(t, chunk_t(i0, 3, 0), chunk_t(i0, 3, 0) + 0.8)
            cctv_scene(cv, t, dop, None, 0)
            cam = (800, 1300, 1.25)
        else:
            i0 = idx("cctv2")
            go = prog(t, a, a + 1.4)
            md = prog(t, chunk_t(i0, 2, 0), chunk_t(i0, 3, 0))
            cctv_scene(cv, t, 1.0, go, md)
            zt = chunk_t(i0, 3, 0)
            if t < zt:
                cam = (800, 1300, 1.25)
            else:
                z = eout(prog(t, zt, zt + 0.6))
                cam = (lerp(800, 930, z), lerp(1300, 1100, z), lerp(1.25, 2.4, z))
        post_fns.append(lambda im: cctv_post(im, t))
    elif shot == "wardrobe":
        i0 = idx("wardrobe")
        sw = chunk_t(i0, 2, 0)
        wardrobe(cv, t, 0.0 if t < sw else 1.0)
        if t < sw:
            cam = (540, lerp(1000, 1200, ease(prog(t, a, sw))), lerp(1.0, 1.4, ease(prog(t, a, sw))))
        else:
            cam = (540, 960, lerp(1.0, 1.8, ease(prog(t, sw, b))))
    elif shot == "lair":
        lair(cv, t)
        cam = (540, lerp(1100, 800, ease(u)), lerp(1.0, 1.3, ease(u)))
    elif shot == "wall":
        i0 = idx("wall")
        wall_writing(cv, t, chunk_t(i0, 1, 0))
        cam = (540, lerp(800, 1100, ease(u)), lerp(1.0, 1.1, u))
        cap_y = 1640
    elif shot == "polaroid":
        i0 = idx("polaroid")
        zt = chunk_t(i0, 2, 0)
        polaroid(cv, t, zt)
        if t < zt:
            cam = (540, 860, lerp(1.0, 1.1, prog(t, a, zt)))
        else:
            z = eout(prog(t, zt, zt + 0.6))
            cam = (lerp(540, 720, z), lerp(860, 640, z), lerp(1.1, 2.3, z))
            shake = 4 if t < zt + 0.1 else 0
    elif shot == "newhall":
        i_n = idx("newhall", 1)
        newpal = dict(wall=(58, 66, 110), side=(44, 50, 92), floor=(40, 40, 70), ceil=(24, 26, 54), door=(84, 92, 136))
        no = prog(t, chunk_t(idx("newhall"), 3, 0), chunk_t(idx("newhall"), 3, 0) + 1.2)
        lo = clamp(prog(t, chunk_t(idx("newhall"), 3, 0) - 0.4, chunk_t(idx("newhall"), 3, 0) + 0.2))
        hallway(cv, t, man=False, lift_open=lo, girl_at_door=True, pal=newpal, door_no="1207",
                neighbour_out=no if t >= chunk_t(idx("newhall"), 3, 0) else None)
        cam = (lerp(560, 520, u), lerp(1060, 1100, u), lerp(1.0, 1.12, ease(u)))
        if t >= VO[i_n]["start"]:
            cam = (480, 1050, lerp(1.6, 1.7, prog(t, VO[i_n]["start"], b)))
    elif shot == "lock2":
        i0 = idx("lock2")
        c0, c1 = chunk_t(i0, 1, 0), chunk_t(i0, 1, 1)
        third = (c1 - c0) / 3
        states = [(0, False), (c0, True), (c0 + third, False), (c0 + 2 * third, True)]
        door_inside(cv, t, states, newdoor=True)
        cam = (540, 860, lerp(1.0, 1.2, ease(u)))
        if t >= VO[idx("lock2", 1)]["start"]:
            cam = (540, 600, lerp(1.6, 1.8, prog(t, VO[idx("lock2", 1)]["start"], b)))
    elif shot == "phone5":
        m = items("phone5")[0]
        msgs = [(m["start"], "You can stop looking for me now."), (m["start"] + m["chunks"][1][0], "I'm not in the building anymore.")]
        phone_screen(cv, t, msgs, lock_screen=True)
        cam = (540, 880, lerp(1.0, 1.06, u))
        cap_y = 1700
    elif shot == "twodoors":
        i0 = idx("twodoors")
        turn = prog(t, chunk_t(i0, 2, 0), chunk_t(i0, 2, 0) + 0.9)
        two_doors(cv, t, turn)
        cam = (lerp(420, 700, ease(turn)), 1000, lerp(1.05, 1.2, u))
    elif shot == "open":
        open_door(cv, t, u)
        cam = (540, 960, lerp(1.0, 1.25, ease(u)))
        fl_a = 0.8 * (1 - lt / 0.12) if lt < 0.12 else 0
        shake = 5 if lt < 0.2 else 0
    elif shot == "outro":
        return outro_frame(t, a)

    img = camera(cv, *cam)
    for fn in post_fns:
        img = fn(img)
    if shake:
        img = ImageChops.offset(img, int((hrand(int(t * 60), 3) - 0.5) * 2 * shake), int((hrand(int(t * 60), 4) - 0.5) * 2 * shake))
    if shot in ("cctv2", "polaroid", "open", "twodoors", "wall", "lair"):
        img = tilt_img(img, 0.6 * math.sin(t * 0.7) + 0.3 * math.sin(t * 1.9))
    if chrom:
        img = chroma(img, chrom)
    if lt < 0.08 and shot not in ("outro",):
        img = vhs(img, t, 16)
    for fn in after:
        fn(img)
    img = post(img, t)
    draw_hud(img, t)
    if not shot.startswith("card"):
        draw_captions(img, t, y=cap_y)
    return flash(img, fl_a)


def outro_frame(t, t0):
    lt = t - t0
    img = Image.new("RGB", (W, H), (5, 5, 14))
    gl = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(gl)
    q = eout(prog(t, t0 + 0.3, t0 + 0.9))
    flick = 1.0 if hrand(int(t * 15), 19) > 0.08 else 0.5
    a = q * flick
    gd.text((540, 930), "604B", font=F("anton", 300), fill=(int(232 * a), int(30 * a), int(40 * a)), anchor="mm")
    gl = gl.filter(ImageFilter.GaussianBlur(28))
    img = ImageChops.add(ImageChops.add(img, gl), gl)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((540, 930), "604B", font=F("anton", 300), fill=(255, 60, 66, int(255 * a)), anchor="mm")
    spaced(d, (540, 690), "THE MAN BY THE LIFT", "inters", 34, (200, 204, 230, int(255 * eout(prog(t, t0 + 0.1, t0 + 0.6)))), 14)
    d.text((540, 1160), "11:47 PM", font=F("mono", 70), fill=(220, 222, 240, int(255 * eout(prog(t, t0 + 0.8, t0 + 1.3)))), anchor="mm")
    q4 = eout(prog(t, t0 + 1.4, t0 + 1.8))
    if q4 > 0:
        pulse = 1 + 0.025 * math.sin(lt * 4)
        bw, bh = 600 * pulse, 120 * pulse
        d.rounded_rectangle([540 - bw / 2, 1400 - bh / 2, 540 + bw / 2, 1400 + bh / 2], radius=bh / 2, outline=(246, 246, 250, int(255 * q4)), width=5)
        spaced(d, (540, 1402), "FOLLOW FOR MORE", "interx", 44, (246, 246, 250, int(255 * q4)), 3)
    img = post(img, t)
    draw_hud(img, t)
    if lt < 0.6:
        img = Image.blend(Image.new("RGB", (W, H)), img, eout(lt / 0.6))
    if t > DUR - 0.6:
        img = Image.blend(img, Image.new("RGB", (W, H)), clamp((t - (DUR - 0.6)) / 0.6))
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
