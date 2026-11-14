"""Customer-facing weekly summary and the engine's own operating metrics."""
import json

from datetime import datetime
from statistics import median

from .labels import nice_date

DONE = ("done", "skipped")  # same as engine.DONE; kept here to avoid an import cycle

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


ACTION_WORDS = {
    "message_worker": "Messaged the worker", "message_customer": "Messaged you", "message_owner": "Told the owner",
    "request_document": "Asked for the document", "find_provider": "Compared providers",
    "request_quotes": "Asked providers for quotes", "book_service": "Booking", "draft_document": "Drafted the document",
    "request_signature": "Sent for signature", "verify": "Checked the proof", "distribute": "Sent to main contractor",
    "close_action": "Sign-off", "isolate_item": "Told to stop using it",
}
STATE_WORDS = {"done": "done", "waiting": "waiting", "awaiting_approval": "needs approval", "pending": "next",
               "blocked": "with our team", "rejected": "declined", "skipped": "not needed"}


def current_step(engine, issue):
    return next((s for s in engine.store.steps(issue["id"]) if s["state"] not in DONE), None)


def where_it_stands(engine, issue):
    if issue["status"] == "resolved":
        return "Sorted, proof on file" if issue["proof"] else "Sorted"
    s = current_step(engine, issue)
    if not s:
        return "Closing"
    if s["state"] == "awaiting_approval":
        who = {"customer": "your OK", "safety_reviewer": "the safety reviewer", "ops": "our team"}[s["approval_role"]]
        text = f"Waiting for {who}"
    elif s["state"] == "waiting":
        r = s["result"] or {}
        text = f"Waiting for {r.get('sent_to', 'a reply')}"
        appt = engine.store.appointments(issue_id=issue["id"])
        if appt and appt[-1]["status"] in ("requested", "confirmed"):
            text += f" (booked with {appt[-1]['provider_name']}, {nice_date(appt[-1]['date'])})"
    elif s["state"] == "blocked":
        text = "Our team is handling this"
    else:
        text = ACTION_WORDS.get(s["action"], s["action"])
    if issue["status"] == "escalated":
        text += " · escalated to our team"
    return text


def title_of(engine, issue):
    if issue["requirement"] == "corrective_action":
        return json.loads(issue["data"] or "{}").get("title", issue["detail"])
    return issue["detail"]


SEVERITY_WORDS = {"critical": "Can stop work", "high": "High", "medium": "Medium"}


def customer_stats(engine):
    """What a customer cares about: sorted this week, days to sort, what could stop work (no automation rate)."""
    from datetime import date as _date
    sorted_week, durations = 0, []
    for i in engine.store.issues("resolved"):
        data = json.loads(i["data"] or "{}")
        done = data.get("resolved_on") or (i["resolved_at"] or "")[:10]
        opened = data.get("opened_on") or (i["created_at"] or "")[:10]
        try:
            d_done, d_open = _date.fromisoformat(done), _date.fromisoformat(opened)
        except ValueError:
            continue
        if 0 <= (engine.today - d_done).days < 7:
            sorted_week += 1
        durations.append(max(0, (d_done - d_open).days))
    return {"sorted_this_week": sorted_week,
            "average_days_to_sort": round(sum(durations) / len(durations), 1) if durations else None,
            "could_stop_work": len(risk_overview(engine)["blocking"])}


def weekly_summary(engine):
    c = engine.customer
    stats = customer_stats(engine)
    open_issues = sorted(engine.store.issues("open"), key=lambda i: (SEV_ORDER.get(i["severity"], 9), i["id"]))
    queue = engine.approval_queue()
    yours = [q for q in queue if q["role"] == "customer"]
    lines = [f"# Compliance summary: {c.company['name']}", f"As of {nice_date(engine.today)}", ""]
    lines.append(f"**{stats['could_stop_work']} item(s) could stop people working on site. "
                 f"{stats['sorted_this_week']} sorted this week, {len(open_issues)} in progress, "
                 f"{len(yours)} need your OK.**")
    lines.append("")
    if yours:
        lines += ["## Needs your OK", ""] + [f"- {q['summary']}" for q in yours] + [""]
    others = len(queue) - len(yours)
    if others:
        lines += [f"{others} other item(s) are with the safety reviewer or our team.", ""]
    if open_issues:
        lines += ["## In progress", "", "| Issue | Priority | Who | What | Where it stands |", "| --- | --- | --- | --- | --- |"]
        for i in open_issues:
            lines.append(f"| {i['id']} | {SEVERITY_WORDS.get(i['severity'], i['severity'])} | {c.holder_name(i['holder'])} "
                         f"| {title_of(engine, i)} | {where_it_stands(engine, i)} |")
        lines.append("")
    done = engine.store.issues("resolved")
    if done:
        lines += ["## Sorted, with proof on file", ""]
        for i in done:
            lines.append(f"- {engine.kb.requirements[i['requirement']]['name']} for {c.holder_name(i['holder'])}")
        lines.append("")
    avg = stats["average_days_to_sort"]
    lines += ["## This week", "",
              f"- Issues sorted this week: {stats['sorted_this_week']}",
              f"- Average days to sort: {avg if avg is not None else 'nothing sorted yet'}",
              f"- Items that could stop work: {stats['could_stop_work']}", ""]
    return "\n".join(lines)


# ---------------- central compliance record (spec 1 and 10) ----------------

def compliance_register(engine):
    """One row per requirement per person/company/subcontractor/asset/site: what is on file and its status."""
    from .detect import _best_doc, _targets, detect, effective_expiry
    kb, c, docs = engine.kb, engine.customer, engine.store.documents()
    findings = {}
    for f in detect(kb, c, docs, engine.today):
        findings.setdefault((f["requirement"], f["holder"], f["context"]), []).append(f)
    rank = {"missing": 0, "expired": 1, "incomplete": 2, "content_gap": 3, "expiring": 4}
    rows = []
    for req in kb.requirements.values():
        for holder, context, required_by in _targets(req, c, kb):
            doc = _best_doc(docs, req["id"], holder, context)
            fs = engine_findings(findings, req["id"], holder, context, kb)
            kinds = sorted({f["kind"] for f in fs}, key=lambda k: rank.get(k, 9))
            status = kinds[0] if kinds else "ok"
            exp = effective_expiry(doc, req) if doc else None
            rows.append({"requirement": req["id"], "name": req["name"], "holder": holder,
                         "holder_name": c.holder_name(holder), "holder_kind": c.holder_kind(holder),
                         "context": context or "", "status": status, "document": doc["id"] if doc else "",
                         "expires": exp.isoformat() if exp else "", "blocks_site_access": bool(req.get("blocks_site_access")),
                         "required_by": ", ".join(required_by), "detail": "; ".join(f["detail"] for f in fs)})
    for item in engine.out_of_use():
        rows.append({"requirement": "safe_to_use", "name": "Safe to use", "holder": item["holder"],
                     "holder_name": item["name"], "holder_kind": c.holder_kind(item["holder"]), "context": "",
                     "status": "out_of_use", "document": item["issue"], "expires": "",
                     "blocks_site_access": True, "required_by": "", "detail": f"Out of use until repaired: {item['reason']}"})
    return rows


def engine_findings(findings, rid, holder, context, kb=None):
    """Findings for one register row. A contractor's stricter minimum is filed under the contractor's id."""
    out = []
    for (r, h, ctx), fs in findings.items():
        if r == rid and h == holder and (ctx == context or (kb and ctx in kb.main_contractors)):
            out += fs
    return out


def risk_overview(engine):
    """Flags potential compliance risks: what could stop work, by site, and what is about to lapse."""
    reg = compliance_register(engine)
    by_site = {}
    for r in reg:
        if r["status"] == "ok":
            continue
        sites = [r["context"]] if r["context"] in engine.customer.sites else \
            [s["id"] for s in engine.customer.holder_sites(r["holder"])] or ["company-wide"]
        for s in sites:
            site = by_site.setdefault(s, {"blocking": 0, "other": 0})
            site["blocking" if r["blocks_site_access"] and r["status"] in ("missing", "expired", "out_of_use") else "other"] += 1
    return {"blocking": [r for r in reg if r["blocks_site_access"] and r["status"] in ("missing", "expired", "out_of_use")],
            "lapsing_soon": [r for r in reg if r["status"] == "expiring"],
            "by_site": by_site, "overdue_actions": [a for a in engine.corrective_actions("open")
                                                    if a.get("due") and a["due"] < engine.today.isoformat()]}


def export_records(engine, out_dir):
    """Everything an auditor or main contractor might ask for, as plain files (spec 10)."""
    import csv
    import shutil
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def write_csv(name, rows):
        rows = list(rows)
        with open(out / name, "w", newline="", encoding="utf-8") as f:
            if not rows:
                f.write("")
                return
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow({k: (json.dumps(v, default=str) if isinstance(v, (dict, list)) else v) for k, v in r.items()})

    write_csv("compliance_register.csv", compliance_register(engine))
    write_csv("issues.csv", engine.store.issues())
    write_csv("actions.csv", engine.store.steps())
    write_csv("communications.csv", engine.store.comms())
    write_csv("appointments.csv", engine.store.appointments())
    write_csv("quotes.csv", engine.store.quotes())
    write_csv("audit_log.csv", engine.store.audit_rows())
    (out / "documents.json").write_text(json.dumps(engine.document_history(), indent=2, default=str), encoding="utf-8")
    if engine.evidence_dir.exists():
        shutil.copytree(engine.evidence_dir, out / "evidence", dirs_exist_ok=True)
    ok, bad = engine.store.verify_audit()
    (out / "README.txt").write_text(
        f"Compliance records for {engine.customer.company['name']}, exported {engine.today.isoformat()}.\n"
        f"Audit log hash chain: {'intact' if ok else f'BROKEN at entry {bad}'} ({len(engine.store.audit_rows())} entries).\n"
        "Files: compliance_register.csv (status of every requirement), issues.csv, actions.csv (every step, "
        "who approved it), communications.csv, appointments.csv, quotes.csv, audit_log.csv (append-only, "
        "hash-chained), documents.json (every version), evidence/ (files named by SHA-256).\n"
        "OpsEngine coordinates and records; it does not certify compliance. Certificates are issued by the "
        "qualified people named in each record.\n", encoding="utf-8")
    engine.store.audit("engine", "records_exported", str(out), {"audit_intact": ok})
    return out
