"""Getting messages delivered (AUDIT.md defect D9 and Phase 3).

dispatch():  one send attempt for an outgoing message, applying WhatsApp consent and the 24-hour
             window, and recording what happened. A failure that may clear up (server down) goes
             into the retry queue; one that can't (no address, address refused, opted out) escalates
             the issue to the ops team at once. A message is never silently treated as delivered.
retry_due(): retries queued messages after 15 minutes, 1 hour, 4 hours and 12 hours; after the
             fifth failure the issue is escalated.
report():    delivery reports from the email or WhatsApp provider (delivered, bounced, complained,
             failed). A bounce or complaint escalates the issue.
reply_window_opened(): called when someone messages us on WhatsApp; sends what was waiting for them.
"""
import json
from datetime import datetime, timedelta, timezone

from . import connectors, whatsapp
from .store import now_iso

BACKOFF_MINUTES = [15, 60, 240, 720]
MAX_ATTEMPTS = len(BACKOFF_MINUTES) + 1
WINDOW_HOURS = 24
BAD_EVENTS = {"bounced", "complained", "failed", "undelivered"}


def _now():
    return datetime.now(timezone.utc)


def _later(minutes):
    return (_now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _escalate(store, issue_id, ref, why):
    if issue_id and store.issue(issue_id) and store.issue(issue_id)["status"] in ("open", "in_progress"):
        store.update_issue(issue_id, status="escalated")
    store.audit("delivery", "delivery_failed", ref or issue_id or "", {"issue": issue_id, "reason": why})


def _worker_by_phone(customer, phone):
    d = whatsapp.digits(phone)
    return next((w for w in customer.workers.values() if d and whatsapp.digits(w.get("phone")) == d), None)


def in_window(store, address):
    last = store.contact_pref(whatsapp.digits(address)).get("last_inbound_at")
    return bool(last) and last >= (_now() - timedelta(hours=WINDOW_HOURS)).isoformat(timespec="seconds")


def dispatch(store, customer, to, subject, body, issue_id="", step_id="", outbox=""):
    """Returns the delivery status shown in the outbox and the message history."""
    channel, address = to.get("channel"), to.get("address")
    base = {"channel": channel, "to_name": to.get("name"), "address": address, "subject": subject, "body": body,
            "issue_id": issue_id, "step_id": step_id, "outbox": outbox}
    cid = customer.company.get("id", "")
    if channel == "whatsapp" and whatsapp.mode() == "cloud" and not connectors.offline():
        key = whatsapp.digits(address)
        if store.contact_pref(key).get("opted_out_at"):
            _escalate(store, issue_id, step_id, f"{to.get('name')} has opted out of WhatsApp: contact them another way")
            return "not sent: opted out of WhatsApp (ops team told)"
        worker = _worker_by_phone(customer, address)
        if worker is not None and not worker.get("whatsapp_opt_in"):
            _escalate(store, issue_id, step_id, f"no WhatsApp opt-in recorded for {to.get('name')}")
            return "not sent: no WhatsApp opt-in recorded (ops team told)"
        if not in_window(store, key):
            first = (to.get("name") or "").split(" ")[0] or "there"
            r = whatsapp.send_template(address, [first, customer.company.get("name", ""), subject])
            if r["status"] == "sent":
                store.add_delivery(**base, status="awaiting_reply", attempts=1, message_id=r.get("message_id", ""))
                return "notified on WhatsApp; full message goes when they reply"
            return _failed(store, base, r)
    r = connectors.deliver(channel, address, subject, body, ref=issue_id, customer_id=cid, step_id=step_id)
    if r["status"] == "sent":  # the body is only kept while it may still need sending
        store.add_delivery(**{**base, "body": ""}, status="sent", attempts=1, message_id=r.get("message_id", ""))
    elif r["status"].startswith("failed"):
        return _failed(store, base, r)
    return r["status"]


def _failed(store, base, r):
    if r.get("permanent"):
        store.add_delivery(**base, status="failed", attempts=1, last_error=r["status"])
        _escalate(store, base["issue_id"], base["step_id"], f"couldn't send to {base['to_name']}: {r['status']}")
        return f"{r['status']} (ops team told)"
    store.add_delivery(**base, status="retrying", attempts=1, last_error=r["status"], next_try=_later(BACKOFF_MINUTES[0]))
    store.audit("delivery", "delivery_retry_queued", base["step_id"] or base["issue_id"], {"error": r["status"]})
    return f"{r['status']} (will retry)"


def retry_due(store, customer, now=None):
    now = (now or _now()).isoformat(timespec="seconds")
    events = []
    for d in store.deliveries("retrying"):
        if (d["next_try"] or "") > now:
            continue
        r = connectors.deliver(d["channel"], d["address"], d["subject"], d["body"], ref=d["issue_id"],
                               customer_id=customer.company.get("id", ""), step_id=d["step_id"])
        attempts = d["attempts"] + 1
        if r["status"] == "sent":
            store.update_delivery(d["id"], status="sent", attempts=attempts, message_id=r.get("message_id", ""), last_error="", body="")
            store.log_comm("out", d["channel"], d["to_name"], d["address"], d["subject"], d["issue_id"], d["step_id"],
                           f"sent (attempt {attempts})", d["outbox"])
            events.append((d["step_id"], f"sent on attempt {attempts}"))
        elif r.get("permanent") or attempts >= MAX_ATTEMPTS or not r["status"].startswith("failed"):
            store.update_delivery(d["id"], status="failed", attempts=attempts, last_error=r["status"], body="")
            _escalate(store, d["issue_id"], d["step_id"], f"gave up sending to {d['to_name']} after {attempts} attempts: {r['status']}")
            store.log_comm("out", d["channel"], d["to_name"], d["address"], d["subject"], d["issue_id"], d["step_id"],
                           f"not delivered after {attempts} attempts (ops team told)", d["outbox"])
            events.append((d["step_id"], "gave up, escalated"))
        else:
            store.update_delivery(d["id"], attempts=attempts, last_error=r["status"],
                                  next_try=_later(BACKOFF_MINUTES[attempts - 1]))
            events.append((d["step_id"], f"attempt {attempts} failed, will retry"))
    return events


def report(store, message_id, event, detail=""):
    """A delivery report from the provider. Returns True if the message was ours."""
    rows = store.deliveries(message_id=message_id)
    if not rows:
        return False
    d = rows[-1]
    event = (event or "").lower()
    store.audit("delivery", "delivery_report", d["step_id"] or d["issue_id"],
                {"event": event, "detail": detail, "to": d["to_name"], "channel": d["channel"]})
    if event in BAD_EVENTS:
        store.update_delivery(d["id"], status=event, last_error=detail)
        _escalate(store, d["issue_id"], d["step_id"], f"message to {d['to_name']} {event}: {detail}".strip(": "))
    elif event in ("delivered", "read") and d["status"] in ("sent", "awaiting_reply"):
        store.update_delivery(d["id"], status=event if d["status"] == "sent" else d["status"])
    return True


def reply_window_opened(store, phone):
    """They messaged us on WhatsApp: record it and send whatever was waiting for the window."""
    key = whatsapp.digits(phone)
    store.set_contact_pref(key, "whatsapp", last_inbound_at=now_iso())
    sent = 0
    for d in store.deliveries("awaiting_reply"):
        if whatsapp.digits(d["address"]) != key:
            continue
        r = whatsapp.send_text(d["address"], d["body"])
        if r["status"] == "sent":
            store.update_delivery(d["id"], status="sent", message_id=r.get("message_id", ""), body="")
            store.log_comm("out", "whatsapp", d["to_name"], d["address"], d["subject"], d["issue_id"], d["step_id"],
                           "sent (after their reply)", d["outbox"])
            sent += 1
        else:
            store.update_delivery(d["id"], status="retrying", attempts=d["attempts"] + 1, last_error=r["status"],
                                  next_try=_later(BACKOFF_MINUTES[0]))
    return sent


def set_opt_out(store, phone, out=True):
    store.set_contact_pref(whatsapp.digits(phone), "whatsapp", opted_out_at=now_iso() if out else None)
    store.audit("inbound:whatsapp", "whatsapp_opt_out" if out else "whatsapp_opt_in_again", "", {"phone_ending": whatsapp.digits(phone)[-4:]})


def summary(store):
    out = {}
    for d in store.deliveries():
        out[d["status"]] = out.get(d["status"], 0) + 1
    return out
