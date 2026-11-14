"""Daily run: scan and advance every customer, then chase anything that has stalled.

A step that is waiting (for proof, a signature) or awaiting approval gets:
  - a reminder to whoever it is waiting on after CHASE_AFTER_DAYS
  - an escalation to the ops team after ESCALATE_AFTER_DAYS

Each reminder and escalation happens once per waiting period, so running the scheduler twice
on the same day (or every day) never spams anyone. Reminders never approve anything: an
approval still needs the named human. Everything is written to each customer's audit trail.

Run it from cron, e.g. every morning at 07:05:
    5 7 * * *  cd /path/to/opsengine-v0 && python -m opsengine daily
"""
import json
import traceback
from datetime import date
from pathlib import Path

from .actions import ActionContext
from .engine import DONE, Engine
from .knowledge import ROOT

CHASE_AFTER_DAYS = 2
ESCALATE_AFTER_DAYS = 5
CUSTOMERS_ROOT = ROOT / "data" / "customers"
INTERNAL = {"name": "Ops team", "channel": "file", "address": "-"}


def customer_folders(root=CUSTOMERS_ROOT):
    """Every customer folder under root (folders starting with _ or . are templates/hidden)."""
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "company.json").exists())


def _since(step):
    r = step["result"] or {}
    raw = r.get("waiting_since") or r.get("awaiting_since") or (step["updated_at"] or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _approver(engine, role):
    if role == "customer":
        o = engine.customer.company["owner"]
        return {"name": o["name"], "channel": "email", "address": o["email"], "language": o.get("language", "en")}
    return {"name": "Safety reviewer" if role == "safety_reviewer" else "Ops team", "channel": "file",
            "address": "-", "language": "en"}


def _context(engine, issue, step):
    prior = {s["action"]: s["result"] for s in engine.store.steps(issue["id"]) if s["state"] in DONE and s["result"]}
    return ActionContext(engine.kb, engine.customer, engine.store, issue, step, prior, engine.outbox, engine.today)


def _chase(engine, issue, step, days):
    ctx = _context(engine, issue, step)
    who_name = engine.customer.holder_name(issue["holder"])
    if step["state"] == "awaiting_approval":
        to = _approver(engine, step["approval_role"])
        summary = engine.approval_summary(step, ctx.prior)
        subject = f"Reminder: your approval is needed ({step['id']})"
        body = (f"This has been waiting for your approval for {days} days:\n\n{summary}\n\n"
                "Nothing will happen until you approve or reject it. Reply APPROVE or REJECT with a reason.")
    else:
        to = ctx.recipient(step["spec"].get("from", "customer"))
        subject = f"Reminder: {ctx.req['name']} still needed"
        body = f"Reminder: we asked {days} days ago and are still waiting."
        if step["spec"].get("template"):
            _, original = ctx.render(step["spec"]["template"])
            body += f"\n\n{original}"
        else:
            body += f" Please send back the signed {ctx.req['name']} ({who_name})."
    body, note = ctx.localise(body, to.get("language", "en"))
    meta = {"Days waiting": days, **({"Translation": note} if note else {})}
    path = ctx.write_outbox(f"reminder-{engine.today.isoformat()}", to, subject, body, meta)
    return {"to": to["name"], "channel": to["channel"], "outbox": path, "translation": note}


def _escalate(engine, issue, step, days):
    ctx = _context(engine, issue, step)
    waiting_on = (_approver(engine, step["approval_role"])["name"] if step["state"] == "awaiting_approval"
                  else ctx.recipient(step["spec"].get("from", "customer"))["name"])
    body = (f"{issue['id']} ({ctx.req['name']} - {engine.customer.holder_name(issue['holder'])}, {issue['severity']}) "
            f"has been stuck at step {step['id']} ({step['action']}, {step['state']}) for {days} days, "
            f"waiting on {waiting_on}. A reminder has been sent. Please follow up by phone.\n\nDetail: {issue['detail']}")
    path = ctx.write_outbox(f"escalation-{engine.today.isoformat()}", INTERNAL,
                            f"Escalation: {issue['id']} stalled {days} days", body)
    engine.store.update_issue(issue["id"], status="escalated")
    return {"waiting_on": waiting_on, "outbox": path}


def chase_stalled(engine):
    """Remind after CHASE_AFTER_DAYS, escalate after ESCALATE_AFTER_DAYS. Returns events."""
    events = []
    for issue in engine.store.issues("open"):
        step = next((s for s in engine.store.steps(issue["id"]) if s["state"] not in DONE), None)
        if step and step["state"] in ("waiting", "awaiting_approval"):
            since = _since(step)
            if since is None:
                continue
            days = (engine.today - since).days
            result = dict(step["result"] or {})
            changed = False
            if days >= CHASE_AFTER_DAYS and not result.get("chased_on"):
                out = _chase(engine, issue, step, days)
                result["chased_on"] = engine.today.isoformat()
                engine.store.audit("scheduler", "chased", step["id"], {"days_waiting": days, **out})
                events.append((step["id"], f"chased after {days} days"))
                changed = True
            if days >= ESCALATE_AFTER_DAYS and not result.get("escalated_on"):
                out = _escalate(engine, issue, step, days)
                result["escalated_on"] = engine.today.isoformat()
                engine.store.audit("scheduler", "escalated", step["id"], {"days_waiting": days, **out})
                events.append((step["id"], f"escalated after {days} days"))
                changed = True
            if changed:
                engine.store.update_step(step["id"], result=json.dumps(result))
    return events


def chase_overdue_actions(engine):
    """Corrective actions past their deadline: remind the owner and escalate, once (spec 8)."""
    events = []
    for issue in engine.store.issues("open"):
        if issue["requirement"] != "corrective_action":
            continue
        data = json.loads(issue["data"] or "{}")
        if not data.get("due") or data.get("overdue_notified") or date.fromisoformat(data["due"]) >= engine.today:
            continue
        step = next((s for s in engine.store.steps(issue["id"]) if s["state"] not in DONE), None) or \
            engine.store.steps(issue["id"])[-1]
        ctx = _context(engine, issue, step)
        to = ctx.recipient("owner")
        subject, body = ctx.render("corrective_overdue")
        body, note = ctx.localise(body, to.get("language", "en"))
        ctx.write_outbox(f"overdue-{engine.today.isoformat()}", to, subject, body, {"Translation": note} if note else None)
        out = _escalate(engine, issue, step, (engine.today - date.fromisoformat(data["due"])).days)
        data["overdue_notified"] = engine.today.isoformat()
        engine.store.update_issue(issue["id"], data=json.dumps(data))
        engine.store.audit("scheduler", "corrective_action_overdue", issue["id"], {"due": data["due"], **out})
        events.append((issue["id"], "overdue: owner reminded and escalated"))
    return events


def follow_up_appointments(engine):
    """Bookings whose date has passed with no outcome: ask the provider what happened (spec 6, 7)."""
    events = []
    for a in engine.store.appointments():
        if a["status"] not in ("requested", "confirmed") or not a["date"] or date.fromisoformat(a["date"]) >= engine.today:
            continue
        notes = json.loads(a["notes"]) if (a["notes"] or "").startswith("{") else {}
        if notes.get("followed_up_on"):
            continue
        issue = engine.store.issue(a["issue_id"])
        if not issue or issue["status"] == "resolved":
            continue
        step = engine.store.step(a["step_id"])
        ctx = _context(engine, issue, step)
        ctx.data["appointment_date"] = a["date"]
        subject, body = ctx.render("appointment_followup")
        prov = next((p for p in engine.kb.providers if p["id"] == a["provider_id"]), {})
        ctx.step = {**step, "id": f"{a['id']}"}
        ctx.write_outbox(f"followup-{engine.today.isoformat()}", {"name": a["provider_name"], "channel": "email",
                                                                  "address": prov.get("email", "")}, subject, body)
        notes["followed_up_on"] = engine.today.isoformat()
        engine.store.update_appointment(a["id"], notes=json.dumps(notes))
        engine.store.audit("scheduler", "appointment_followed_up", a["id"], {"date": a["date"], "provider": a["provider_id"]})
        events.append((a["id"], "provider asked whether it went ahead"))
    return events


def run_customer(folder, state_dir=None, today=None):
    engine = Engine(folder, state_dir=state_dir, today=today)
    if engine.customer.company.get("sample") and CUSTOMERS_ROOT.resolve() in Path(folder).resolve().parents:
        raise ValueError("SAMPLE data found in data/customers/ - move it to data/sample/ (real customers only there)")
    engine.store.audit("scheduler", "daily_run_started", engine.customer.company["id"],
                       {"date": engine.today.isoformat()})
    scan = engine.scan()
    advanced = engine.advance()
    chased = chase_stalled(engine)
    overdue = chase_overdue_actions(engine)
    followed = follow_up_appointments(engine)
    summary = {"customer": engine.customer.company["id"], "date": engine.today.isoformat(),
               "opened": scan["opened"], "updated": scan["updated"], "closed": scan["closed"],
               "actions": len(advanced),
               "chased": [ref for ref, what in chased if what.startswith("chased")],
               "escalated": [ref for ref, what in chased if what.startswith("escalated")],
               "overdue_actions": [ref for ref, _ in overdue],
               "appointments_followed_up": [ref for ref, _ in followed],
               "approvals_waiting": len(engine.approval_queue()),
               "reviews_waiting": len(engine.review_queue())}
    engine.store.audit("scheduler", "daily_run_finished", summary["customer"], summary)
    return summary


def daily_run(folders, state_dir=None, today=None):
    """Run every customer. One customer failing never stops the others."""
    results = []
    for folder in folders:
        try:
            results.append({"status": "ok", **run_customer(folder, state_dir, today)})
        except Exception as exc:  # noqa: BLE001 - report and carry on with the next customer
            results.append({"status": "failed", "customer": Path(folder).name, "error": repr(exc),
                            "trace": traceback.format_exc(limit=3)})
    return results
