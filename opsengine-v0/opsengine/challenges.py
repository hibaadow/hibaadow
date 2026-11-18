"""Workers (or their employer) can challenge a compliance status ("my Safe Pass is valid", "I don't work on
that site"). GDPR review Q7 / Art 22: a person reviews every challenge; the system never decides one.

- Raising a challenge never hides or clears the issue: it stays open and visible, marked "challenged".
  Reminders about it pause while a person checks, so the worker isn't chased for something they dispute.
  Anything that stops work still shows as stopping work until the challenge is decided.
- A person on our team decides within RESPOND_DAYS. Upheld: the corrected record goes through the
  normal checks (ingest / validation), so a challenge can't sneak an unchecked document in. Not upheld:
  the reason is recorded and sent to the customer (and the worker, if they raised it).
- Overdue challenges are escalated to the ops team by the daily run.
Every step is audited."""
import json
from datetime import timedelta
from pathlib import Path

from .store import now_iso

RESPOND_DAYS = 5
OPEN = "open"


def _next_id(store):
    n = store.db.execute("SELECT COUNT(*) FROM challenges").fetchone()[0] + 1
    return f"CH-{n:04d}"


def get(store, ch_id):
    row = store.db.execute("SELECT * FROM challenges WHERE id=?", (ch_id,)).fetchone()
    return dict(row) if row else None


def listing(store, status=None, issue_id=None):
    sql, args = "SELECT * FROM challenges WHERE 1=1", []
    if status:
        sql, args = sql + " AND status=?", args + [status]
    if issue_id:
        sql, args = sql + " AND issue_id=?", args + [issue_id]
    return [dict(r) for r in store.db.execute(sql + " ORDER BY id", args)]


def open_for(store, issue_id):
    return next(iter(listing(store, OPEN, issue_id)), None)


def raise_challenge(engine, issue_id, by, reason, channel="portal", holder=None):
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValueError("say briefly why the status is wrong")
    issue = engine.store.issue(issue_id) if issue_id else None
    if issue_id and not issue:
        raise ValueError(f"unknown issue {issue_id}")
    if issue and issue["status"] == "resolved":
        raise ValueError("that issue is already sorted")
    if issue and open_for(engine.store, issue_id):
        raise ValueError("that status is already being checked")
    ch = {"id": _next_id(engine.store), "issue_id": issue_id or "", "holder": holder or (issue or {}).get("holder", ""),
          "raised_by": by, "channel": channel, "reason": reason[:1000], "status": OPEN,
          "due_on": (engine.today + timedelta(days=RESPOND_DAYS)).isoformat(), "created_at": now_iso()}
    engine.store.db.execute(f"INSERT INTO challenges ({', '.join(ch)}) VALUES ({', '.join('?' * len(ch))})", list(ch.values()))
    engine.store.db.commit()
    engine.store.audit(f"human:{by}" if channel == "portal" else f"inbound:{channel}", "challenge_raised", ch["id"],
                       {"issue": issue_id, "holder": ch["holder"], "reason": reason[:300], "due_on": ch["due_on"]})
    _note_ops(engine, ch, f"New challenge {ch['id']} from {by}: {reason[:300]}. Decide by {ch['due_on']}.")
    return ch["id"]


def decide(engine, ch_id, by, upheld, note, document=None):
    """A person decides. Upheld needs the corrected record, which goes through the normal checks."""
    ch = get(engine.store, ch_id)
    if not ch or ch["status"] != OPEN:
        raise ValueError(f"{ch_id} isn't waiting for a decision")
    note = (note or "").strip()
    if len(note) < 5:
        raise ValueError("record the reason for the decision")
    events = []
    if upheld:
        if not document:
            raise ValueError("an upheld challenge needs the corrected record (it goes through the normal checks)")
        events = engine.ingest(document, source=f"challenge {ch_id}")
        if document.get("id") not in {d["id"] for d in engine.store.documents()}:
            raise ValueError("the corrected record didn't pass the checks; it's in the review queue instead")
    status = "upheld" if upheld else "not_upheld"
    engine.store.db.execute("UPDATE challenges SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                            (status, by, now_iso(), note[:1000], ch_id))
    engine.store.db.commit()
    engine.store.audit(f"human:{by}", "challenge_decided", ch_id, {"outcome": status, "note": note[:300], "issue": ch["issue_id"]})
    _tell_outcome(engine, ch, upheld, note)
    return events


def overdue(engine):
    """Daily run: challenges past their decision date go to the ops team, once."""
    out = []
    for ch in listing(engine.store, OPEN):
        if ch["due_on"] < engine.today.isoformat() and not engine.store.setting(f"challenge_overdue:{ch['id']}"):
            engine.store.set_setting(f"challenge_overdue:{ch['id']}", engine.today.isoformat(), "scheduler")
            engine.store.audit("scheduler", "challenge_overdue", ch["id"], {"due_on": ch["due_on"]})
            _note_ops(engine, ch, f"Challenge {ch['id']} is overdue (was due {ch['due_on']}). Decide it today.")
            out.append(ch["id"])
    return out


def _write(engine, name, to, subject, body, issue_id=""):
    from . import delivery
    status = "internal" if to["channel"] == "file" else delivery.dispatch(engine.store, engine.customer, to, subject, body, issue_id)
    engine.outbox.mkdir(parents=True, exist_ok=True)
    path = engine.outbox / f"{name}.md"
    path.write_text(f"# {subject}\n\n- To: {to['name']} via {to['channel']} ({to['address']})\n- Delivery: {status}\n\n{body}\n", encoding="utf-8")
    engine.store.log_comm("out", to["channel"], to["name"], to["address"], subject, issue_id, "", status, str(path))


def _note_ops(engine, ch, text):
    _write(engine, f"{ch['id']}-ops-{now_iso()[:19].replace(':', '')}", {"name": "Ops team", "channel": "file", "address": "-"},
           f"Challenge {ch['id']}", text, ch["issue_id"])


def _tell_outcome(engine, ch, upheld, note):
    c = engine.customer
    outcome = ("You were right: we've corrected the record." if upheld else
               "We checked and the status stays as it is.")
    body = f"About your challenge {ch['id']}: {outcome} Reason: {note}"
    owner = c.company["owner"]
    _write(engine, f"{ch['id']}-outcome-customer", {"name": owner["name"], "channel": "email", "address": owner["email"],
                                                    "language": owner.get("language", "en")},
           f"Outcome of challenge {ch['id']}", body, ch["issue_id"])
    w = c.workers.get(ch["holder"])
    if w and ch["channel"] == "whatsapp":
        _write(engine, f"{ch['id']}-outcome-worker", {"name": w["name"], "channel": "whatsapp", "address": w["phone"],
                                                      "language": w.get("language", "en")},
               f"Outcome of challenge {ch['id']}", body, ch["issue_id"])


def summary(engine, issue_id):
    """Plain words for an issue page: is it being challenged, or how was it decided?"""
    rows = listing(engine.store, issue_id=issue_id)
    if not rows:
        return None
    ch = rows[-1]
    from .labels import nice_date
    if ch["status"] == OPEN:
        return f"Challenged by {ch['raised_by']}: \"{ch['reason']}\". A person is checking and will decide by {nice_date(ch['due_on'])}."
    word = "upheld" if ch["status"] == "upheld" else "not upheld"
    return f"Challenge {word} by {ch['decided_by']}: {ch['decision_note']}"
