"""GDPR basics in the software (AUDIT.md Phase 2). The legal documents themselves need a solicitor.

- inventory(): what personal data is held, why, where and for how long (docs/data-inventory.json).
- purge(): applies rules/retention.json. Dry run unless apply=True. Deletes old review uploads,
  removes leavers' evidence files and redacts their document records once the retention period has
  passed, and deletes old message files for resolved issues. Every deletion is audited as a count
  and a reason, never the deleted content.
- export_person(): everything held about one worker or subcontractor, for a subject access request.
"""
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from .whatsapp import digits

ROOT = Path(__file__).resolve().parent.parent
KEEP_ON_REDACT = {"id", "type", "holder", "context", "expires", "issued"}  # enough to show a record existed, nothing personal


CUSTOMER_SETTABLE = ("review_uploads_days", "leaver_photos_months", "leaver_records_years",
                     "leaver_whatsapp_prefs_days", "resolved_message_files_years")


def retention(root=ROOT, customer=None):
    """Default periods, with the customer's own choices (company.json "retention") on top."""
    r = json.loads((Path(root) / "rules" / "retention.json").read_text(encoding="utf-8"))
    chosen = (customer.company.get("retention") or {}) if customer else {}
    for k, v in chosen.items():
        if k in CUSTOMER_SETTABLE and isinstance(v, (int, float)) and v >= 0:
            r[k] = v
    r["customer_choices"] = {k: v for k, v in chosen.items() if k in CUSTOMER_SETTABLE}
    return r


def inventory(root=ROOT):
    return json.loads((Path(root) / "docs" / "data-inventory.json").read_text(encoding="utf-8"))


def _years_ago(today, years):
    return today - timedelta(days=round(365.25 * years))


def _months_ago(today, months):
    return today - timedelta(days=round(30.44 * months))


def purge(engine, apply=False, by="gdpr-purge"):
    """Returns what was (or would be) deleted, by reason. Nothing is touched unless apply=True."""
    r = retention(customer=engine.customer)
    today = engine.today
    plan = {"review_uploads": [], "leaver_evidence_files": [], "leaver_documents": [], "leaver_people_forgotten": [],
            "leaver_contact_prefs": [], "message_files": [], "workers_to_remove_from_workers_json": []}
    # 1. photos sent for review that a person rejected
    cutoff = (today - timedelta(days=r["review_uploads_days"])).isoformat()
    for rev in engine.store.reviews("rejected"):
        decided = (rev["decided_at"] or "")[:10]
        f = Path(rev["file"]) if rev["file"] else None
        if decided and decided <= cutoff and f and f.is_file() and engine.outbox.parent.resolve() in f.resolve().parents:
            plan["review_uploads"].append(str(f))
    left = {wid: str(w["left_on"])[:10] for wid, w in engine.customer.workers.items() if w.get("left_on")}

    def gone_for(cut):
        return {wid for wid, d in left.items() if d <= cut.isoformat()}
    # 2. leavers' WhatsApp preferences: on leaving (or after the customer's chosen days)
    for wid in gone_for(today - timedelta(days=r["leaver_whatsapp_prefs_days"])):
        phone = digits(engine.customer.workers[wid].get("phone"))
        if phone and engine.store.contact_pref(phone):
            plan["leaver_contact_prefs"].append(phone)
    # 3. leavers' card photos: soon after leaving
    photo_leavers = gone_for(_months_ago(today, r["leaver_photos_months"]))
    # 4. leavers' named records: kept for claims (about 6 years), then redacted and the person forgotten
    record_leavers = gone_for(_years_ago(today, r["leaver_records_years"]))
    for doc in engine.store.documents():
        ev = (doc.get("evidence") or {}).get("stored_as")
        if doc["holder"] in photo_leavers and ev and (engine.evidence_dir / ev).is_file():
            plan["leaver_evidence_files"].append(str(engine.evidence_dir / ev))
        if doc["holder"] in record_leavers and any(v != "[deleted]" for k, v in doc.items() if k not in KEEP_ON_REDACT):
            plan["leaver_documents"].append(doc["id"])
    plan["leaver_people_forgotten"] = sorted(record_leavers)
    plan["workers_to_remove_from_workers_json"] = sorted(record_leavers)
    # 5. message files for issues resolved long ago
    cutoff = _years_ago(today, r["resolved_message_files_years"]).isoformat()
    old_issues = {i["id"] for i in engine.store.issues("resolved")
                  if (json.loads(i["data"] or "{}").get("resolved_on") or (i["resolved_at"] or "")[:10]) <= cutoff}
    for c in engine.store.comms():
        if c["issue_id"] in old_issues and c["outbox"] and Path(c["outbox"]).is_file():
            plan["message_files"].append(c["outbox"])
    plan["message_files"] = sorted(set(plan["message_files"]))
    if apply:
        for f in plan["review_uploads"] + plan["leaver_evidence_files"] + plan["message_files"]:
            Path(f).unlink(missing_ok=True)
        for phone in plan["leaver_contact_prefs"]:
            engine.store.db.execute("DELETE FROM contact_prefs WHERE address=?", (phone,))
        engine.store.db.commit()
        for doc_id in plan["leaver_documents"]:
            engine.store.redact_document(doc_id, KEEP_ON_REDACT, by, "leaver retention period passed")
        for wid in plan["leaver_people_forgotten"]:
            w = engine.customer.workers[wid]
            name, phone = w.get("name", ""), w.get("phone", "")
            d = digits(phone)
            variants = [name, name.replace(" ", "_"), name.replace(" ", "-"), w.get("email", ""), phone, d, "+" + d]
            engine.store.erase_text(variants + [x for x in w.get("also_known_as", [])], "leaver retention period passed")
            engine.store.forget(variants)
        engine.store.audit(by, "personal_data_purged", engine.customer.company["id"],
                           {k: len(v) for k, v in plan.items() if k != "workers_to_remove_from_workers_json"} |
                           {"retention": {k: v for k, v in r.items() if not k.startswith("_") and k != "source"}})
    return plan


def purge_unmatched(state_dir, today, apply=False):
    """Inbound messages we couldn't match, after unmatched_inbound_days (OpsEngine is controller for these)."""
    days = retention()["unmatched_inbound_days"]
    folder = Path(state_dir) / "inbound-unmatched"
    cutoff = datetime.combine(today - timedelta(days=days), datetime.min.time()).timestamp()
    old = sorted(str(f) for f in folder.glob("*") if f.is_file() and f.stat().st_mtime < cutoff) if folder.exists() else []
    if apply:
        for f in old:
            Path(f).unlink(missing_ok=True)
    return old


def purge_signin_history(accounts, today, apply=False):
    """IP addresses in the account log, after signin_history_months: their tokens are forgotten."""
    months = retention()["signin_history_months"]
    cutoff = _months_ago(today, months).isoformat()
    n = accounts.store.db.execute("SELECT COUNT(*) FROM people WHERE kind='ip' AND last_seen < ?", (cutoff,)).fetchone()[0]
    if apply and n:
        accounts.store.forget(kinds=["ip"], before=cutoff)
        accounts.audit("gdpr-purge", "signin_history_purged", "", {"ip_addresses": n, "months": months})
    return n


def export_person(engine, holder, out_dir, by="subject-access"):
    """Everything held about one worker or subcontractor (subject access request)."""
    c = engine.customer
    kind = c.holder_kind(holder)
    if kind not in ("worker", "subcontractor"):
        raise ValueError("give a worker or subcontractor id")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    person = c.workers.get(holder) or c.subcontractors.get(holder)
    name = c.holder_name(holder)
    docs = [d for d in engine.store.documents() if d["holder"] == holder]
    issues = [i for i in engine.store.issues() if i["holder"] == holder or json.loads(i["data"] or "{}").get("owner") == holder]
    issue_ids = {i["id"] for i in issues}
    comms = [m for m in engine.store.comms() if m["issue_id"] in issue_ids or (m["to_name"] or "").startswith(name)]
    refs = issue_ids | {d["id"] for d in docs} | {s["id"] for i in issues for s in engine.store.steps(i["id"])}
    audit = [a for a in engine.store.audit_rows() if a["ref"] in refs or any(a["ref"].startswith(i + ".") for i in issue_ids)]
    (out / "files").mkdir(exist_ok=True)
    copied = 0
    for d in docs:
        ev = (d.get("evidence") or {}).get("stored_as")
        if ev and (engine.evidence_dir / ev).is_file():
            shutil.copy2(engine.evidence_dir / ev, out / "files" / ev)
            copied += 1
    for m in comms:
        if m["outbox"] and Path(m["outbox"]).is_file():
            shutil.copy2(m["outbox"], out / "files" / Path(m["outbox"]).name)
            copied += 1
    data = {"person": person, "kind": kind, "customer": c.company["name"], "documents": docs,
            "issues": [{**i, "steps": engine.store.steps(i["id"])} for i in issues], "messages": comms,
            "appointments": [a for a in engine.store.appointments() if a["holder"] == holder],
            "reviews": [r for r in engine.store.reviews() if r["holder"] == holder],
            "whatsapp_preferences": engine.store.contact_pref(digits(person.get("phone"))) if person else {},
            "audit_entries": audit}
    (out / "data.json").write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    (out / "README.txt").write_text(
        f"Personal data held by OpsEngine about {name}, on behalf of {c.company['name']}, exported {engine.today.isoformat()}.\n"
        f"data.json: the person's record, {len(docs)} document(s), {len(issues)} issue(s), {len(comms)} message(s), "
        f"bookings, photo reviews and {len(audit)} audit entries. files/: {copied} file(s) (card photos, certificates, messages).\n"
        "Check the export before sending: it may mention other people (e.g. in messages), who may need to be redacted.\n",
        encoding="utf-8")
    engine.store.audit(by, "subject_access_export", holder, {"documents": len(docs), "issues": len(issues),
                                                             "messages": len(comms), "files": copied})
    return out
