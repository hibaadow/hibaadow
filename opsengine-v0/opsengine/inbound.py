"""Inbound documents by email and WhatsApp (AUDIT.md Phase 3), feeding the photo reader.

Email: each customer can have their own address, docs+<customer id>@<your domain> (plus addressing),
or the customer is found from the sender. The sender must be someone on file for that customer
(owner, broker, subcontractor contact or worker email). Replies to our emails carry the issue
reference ([ISS-0007]) in the subject, which tells us whose document it is and what type is
expected. Without a reference, a subcontractor's own document is filed under them; anything else
is kept for the ops team rather than guessed. If the receiving mail server didn't confirm the
sender (DMARC/SPF in Authentication-Results), every attachment goes to a person to check.

WhatsApp: the sender's number must match exactly one worker. Photos and PDFs are read; if that
worker has exactly one document request open, that's the expected type. STOP / START change
consent. Any message from them opens the 24-hour reply window (see delivery.py).

Nothing is ever accepted on the strength of the channel alone: every file goes through the same
photo reader and checks as before, and anything doubtful waits in the review queue."""
import email
import email.policy
import email.utils
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import delivery, whatsapp
from .engine import Engine

ATTACHMENT_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}
ISSUE_REF = re.compile(r"\b(ISS-\d{4})\b")


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def _safe_name(name, fallback):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name or "").name).strip(".-")
    return name[:80] or fallback


def _addresses(customer):
    c = customer.company
    out = {}
    if c.get("owner", {}).get("email"):
        out[c["owner"]["email"].lower()] = ("owner", "company")
    if c.get("broker", {}).get("email"):
        out[c["broker"]["email"].lower()] = ("broker", "company")
    for sid, sub in customer.subcontractors.items():
        if sub.get("contact", {}).get("email"):
            out[sub["contact"]["email"].lower()] = ("subcontractor", sid)
    for wid, w in customer.workers.items():
        if w.get("email"):
            out[w["email"].lower()] = ("worker", wid)
    return out


def _sender_verified(msg):
    results = " ".join(str(h) for h in msg.get_all("Authentication-Results", [])).lower()
    return "dmarc=pass" in results or ("spf=pass" in results and "dkim=pass" in results)


def _engines(customers, state_dir, today):
    return {cid: Engine(folder, state_dir=state_dir, today=today) for cid, folder in customers.items()}


def _unmatched(state_dir, raw, why, suffix=".eml"):
    folder = Path(state_dir) / "inbound-unmatched"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_stamp()}{suffix}"
    path.write_bytes(raw)
    (folder / f"{path.stem}.why.txt").write_text(why + "\n", encoding="utf-8")
    return {"status": "unmatched", "why": why, "kept_as": str(path)}


def handle_email(customers, state_dir, raw, today=None, call=None):
    """customers: {customer id: folder}. Returns what happened, per attachment."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    recipients = " ".join(str(msg.get(h, "")) for h in ("To", "Cc", "Delivered-To")).lower()
    engines = _engines(customers, state_dir, today)
    tagged = [cid for cid in engines if f"+{cid}@" in recipients]
    known = [cid for cid, e in engines.items() if sender in _addresses(e.customer)]
    cid = tagged[0] if len(tagged) == 1 else known[0] if len(known) == 1 else None
    if not cid:
        return _unmatched(state_dir, raw, f"couldn't tell which customer this is for (from {sender or 'unknown sender'})")
    e = engines[cid]
    role, who = _addresses(e.customer).get(sender, (None, None))
    if role is None:
        e.store.audit("inbound:email", "inbound_refused", "", {"reason": "sender not on file", "sender_domain": sender.rpartition("@")[2]})
        return _unmatched(state_dir, raw, f"{sender} is not on file for this customer")
    subject = str(msg.get("Subject", ""))
    ref = ISSUE_REF.search(subject) or ISSUE_REF.search(msg.get_body(("plain",)).get_content() if msg.get_body(("plain",)) else "")
    issue = e.store.issue(ref.group(1)) if ref else None
    if issue:
        holder, expected = issue["holder"], issue["requirement"] if issue["requirement"] in e.kb.requirements else None
    elif role == "subcontractor":
        holder, expected = who, None
    elif role == "worker":
        holder, expected = who, None
    else:
        holder, expected = None, None
    verified = _sender_verified(msg)
    e.store.log_comm("in", "email", sender, sender, subject, issue["id"] if issue else "", "", "received")
    results = []
    inbox = e.store.path.parent / "inbound"
    inbox.mkdir(exist_ok=True)
    for i, part in enumerate(msg.iter_attachments()):
        name = _safe_name(part.get_filename(), f"attachment-{i + 1}")
        if Path(name).suffix.lower() not in ATTACHMENT_TYPES:
            results.append({"file": name, "status": "ignored (not a photo or PDF)"})
            continue
        path = inbox / f"{_stamp()}-{name}"
        path.write_bytes(part.get_payload(decode=True) or b"")
        if holder is None or (holder not in e.customer.workers and holder != "company"):
            # the photo reader files worker and company documents; anything else goes to a person
            review = e.store.add_review({"file": str(path), "holder": holder or "", "context": None,
                                         "extraction": {"source": "email", "received_via": "email", "from": sender},
                                         "confidence": 0, "reasons": ["arrived by email without an issue reference: a person must file it"]})
            e.store.audit("inbound:email", "review_queued", review, {"file": name, "from_role": role})
            results.append({"file": name, "status": "needs_review", "review": review})
            continue
        hold = [] if verified else ["the sender's email address couldn't be verified: check it came from them"]
        r = e.ingest_photo(path, holder, issue["context"] if issue else None, expected_type=expected,
                           received_via="email", call=call, hold_reasons=hold)
        results.append({"file": name, **{k: r[k] for k in ("status", "confidence") if k in r}})
    if not results:
        results.append({"status": "no attachments"})
    e.store.audit("inbound:email", "email_received", issue["id"] if issue else "",
                  {"from_role": role, "sender_verified": verified, "attachments": len(results)})
    return {"status": "processed", "customer": cid, "holder": holder, "issue": issue["id"] if issue else None,
            "sender_verified": verified, "results": results}


def process_maildrop(customers, state_dir, folder, today=None, call=None):
    """Process every .eml file in a folder (e.g. delivered there by the mail server) once."""
    folder = Path(folder)
    done = folder / "processed"
    done.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(folder.glob("*.eml")):
        out.append({"file": f.name, **handle_email(customers, state_dir, f.read_bytes(), today, call)})
        f.rename(done / f.name)
    return out


def poll_imap(customers, state_dir, today=None):
    """Fetch unread mail from IMAP_HOST (settings in .env) and process it. Untested against a live server."""
    import imaplib
    import os
    out = []
    with imaplib.IMAP4_SSL(os.environ["IMAP_HOST"], int(os.environ.get("IMAP_PORT", "993"))) as m:
        m.login(os.environ["IMAP_USER"], os.environ.get("IMAP_PASSWORD", ""))
        m.select(os.environ.get("IMAP_FOLDER", "INBOX"))
        _, ids = m.search(None, "UNSEEN")
        for num in ids[0].split():
            _, data = m.fetch(num, "(RFC822)")
            out.append(handle_email(customers, state_dir, data[0][1], today))
            m.store(num, "+FLAGS", "\\Seen")
    return out


# ---------------- WhatsApp ----------------
def _find_worker(engines, phone):
    hits = [(cid, wid) for cid, e in engines.items() for wid, w in e.customer.workers.items()
            if whatsapp.digits(w.get("phone")) == phone]
    return hits[0] if len(hits) == 1 else (None, None)


def _expected_for(e, holder):
    """Only a hint when it can't be wrong: the worker has exactly one open document issue. A wrong hint
    would send a good photo to review, so otherwise the reader works out the type itself."""
    open_issues = [i for i in e.store.issues("open") if i["holder"] == holder and i["requirement"] in e.kb.requirements]
    return (open_issues[0]["requirement"], open_issues[0]["context"]) if len(open_issues) == 1 else (None, None)


def handle_whatsapp(customers, state_dir, payload, today=None, transport=None, call=None):
    engines = _engines(customers, state_dir, today)
    messages, statuses = whatsapp.parse_webhook(payload)
    out = []
    for s in statuses:
        for e in engines.values():
            if delivery.report(e.store, s["id"], s["status"], s["error"]):
                break
    for m in messages:
        cid, wid = _find_worker(engines, m["from"])
        if not cid:
            out.append(_unmatched(state_dir, json.dumps(m).encode(), "WhatsApp from a number that isn't exactly one worker", ".json"))
            continue
        e = engines[cid]
        name = e.customer.workers[wid]["name"]
        e.store.log_comm("in", "whatsapp", name, m["from"], (m["text"] or m["type"] or "")[:80], "", "", "received")
        word = (m["text"] or "").strip().upper()
        if word in ("STOP", "UNSUBSCRIBE"):
            delivery.set_opt_out(e.store, m["from"], True)
            out.append({"status": "opted_out", "worker": wid})
            continue
        if word == "START":
            delivery.set_opt_out(e.store, m["from"], False)
        sent = delivery.reply_window_opened(e.store, m["from"])
        if m["type"] in ("image", "document") and m["media_id"]:
            data, mime = whatsapp.download_media(m["media_id"], transport)
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}.get(mime or m["mime"], "")
            if not ext:
                out.append({"status": "ignored (not a photo or PDF)", "worker": wid})
                continue
            inbox = e.store.path.parent / "inbound"
            inbox.mkdir(exist_ok=True)
            path = inbox / f"{_stamp()}-whatsapp-{wid}{ext}"
            path.write_bytes(data)
            expected, context = _expected_for(e, wid)
            r = e.ingest_photo(path, wid, context, expected_type=expected, received_via="whatsapp", call=call)
            out.append({"status": r["status"], "worker": wid, "confidence": r.get("confidence"), "sent_waiting": sent})
        else:
            out.append({"status": "message logged", "worker": wid, "sent_waiting": sent})
    return out
