"""Send one personalised outreach email per firm through Resend, BCC the founder, and log it.
python3 send_batch.py batch.json [--dry]"""
import json, re, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

BODY = """{greet},

{hook}

ClearToWork takes all of that off your hands, and to show you how, we'd like to do a free site paperwork check for {short}:

1. Reply YES and send us your crew list and whatever cards and certs you have. Phone photos are fine.
2. Within 48 hours you get a report showing everything that's missing or expiring, for each of your main contractors.
3. If you like it, we keep it all in date for you on a free 30-day trial: we chase workers for card photos, get certificates from your broker, line up courses (nothing that costs money without your OK) and keep a ready-to-send pack for every main contractor.

No cost, no commitment, and your workers don't need an app.

See how ClearToWork works in 60 seconds:
https://cleartowork.ie

Just reply YES to get started.

Kind regards,
Hiba
Founder, ClearToWork
hello@cleartowork.ie · https://cleartowork.ie

If this isn't for you, just reply "no thanks" and I won't contact you again."""

def main():
    batch = json.loads(Path(sys.argv[1]).read_text())
    dry = "--dry" in sys.argv
    bcc = (Path(__file__).parent / ".bcc").read_text().strip()
    log = Path(__file__).parent.parent / "15_outreach_log.md"
    for f in batch:
        short = re.sub(r"\s*\(.*?\)|\s+(Ltd|Limited|Group|Services|Dublin)\b.*$", "", f["firm"]).strip()
        text = BODY.format(short=short, **f)
        if dry:
            print(f"--- {f['firm']} <{f['to']}> | {f['subject']}\n{text}\n"); continue
        payload = {"from": "Hiba | ClearToWork <hello@cleartowork.ie>", "to": [f["to"]], "bcc": [bcc],
                   "reply_to": "hello@cleartowork.ie", "subject": f["subject"], "text": text}
        req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer proxy-injected", "Content-Type": "application/json", "User-Agent": "cleartowork-outreach/1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status = "Sent (id " + json.load(r)["id"][:8] + ")"
        except urllib.error.HTTPError as e:
            status = f"Failed: {e.code} {e.read().decode()[:120]}"
        status = status.replace("\n", " ")
        print(f["firm"], "->", status)
        with log.open("a") as fh:
            fh.write(f"| {datetime.now():%d %b %Y %H:%M} | {f['firm']} | {f['to']} | Email from hello@cleartowork.ie (Resend) | "
                     f"Trial message; source: {f['source']} | {status} | +5 working days |\n")
        time.sleep(1.5)

main()
