"""Send one personalised outreach email per firm through Resend, BCC the founder, and log it.
python3 send_batch.py batch.json [--dry]"""
import json, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

BODY = """{greet},

{hook}

That's exactly what ClearToWork takes off your hands:

- We check every worker's Safe Pass, CSCS, insurance and RAMS against what each of your main contractors requires, and show you every gap.
- We chase it for you: card photos from your crew, certificates from your broker, course bookings when something has run out.
- We remind you well before anything expires, so nobody gets turned away at the gate.
- You always have an up-to-date pack ready to send to each main contractor.

Nothing that costs money happens without your OK, and your workers don't need an app: they just reply with a photo of their card.

We're taking on a small number of Irish subcontractors for a free 30-day trial. On day one we run a full check and show you exactly where you stand. No cost, no commitment.

Would you be open to a quick 10-minute call this week or next?

See how it works in 60 seconds: https://cleartowork.netlify.app

Kind regards,
Hiba
Founder, ClearToWork
hello@cleartowork.ie · cleartowork.ie

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
                                     headers={"Authorization": "Bearer proxy-injected", "Content-Type": "application/json", "User-Agent": "cleartowork-outreach/1"})
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
