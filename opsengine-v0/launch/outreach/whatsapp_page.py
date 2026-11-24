"""Build 16_whatsapp_messages.html (tap-to-send buttons) from 16_whatsapp_messages.md."""
import re, html
from pathlib import Path
here = Path(__file__).parent.parent
md = (here / "16_whatsapp_messages.md").read_text()
cards = []
for m in re.finditer(r"## (\d+)\. (.+?)  \((.+?), from .+?\)\n\*\*\[Open in WhatsApp\]\((.+?)\)\*\*\n\n((?:>.*\n?)+)", md):
    n, f, ph, link, quote = m.groups()
    txt = "\n".join(l[2:] if l.startswith("> ") else "" for l in quote.strip().splitlines())
    cards.append(f'<div class="c"><h2>{n}. {html.escape(f)}</h2><p class="ph">{ph}</p><p class="t">{html.escape(txt)}</p>'
                 f'<a class="b" href="{html.escape(link)}">Open in WhatsApp</a></div>')
css = """:root{--bg:#f6f5f1;--card:#fff;--ink:#16181d;--mut:#5b6170;--g:#1f9d55}
@media (prefers-color-scheme:dark){:root{--bg:#111;--card:#1c1d20;--ink:#eee;--mut:#aaa}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,system-ui,sans-serif;padding:16px}h1{font-size:22px}
.c{background:var(--card);border-radius:14px;padding:14px 16px;margin:0 0 14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}h2{font-size:18px;margin:0}
.ph{color:var(--mut);margin:2px 0 8px}.t{white-space:pre-wrap;font-size:15px}
.b{display:block;text-align:center;background:var(--g);color:#fff;text-decoration:none;font-weight:700;padding:12px;border-radius:10px}"""
page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>WhatsApp messages</title><style>{css}</style></head><body><h1>WhatsApp messages</h1>'
        f'<p>Tap the green button: WhatsApp opens with the message typed. Check it, press send. Then tell Claude which ones you sent.</p>'
        f'{"".join(cards)}</body></html>')
(here / "16_whatsapp_messages.html").write_text(page)
print(len(cards), "cards")
