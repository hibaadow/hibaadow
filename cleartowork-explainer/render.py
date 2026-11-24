"""ClearToWork explainer (57 s, 1080x1920): original script and visuals, the house character and voice.

usage: python render.py <start_frame> <end_frame> <out.mp4>  |  python render.py --still <t> <out.png>"""
import importlib.util, json, math, os, subprocess, sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
am = _load("am", os.path.join(HERE, "..", "2am-delivery", "render.py"))       # shared toolkit (captions, cards, character)
m35, lb = am.m35, am.lb
Cv, camera, F, post = lb.Cv, lb.camera, lb.F, lb.post
clamp, lerp, ease, eout, prog = lb.clamp, lb.lerp, lb.ease, lb.eout, lb.prog
W, H, FPS, SS = lb.W, lb.H, lb.FPS, lb.SS
BG, WHITE, GREY, RED, BLUE, AMBER, GREEN, PAPER, INK = am.BG, am.WHITE, am.GREY, am.RED, am.BLUE, am.AMBER, am.GREEN, am.PAPER, am.INK
card, slide, bubble, bg = am.card, am.slide, am.bubble, am.bg
you_stand, you_sit = m35.you_stand, m35.you_sit

TL = json.load(open(os.path.join(HERE, "timeline.json")))
LINES = TL["lines"]; DUR = TL["duration"]
am.LINES = LINES
chunk_t = am.chunk_t
GO = (31, 157, 85)
HIVIS = dict(top=(255, 200, 40), top_d=(215, 160, 20), pants=(44, 46, 58), rim=(80, 84, 110), hood=False, hair=False, glasses=False)


def logo(cv, cx, cy, s=1.0, a=1.0):
    r = 46 * s
    cv.rrect(cx - 290 * s - r, cy - r, cx - 290 * s + r, cy + r, 18 * s, GO)
    cv.line([(cx - 290 * s - 20 * s, cy + 2 * s), (cx - 290 * s - 4 * s, cy + 18 * s), (cx - 290 * s + 24 * s, cy - 16 * s)], WHITE, 10 * s)
    cv.text((cx - 220 * s, cy), "ClearToWork", "interx", 92 * s, WHITE, anchor="lm")


def site(cv, t, open_u=0.0, sign_ok=False):
    cv.rect(0, 0, W, H, (24, 28, 44)); cv.glow_ell(800, 300, 600, 300, (255, 190, 120), 50)   # dawn
    cv.rect(0, 1240, W, H, (60, 56, 52))
    for k in range(5):                                                                 # crane
        cv.line([(780, 300), (780, 1000)], (230, 180, 40), 14)
    cv.line([(560, 320), (1040, 320)], (230, 180, 40), 12); cv.line([(780, 300), (980, 1000)], (60, 60, 80), 3)
    for x in range(0, W, 120):                                                          # hoarding
        if 380 < x < 700:
            continue
        cv.rect(x, 900, x + 116, 1240, (36, 90, 60)); cv.rect(x, 900, x + 116, 912, (230, 230, 230))
    gw = 320 * (1 - open_u)                                                             # gate leaves
    cv.rect(380, 900, 380 + gw / 2, 1240, (180, 180, 190)); cv.rect(700 - gw / 2, 900, 700, 1240, (180, 180, 190))
    for x in range(390, int(380 + gw / 2), 22): cv.line([(x, 910), (x, 1230)], (120, 120, 130), 4)
    for x in range(int(700 - gw / 2) + 10, 700, 22): cv.line([(x, 910), (x, 1230)], (120, 120, 130), 4)
    col = GO if sign_ok else (200, 30, 44)
    cv.rrect(420, 760, 660, 880, 16, col)
    cv.text((540, 800), "ALL CLEAR" if sign_ok else "NO ENTRY", "interx", 38, WHITE)
    cv.text((540, 848), "cards checked" if sign_ok else "without valid cards", "inters", 24, WHITE)


def crew(cv, x0, fy, walk=0.0, t=0.0):
    for k in range(3):
        x = x0 + k * 120 + walk
        you_stand(cv, x, fy - (k % 2) * 6, s=0.5, eyes=True, look=0.3, pal=HIVIS)


# ---------------------------------------------------------------- scenes
def sc_gate(cv, t, lt, i):
    site(cv, t)
    you_stand(cv, 230, 1330, s=0.8, eyes=True, look=0.6)
    crew(cv, 330, 1300)
    return (540, 1000, lerp(1.0, 1.08, ease(prog(lt, 0, 4))))


def sc_papers(cv, t, lt, i):
    bg(cv, RED, 34)
    items = [("Safe Pass · D. Murphy", "EXPIRED", RED, 0), ("Insurance certificate", "REQUESTED", AMBER, 1), ("RAMS · Site 2", "DUE FRIDAY", RED, 2)]
    for k, (a, b, c, ci) in enumerate(items):
        u = prog(t, chunk_t(i, min(ci * 2, len(LINES[i]["chunks"]) - 1)), chunk_t(i, min(ci * 2, len(LINES[i]["chunks"]) - 1)) + 0.35)
        if u <= 0: continue
        y = 470 + k * 240 + slide(u)
        card(cv, 110, y, 970, y + 200)
        cv.text((150, y + 70), a, "interx", 44, WHITE, anchor="lm")
        cv.rrect(150, y + 115, 150 + 30 + F("interx", 34).getlength(b), y + 170, 14, c)
        cv.text((165, y + 142), b, "interx", 34, WHITE, anchor="lm")
    return (540, 960, 1.0)


def sc_night(cv, t, lt, i):
    cv.rect(0, 0, W, H, (14, 14, 24)); cv.glow_ell(560, 900, 500, 400, (255, 220, 160), 50)
    cv.rect(0, 1200, W, H, (30, 26, 30))
    cv.rect(260, 1080, 900, 1110, (110, 80, 56)); cv.rect(290, 1110, 310, 1300, (90, 64, 44)); cv.rect(850, 1110, 870, 1300, (90, 64, 44))
    for k in range(9):                                                                  # paper pile
        cv.rect(560 + (k % 2) * 8, 1060 - k * 16, 760 + (k % 3) * 6, 1076 - k * 16, (236, 232, 220))
    you_sit(cv, 420, 720, eyes=True, look=0.6, pal=m35.HOODIE_PAL)
    cv.rrect(640, 380, 860, 470, 16, (30, 30, 44)); cv.text((750, 425), "22:47", "mono", 56, AMBER)
    return (540, 960, lerp(1.0, 1.06, ease(prog(lt, 0, 4))))


def sc_brand(cv, t, lt, i):
    bg(cv, GREEN, 50)
    q = eout(prog(lt, 0.0, 0.5))
    logo(cv, 540 + 40, 900 + slide(q, 40), s=1.0)
    cv.glow_ell(540, 900, 520, 140, GO, int(80 * q))
    return (540, 960, 1.0)


def checklist_row(cv, y, label, ok, u):
    if u <= 0: return
    y += slide(u, 30)
    card(cv, 110, y, 970, y + 120, r=22)
    cv.text((150, y + 60), label, "inters", 38, WHITE, anchor="lm")
    c = GO if ok else (200, 30, 44)
    cv.circ(910, y + 60, 32, c)
    if ok:
        cv.line([(894, y + 60), (906, y + 72), (928, y + 48)], WHITE, 7)
    else:
        cv.line([(898, y + 48), (922, y + 72)], WHITE, 7); cv.line([(898, y + 72), (922, y + 48)], WHITE, 7)


def sc_find(cv, t, lt, i):
    bg(cv, BLUE, 26)
    cv.text((540, 400), "MAIN CONTRACTOR CHECK", "mono", 32, GREY)
    rows = [("Safety Statement", True), ("Insurance at their minimum", False), ("Safe Pass · 6 workers", False), ("CSCS cards", True), ("Site induction", False), ("Equipment inspections", True)]
    for k, (a, ok) in enumerate(rows):
        checklist_row(cv, 470 + k * 140, a, ok, prog(lt, 0.3 + k * 0.35, 0.6 + k * 0.35))
    return (540, 960, 1.0)


def sc_chase(cv, t, lt, i):
    bg(cv, BLUE, 26)
    nc = len(LINES[i]["chunks"])
    y = 380
    y = bubble(cv, 120, y, "Hi Declan, can you send a photo of your new Safe Pass?", prog(t, chunk_t(i, 1), chunk_t(i, 1) + 0.3), who="TO WORKER", c=(40, 90, 160), size=38, maxw=760)
    y = bubble(cv, 200, y, "[photo] New card attached", prog(t, chunk_t(i, 1) + 1.0, chunk_t(i, 1) + 1.3), who="DECLAN", size=38, maxw=700)
    y = bubble(cv, 120, y, "Insurance certificate received from your broker", prog(t, chunk_t(i, min(3, nc - 1)), chunk_t(i, min(3, nc - 1)) + 0.3), who="BROKER", c=(52, 44, 60), size=38, maxw=760)
    u = prog(t, chunk_t(i, nc - 2), chunk_t(i, nc - 2) + 0.35)
    if u > 0:
        yy = y + slide(u)
        card(cv, 120, yy, 960, yy + 220)
        cv.text((160, yy + 60), "Safe Pass course · Tue 2 Dec", "interx", 38, WHITE, anchor="lm")
        cv.text((160, yy + 110), "€149 · needs your OK", "inters", 32, GREY, anchor="lm")
        tap = prog(t, chunk_t(i, nc - 1) + 0.5, chunk_t(i, nc - 1) + 0.8)
        cv.rrect(160, yy + 140, 420, yy + 200, 30, GO if tap >= 1 else (60, 64, 90))
        cv.text((290, yy + 170), "Approved" if tap >= 1 else "Approve", "interx", 32, WHITE)
    return (540, 960, 1.0)


def sc_check(cv, t, lt, i):
    bg(cv, GREEN, 30)
    u = prog(lt, 0.1, 0.5); y = 420 + slide(u)
    cv.rrect(250, y, 830, y + 360, 30, (230, 236, 246))
    cv.rect(250, y + 230, 830, y + 300, (40, 90, 160))
    cv.text((290, y + 70), "SAFE PASS", "interx", 46, INK, anchor="lm")
    cv.text((290, y + 130), "D. Murphy", "inters", 36, (70, 70, 80), anchor="lm")
    cv.text((290, y + 175), "Valid to 2030", "inters", 30, (70, 70, 80), anchor="lm")
    q = eout(prog(t, chunk_t(i, 1), chunk_t(i, 1) + 0.3))
    if q > 0:
        im = Image.new("RGBA", (600, 200), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle([12, 12, 588, 188], radius=12, outline=(31, 157, 85, 240), width=10)
        d.text((300, 102), "CHECKED", font=F("anton", int(lerp(140, 100, q))), fill=(31, 157, 85, 245), anchor="mm")
        im = im.rotate(-8, expand=True).resize((int(im.width * 0.8 * SS), int(im.height * 0.8 * SS)))
        cv.im.paste(im, (int(640 * SS - im.width / 2), int((y + 300) * SS - im.height / 2)), im)
    nc = len(LINES[i]["chunks"])
    u2 = prog(t, chunk_t(i, max(0, nc - 3)), chunk_t(i, max(0, nc - 3)) + 0.35)
    if u2 > 0:
        yy = 1000 + slide(u2)
        card(cv, 150, yy, 930, yy + 160)
        cv.text((190, yy + 55), "Safety Statement v3", "interx", 38, WHITE, anchor="lm")
        cv.text((190, yy + 110), "Signed off by a qualified safety professional", "inters", 28, (120, 220, 160), anchor="lm")
    return (540, 960, 1.0)


def sc_ready(cv, t, lt, i):
    bg(cv, GREEN, 30)
    u = prog(lt, 0.1, 0.5); y = 400 + slide(u)
    card(cv, 130, y, 950, y + 560)
    cv.text((170, y + 70), "Weekly summary", "interx", 46, WHITE, anchor="lm")
    cv.text((170, y + 170), "14 / 14", "anton", 120, (120, 220, 160), anchor="lm")
    cv.text((170, y + 260), "requirements in date", "inters", 34, GREY, anchor="lm")
    for k, txt in enumerate(("Glenmara site: ready", "Harbour site: ready", "Pack ready for main contractor")):
        cv.circ(190, y + 350 + k * 60, 16, GO); cv.text((225, y + 350 + k * 60), txt, "inters", 32, WHITE, anchor="lm")
    return (540, 960, 1.0)


def sc_gate2(cv, t, lt, i):
    op = ease(prog(lt, 0.0, 0.8))
    site(cv, t, open_u=op, sign_ok=True)
    walk = ease(prog(lt, 0.6, 2.2)) * 260
    you_stand(cv, 230, 1330, s=0.8, eyes=True, look=0.6)
    crew(cv, 330, 1300, walk=walk)
    return (540, 1000, 1.0)


def sc_cta(cv, t, lt, i):
    bg(cv, GREEN, 40)
    logo(cv, 540 + 40, 640, s=0.95)
    cv.text((540, 760), "Your crew, clear to work.", "inters", 44, GREY)
    u = prog(t, chunk_t(i, min(2, len(LINES[i]["chunks"]) - 1)), chunk_t(i, min(2, len(LINES[i]["chunks"]) - 1)) + 0.35)
    if u > 0:
        y = 880 + slide(u)
        cv.rrect(170, y, 910, y + 130, 65, (255, 207, 51))
        cv.text((540, y + 65), "Free 30-day pilot", "interx", 54, INK)
        cv.text((540, y + 210), "cleartowork.ie", "interx", 64, WHITE)
    you_stand(cv, 540, 1880, s=0.5, eyes=True, look=0.0)
    return (540, 960, 1.0)


SCENES = {"gate": sc_gate, "papers": sc_papers, "night": sc_night, "brand": sc_brand, "find": sc_find, "chase": sc_chase,
          "check": sc_check, "ready": sc_ready, "gate2": sc_gate2, "cta": sc_cta}


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
    if l["scene"] != "cta":
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
