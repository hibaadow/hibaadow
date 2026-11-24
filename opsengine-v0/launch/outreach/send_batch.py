"""Send one personalised outreach email per firm through Resend, BCC the founder, and log it.
python3 send_batch.py batch.json [--dry]"""
import json, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

BODY = """{greet},

{hook}

ClearToWork keeps all of that in date for you: we check everything against what each main contractor wants, chase workers and brokers for anything missing or expiring, and keep a ready-to-send pack for every contractor.

We're offering a free 30-day trial to a few firms this month. Could the person who looks after your site paperwork spare 10 minutes for 3 quick questions, to see if it would suit you?

You can see what we do here (60-second video): https://cleartowork.netlify.app

Thanks,
Hiba
ClearToWork · hello@cleartowork.ie

If this isn't for you, just reply "no thanks" and I won't contact you again."""

def main():
    batch = json.loads(Path(sys.argv[1]).read_text())
    dry = "--dry" in sys.argv
    bcc = (Path(__file__).parent / ".bcc").read_text().strip()
    log = Path(__file__).parent.parent / "15_outreach_log.md"
    for f in batch:
        text = BODY.format(**f)
        if dry:
            print(f"--- {f['firm']} <{f['to']}> | {f['subject']}\n{text}\n"); continue
        payload = {"from": "Hiba | ClearToWork <hello@cleartowork.ie>", "to": [f["to"]], "bcc": [bcc],
                   "reply_to": "hello@cleartowork.ie", "subject": f["subject"], "text": text}
        req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer proxy-injected", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status = "Sent (id " + json.load(r)["id"][:8] + ")"
        except urllib.error.HTTPError as e:
            status = f"Failed: {e.code} {e.read().decode()[:120]}"
        print(f["firm"], "->", status)
        with log.open("a") as fh:
            fh.write(f"| {datetime.now():%d %b %Y %H:%M} | {f['firm']} | {f['to']} | Email from hello@cleartowork.ie (Resend) | "
                     f"Trial message; source: {f['source']} | {status} | +5 working days |\n")
        time.sleep(1.5)

main()
