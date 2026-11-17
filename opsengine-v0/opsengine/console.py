"""Cross-customer operations console: every queue our team works, across all customers, most urgent first.

Read-only: it lists and links; every action still happens on the customer's own pages, with the same
access checks and audit trail. Reviewers see only the safety review queue."""
from datetime import date

from . import limits
from .engine import DONE
from .report import risk_overview

QUEUES = {
    "stops_work": "Could stop work",
    "safety_reviews": "Safety reviews waiting",
    "photo_checks": "Photos and documents to check",
    "escalated": "Escalated issues",
    "blocked": "Blocked steps",
    "failed_messages": "Messages that couldn't be delivered",
    "overdue_actions": "Overdue corrective actions",
    "customer_approvals": "Waiting on the customer's approval",
    "plan_limits": "Plan limits reached",
}
REVIEWER_QUEUES = {"safety_reviews"}
RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _days(today, since):
    try:
        return max(0, (today - date.fromisoformat(str(since)[:10])).days)
    except ValueError:
        return 0


def _since(step):
    r = step["result"] or {}
    return r.get("awaiting_since") or r.get("waiting_since") or (step["updated_at"] or "")[:10]


def items(engines, role="ops"):
    """engines: {customer id: Engine}. Returns a list of queue items, most urgent first."""
    out = []
    for cid, e in engines.items():
        name, today = e.customer.company["name"], e.today
        sev = {i["id"]: i["severity"] for i in e.store.issues()}

        def add(queue, title, severity, since, link, detail=""):
            out.append({"queue": queue, "customer_id": cid, "customer": name, "title": title, "severity": severity,
                        "age_days": _days(today, since), "link": link, "detail": detail})
        for s in e.store.steps(state="awaiting_approval"):
            prior = {p["action"]: p["result"] for p in e.store.steps(s["issue_id"]) if p["state"] in DONE and p["result"]}
            summary = e.approval_summary(s, prior)
            if s["approval_role"] == "safety_reviewer":
                held = ""
                try:
                    limits.check_review_allowed(e, s)
                except limits.LimitReached:
                    held = "Held: over the plan's review allowance"
                add("safety_reviews", summary, sev.get(s["issue_id"], "medium"), _since(s), f"/c/{cid}/reviewer", held)
            elif s["approval_role"] == "customer":
                add("customer_approvals", summary, sev.get(s["issue_id"], "medium"), _since(s), f"/c/{cid}/issue/{s['issue_id']}")
        if role == "reviewer":
            continue
        for r in risk_overview(e)["blocking"]:
            add("stops_work", f"{r['name']}: {r['holder_name']}", "critical", today, f"/c/{cid}/people", r["detail"])
        for r in e.review_queue():
            add("photo_checks", f"Check a document from {e.customer.holder_name(r['holder']) or 'an unknown sender'}",
                "high", r["created_at"], f"/c/{cid}/ops", "; ".join(r["reasons"])[:200])
        for i in e.store.issues("escalated"):
            add("escalated", i["detail"][:160], i["severity"], i["updated_at"], f"/c/{cid}/issue/{i['id']}")
        for s in e.store.steps(state="blocked"):
            add("blocked", f"{s['action'].replace('_', ' ')} for {s['issue_id']}", sev.get(s["issue_id"], "medium"),
                _since(s), f"/c/{cid}/issue/{s['issue_id']}", (s["result"] or {}).get("note", ""))
        for d in e.store.deliveries():
            if d["status"] in ("failed", "bounced", "complained"):
                add("failed_messages", f"{d['subject']} to {d['to_name']}", "high", d["updated_at"],
                    f"/c/{cid}/issue/{d['issue_id']}" if d["issue_id"] else f"/c/{cid}/messages", d["last_error"] or d["status"])
        for a in risk_overview(e)["overdue_actions"]:
            add("overdue_actions", a.get("title", a["detail"]), a["severity"], a["due"], f"/c/{cid}/issue/{a['id']}")
        for m, u in limits.usage(e).items():
            if u["level"] in ("at", "over"):
                add("plan_limits", f"{u['used']} of {u['allowance']} {u['label']}", "medium", today, "/admin/plans",
                    limits.offer(e, m))
    allowed = REVIEWER_QUEUES if role == "reviewer" else set(QUEUES)
    out = [x for x in out if x["queue"] in allowed]
    order = list(QUEUES)
    out.sort(key=lambda x: (RANK.get(x["severity"], 2), order.index(x["queue"]), -x["age_days"]))
    return out


def counts(rows):
    c = {q: 0 for q in QUEUES}
    for r in rows:
        c[r["queue"]] += 1
    return c
