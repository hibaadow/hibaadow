"""Inbound email: replies and photo attachments filed against the right customer and issue.

    python -m opsengine inbox          # check the mailbox once (run every few minutes from a timer)

Settings (.env): IMAP_HOST, IMAP_PORT (993), IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER (INBOX).

Routing, most reliable first:
  1. plus address in To/Delivered-To: inbox+<customer>.<issue>@domain (set by our own emails)
  2. an issue tag in the subject, e.g. "[ISS-0005]", with the sender matched to a customer
  3. the sender's address matched to a customer's owner or a subcontractor contact
Anything that can't be routed is kept for the ops team; nothing is guessed. Photos go through
the normal photo reader (engine.ingest_photo), so low-confidence reads wait for a person."""
import email
import email.policy
import imaplib
import json
import os
import re
from datetime import date
from email.utils import parseaddr
from pathlib import Path

from .engine import Engine
from .knowledge import ROOT

PLUS = re.compile(r"\+([a-z0-9_\-]+)(?:\.(ISS-\d+))?@", re.I)
TAG = re.compile(r"\[(ISS-\d+)\]")
ATTACH_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic"}


def _company(folder):
    return json.loads((Path(folder) / "company.json").read_text(encoding="utf-8"))


def sender_index(customers):
    """email address -> customer id, from owners and subcontractor contacts."""
    idx = {}
    for cid, folder in customers.items():
        c = _company(folder)
        if c.get("owner", {}).get("email"):
            idx[c["owner"]["email"].lower()] = cid
        subs = c.get("subcontractors", [])
        for s in (subs.values() if isinstance(subs, dict) else subs):
            em = (s.get("contact") or {}).get("email")
            if em:
                idx[em.lower()] = cid
    return idx


def route(msg, customers):
    """(customer id or None, issue id or None, how) for an email.message.EmailMessage."""
    for h in ("Delivered-To", "X-Original-To", "To", "Cc"):
        for v in msg.get_all(h, []):
            m = PLUS.search(v)
            if m and m.group(1) in customers:
                return m.group(1), m.group(2), "reply address"
    sender = parseaddr(msg.get("From", ""))[1].lower()
    cid = sender_index(customers).get(sender)
    tag = TAG.search(msg.get("Subject", ""))
    if cid:
        return cid, tag.group(1) if tag else None, "sender" + (" + subject tag" if tag else "")
    return None, None, "unknown sender"


def attachments(msg):
    for part in msg.iter_attachments():
        name = Path(part.get_filename() or "attachment").name
        if Path(name).suffix.lower() in ATTACH_TYPES:
            yield name, part.get_payload(decode=True)


def process(raw, customers, state_dir=None, today=None, call=None):
    """File one raw email. Returns a summary dict (also used by tests)."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    cid, issue_id, how = route(msg, customers)
    sender_name, sender = parseaddr(msg.get("From", ""))
    subject = msg.get("Subject", "(no subject)")
    state = Path(state_dir or ROOT / "state")
    if not cid:
        held = state / "inbound_unrouted"
        held.mkdir(parents=True, exist_ok=True)
        path = held / f"{date.today().isoformat()}-{abs(hash(msg.get('Message-ID', subject))) % 10**8}.eml"
        path.write_bytes(raw)
        return {"status": "unrouted", "why": how, "saved": str(path)}
    eng = Engine(customers[cid], state_dir=state, today=today)
    issue = eng.store.issue(issue_id) if issue_id else None
    eng.store.log_comm("in", "email", sender_name or sender, sender, subject, issue["id"] if issue else None, None,
                       "received", "")
    out = {"status": "filed", "customer": cid, "issue": issue["id"] if issue else None, "how": how, "photos": []}
    folder = state / "uploads" / cid
    folder.mkdir(parents=True, exist_ok=True)
    for i, (name, data) in enumerate(attachments(msg)):
        path = folder / f"{date.today().isoformat()}-email-{i}-{name}"
        path.write_bytes(data)
        holder = issue["holder"] if issue and (issue["holder"] == "company" or issue["holder"] in eng.customer.workers) else "company"
        context = issue.get("context") if issue else None
        try:
            r = eng.ingest_photo(path, holder, context=context, received_via="email", call=call)
        except Exception as exc:                       # never lose an attachment: a person looks at it
            review = eng._hold_for_review({"file": str(path), "holder": holder}, [f"could not read automatically: {exc}"], "email")
            r = {"status": "needs_review", "review": review}
        out["photos"].append({"file": name, "status": r["status"], "review": r.get("review")})
    return out


def check_mailbox(customers, state_dir=None, today=None):
    """Fetch unread mail over IMAP, file each message, mark it read. Returns the summaries."""
    host = os.environ.get("IMAP_HOST")
    if not host:
        raise SystemExit("IMAP_HOST is not set (see .env.example)")
    box = imaplib.IMAP4_SSL(host, int(os.environ.get("IMAP_PORT", "993")))
    box.login(os.environ.get("IMAP_USER", ""), os.environ.get("IMAP_PASSWORD", ""))
    box.select(os.environ.get("IMAP_FOLDER", "INBOX"))
    results = []
    try:
        _, data = box.search(None, "UNSEEN")
        for num in data[0].split():
            _, parts = box.fetch(num, "(RFC822)")
            raw = parts[0][1]
            try:
                results.append(process(raw, customers, state_dir, today))
                box.store(num, "+FLAGS", "\\Seen")
            except Exception as exc:                   # leave it unread; try again next time
                results.append({"status": "error", "error": repr(exc)})
    finally:
        box.logout()
    return results
