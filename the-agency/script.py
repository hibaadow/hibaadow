# THE AGENCY — the creator's own script, word for word (captions show it exactly).
# SPOKEN fixes pronunciation only (numbers, names); captions keep the original text.
import re
RAW = [
    ("hook",    "This is why a lot of people are not okay with surrogacy.", {"not okay": "*", "surrogacy.": "_"}),
    ("signup",  "So back in 2024, a 26-year-old woman named Kayla decided that she was going to be a surrogate for a little bit of extra money through a surrogacy agency.", {"Kayla": "*", "surrogate": "_", "extra money": "*", "agency.": "_"}),
    ("couple",  "She gets paired with this couple, Sylvia and Guojun, who want a second child but are not able to conceive naturally.", {"Sylvia and Guojun,": "*", "second child": "_", "naturally.": "_"}),
    ("pregnant", "So Kayla moves forward with the surrogacy, she gets pregnant, and things start getting weird.", {"pregnant,": "_", "weird.": "*"}),
    ("intro",   "Also, I'm Kaelyn, a dark curiosity, so follow along for the rabbit holes I go down.", {"Kaelyn,": "*", "dark curiosity,": "_", "rabbit holes": "*"}),
    ("onread",  "So first, Kayla rarely hears from this couple.", {"rarely hears": "*"}),
    ("noshow",  "She's carrying their child, she's going to appointment, she texts them updates, they never show up to the appointments and they rarely reach out to her.", {"updates,": "_", "never show up": "*", "rarely reach out": "_"}),
    ("onread2", "It seems like they just don't care about being involved.", {"don't care": "*"}),
    ("posting", "But also, Kayla's tracking her journey on TikTok, and other women start reaching out to her", {"TikTok,": "_", "other women": "*"}),
    ("dm",      "and they say, \"Hey, this is gonna sound so weird, but I think I'm carrying a baby for the same couple that you are.\"", {"weird,": "_", "same couple": "*"}),
    ("more",    "And it's not just one other woman, it's like six other women.", {"six other women.": "*"}),
    ("owners",  "So some of these women start to dig a little bit deeper and they find out that the agency that organised the surrogacy was actually founded by this couple.", {"dig": "_", "agency": "_", "founded by this couple.": "*"}),
    ("police",  "That's when the police get involved.", {"police": "*"}),
    ("arcadia", "They find out that the couple is living in Arcadia, California.", {"Arcadia, California.": "_"}),
    ("cribs",   "They show up just to investigate, and they find over 15 babies, all under the age of 3 years old, inside of their house.", {"over 15 babies,": "*", "3 years old,": "_"}),
    ("nightmare", "And what was going on in the house was the stuff of nightmares.", {"nightmares.": "*"}),
    ("chaos",   "Think cribs everywhere, kids running around, and not enough adults to look after all of them.", {"cribs everywhere,": "_", "not enough adults": "*"}),
    ("arrest",  "The story is still unfolding. That couple was actually just recently arrested, so we're gonna get a lot more information on what was really happening there.", {"still unfolding.": "_", "arrested,": "*", "really happening": "_"}),
    ("end",     "But The Journey by The New Yorker is a podcast that's actually covering it this season. That's where a lot of this information comes from, so check it out if you wanna learn more.", {"The Journey": "*", "The New Yorker": "_", "check it out": "*"}),
]
SAY = {"2024": "twenty twenty-four", "26-year-old": "twenty-six-year-old", "Guojun": "Gwo-jun", "Kaelyn": "Kay-lin", "15": "fifteen", "3": "three"}


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
