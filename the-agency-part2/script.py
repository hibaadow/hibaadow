# THE AGENCY, Part 2 — what happened next. Facts only (LA County DA, CBS, ABC7, CNN, Courthouse News); allegations marked.
# SPOKEN fixes pronunciation only (numbers, names); captions keep the original text.
import re
RAW = [
    ("hook2",    "Remember the couple with all the surrogate babies? Here's what happened next.", {"surrogate babies?": "*", "happened next.": "_"}),
    ("recap",    "Quick recap: Kayla was a surrogate for Sylvia and Guojun, and then found out other women were carrying babies for them too.", {"Kayla": "_", "Sylvia and Guojun,": "*", "other women": "*"}),
    ("correct",  "And one correction from part one: the children in that house weren't all babies. They were aged from two months to thirteen years.", {"correction": "_", "two months": "*", "thirteen years.": "*"}),
    ("hospital", "It started back in 2025, when a young child in the couple's care ended up in hospital with a head injury, and the hospital called the police.", {"2025,": "_", "head injury,": "*", "called the police.": "_"}),
    ("found",    "Police went to their mansion in Arcadia and found fifteen children living there.", {"Arcadia": "_", "fifteen children": "*"}),
    ("cameras",  "One report says the house had thirty-two cameras inside.", {"thirty-two cameras": "*"}),
    ("released", "The couple were arrested, but released a few days later without charges.", {"arrested,": "_", "without charges.": "*"}),
    ("custody",  "In the end, twenty-one children were taken into protective custody.", {"twenty-one children": "*", "protective custody.": "_"}),
    ("business", "And here's the twist: the couple allegedly ran their own surrogacy company out of that same house.", {"twist:": "_", "surrogacy company": "*", "same house.": "_"}),
    ("lies",     "Prosecutors say they told at least two surrogates that Sylvia was struggling to get pregnant.", {"Prosecutors": "_", "two surrogates": "*", "struggling to get pregnant.": "_"}),
    ("charged",  "Then, in October 2026, the Los Angeles District Attorney finally charged them, with conspiracy to commit child abuse.", {"October 2026,": "_", "charged them,": "*", "child abuse.": "*"}),
    ("alleged",  "Prosecutors allege that fifteen of the sixteen children living in that home were repeatedly abused.", {"allege": "_", "fifteen of the sixteen": "*", "repeatedly abused.": "*"}),
    ("witness",  "Sylvia is also accused of trying to stop witnesses from talking.", {"stop witnesses": "*"}),
    ("plea",     "They both pleaded not guilty, and Guojun's lawyer denies the allegations.", {"not guilty,": "*", "denies": "_"}),
    ("bail",     "Bail was set at twenty million dollars each, and a judge refused to lower it.", {"twenty million dollars": "*", "refused": "_"}),
    ("nanny",    "And the nanny? There's a warrant out for her arrest, and police have been looking for her.", {"nanny?": "_", "warrant": "*", "looking for her.": "_"}),
    ("mothers",  "Meanwhile, some of the surrogates are fighting for custody of the babies they carried.", {"surrogates": "_", "fighting for custody": "*"}),
    ("sentence", "If they're convicted, Guojun faces up to seventeen years in prison, and Sylvia up to nearly twelve.", {"convicted,": "_", "seventeen years": "*", "nearly twelve.": "*"}),
    ("pending",  "But the trial hasn't happened yet, and until it does, they're innocent until proven guilty.", {"hasn't happened yet,": "*", "innocent until proven guilty.": "_"}),
    ("end3",     "So follow for part three, because when the verdict comes in, I'll tell you everything.", {"part three,": "*", "verdict": "_"}),
]
SAY = {"2025": "twenty twenty-five", "2026": "twenty twenty-six", "Guojun": "Gwo-jun", "Guojun's": "Gwo-jun's"}


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
