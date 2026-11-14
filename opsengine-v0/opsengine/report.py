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
            site["blocking" if r["blocks_site_access"] and r["status"] in ("missing", "expired") else "other"] += 1
    return {"blocking": [r for r in reg if r["blocks_site_access"] and r["status"] in ("missing", "expired")],
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
