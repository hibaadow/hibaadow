# ClearToWork explainer: original script.
# SPOKEN fixes pronunciation only (numbers, names); captions keep the original text.
import re
RAW = [
    ("gate",    "It's seven A.M. Your crew is at the gate, and they're not getting on site.", {"seven": "*", "not getting on site.": "*"}),
    ("papers",  "One Safe Pass expired last week. The main contractor wants your insurance cert. And a new RAMS, by Friday.", {"expired": "*", "insurance cert.": "_", "by Friday.": "*"}),
    ("night",   "So you spend your evenings chasing cards and paperwork, instead of running your business.", {"evenings": "_", "chasing": "*", "running your business.": "_"}),
    ("brand",   "That's where ClearToWork comes in.", {"ClearToWork": "_"}),
    ("find",    "We check your crew and documents against what each main contractor needs, and show you every gap.", {"each main contractor": "_", "every gap.": "*"}),
    ("chase",   "Then we chase it for you. New card photos from your workers. Certificates from your broker. Training lined up, with your OK first.", {"chase": "_", "OK": "*"}),
    ("check",   "Every card and cert is checked before anything is closed. And a qualified safety professional signs off your safety documents.", {"checked": "_", "qualified": "*", "professional": "*"}),
    ("ready",   "You get a weekly summary, and a record you can show any main contractor.", {"weekly summary,": "_", "any main contractor.": "*"}),
    ("gate2",   "Next time, your crew walks straight on site.", {"straight on site.": "_"}),
    ("cta",     "ClearToWork. Your crew, clear to work. Free sixty-day pilot for Irish subcontractors, at cleartowork dot I E.", {"ClearToWork.": "_", "clear to work.": "*", "Free sixty-day pilot": "*"}),
]
SAY = {"ClearToWork": "Clear To Work"}


def mark(cap, hl):
    for k, m in hl.items():
        cap = cap.replace(k, " ".join(m + w + m for w in k.split()), 1) if k in cap else cap
    return cap


def chunks(text, hl, n=5):
    words = text.split(); out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= n or (len(cur) >= 3 and re.search(r"[.,?!\"]$", w)):
            out.append(" ".join(cur)); cur = []
    if cur: out.append(" ".join(cur))
    res = []
    for c in out:
        sp = c
        for k, v in SAY.items():
            sp = re.sub(rf"\b{re.escape(k)}\b", v, sp)
        res.append((sp, c))
    # highlights on the caption side (phrase may span chunks: mark word by word)
    words_hl = {}
    for k, m in hl.items():
        for w in k.split(): words_hl[w] = m
    res2 = []
    for sp, c in res:
        cw = [(words_hl[w] + w + words_hl[w]) if w in words_hl else w for w in c.split()]
        res2.append((sp, " ".join(cw)))
    return res2


LINES = [(sc, chunks(txt, hl)) for sc, txt, hl in RAW]
