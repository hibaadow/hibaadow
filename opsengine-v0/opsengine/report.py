"""Customer-facing weekly summary and the engine's own operating metrics."""
import json
from datetime import datetime
from statistics import median

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2}


def metrics(engine):
    steps = engine.store.steps()
    executed = [s for s in steps if s["state"] in ("done", "waiting") and s["action"] != "verify"]
    auto = [s for s in executed if not s["approval_role"]]
    issues = engine.store.issues()
    resolved = [i for i in issues if i["status"] == "resolved" and i["resolved_at"]]
    hours = [(datetime.fromisoformat(i["resolved_at"]) - datetime.fromisoformat(i["created_at"])).total_seconds() / 3600
             for i in resolved]
    return {
        "issues_total": len(issues),
        "issues_open": len([i for i in issues if i["status"] != "resolved"]),
        "issues_resolved": len(resolved),
        "actions_taken": len(executed),
        "actions_without_human": len(auto),
        "automation_rate": round(100 * len(auto) / len(executed)) if executed else 0,
        "approvals_waiting": len(engine.approval_queue()),
        "median_hours_to_close": round(median(hours), 1) if hours else None,
    }


def weekly_summary(engine):
    c = engine.customer
    m = metrics(engine)
    open_issues = sorted(engine.store.issues("open"), key=lambda i: (SEV_ORDER.get(i["severity"], 9), i["id"]))
    lines = [f"# Compliance summary: {c.company['name']}", f"As of {engine.today.isoformat()}", ""]
    blocking = [i for i in open_issues if i["severity"] == "critical"]
    lines.append(f"**{len(blocking)} item(s) can stop people working on site. "
                 f"{m['issues_resolved']} resolved, {m['issues_open']} in progress, "
                 f"{m['approvals_waiting']} need your approval.**")
    lines.append("")
    queue = engine.approval_queue()
    if queue:
        lines += ["## Needs your OK", ""]
        for q in queue:
            lines.append(f"- [{q['step']}] ({q['role']}) {q['summary']}")
        lines.append("")
    if open_issues:
        lines += ["## In progress", "", "| Issue | Severity | Who | What | Where it stands |", "| --- | --- | --- | --- | --- |"]
        for i in open_issues:
            steps = engine.store.steps(i["id"])
            cur = next((s for s in steps if s["state"] not in ("done", "skipped")), None)
            stand = f"{cur['action']} ({cur['state']})" if cur else "closing"
            lines.append(f"| {i['id']} | {i['severity']} | {c.holder_name(i['holder'])} | {i['detail']} | {stand} |")
        lines.append("")
    done = engine.store.issues("resolved")
    if done:
        lines += ["## Resolved, with proof on file", ""]
        for i in done:
            lines.append(f"- {i['id']} {engine.kb.requirements[i['requirement']]['name']} - "
                         f"{c.holder_name(i['holder'])} - proof: {i['proof']}")
        lines.append("")
    lines += ["## Engine metrics", "", "```", json.dumps(m, indent=2), "```", ""]
    return "\n".join(lines)
