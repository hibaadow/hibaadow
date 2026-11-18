"""Compliance pack for one main contractor, in that contractor's own format ("pack" in
rules/main_contractors/<id>.json): their sections, their register columns, their file naming, photos
or not, and their size limit.

What goes in: only the company, the workers on that contractor's sites (not leavers), and the
subcontractors and equipment on those sites, and only the requirements that contractor needs.
Gaps are listed, never left out: a pack with anything that could stop work is marked INCOMPLETE.
Documents marked `share_as: confirmation` (written terms) are confirmed in the register, never attached.
Every file has a SHA-256 in MANIFEST.json, and each export is audited.

Sharing safeguards (packs carry names, card numbers and photos):
1. prepare(): builds the pack privately and records it; nothing can be downloaded yet. The recipient and
   destination come only from the contractor's rules file, and must be on its `verified_recipients` list
   (a real customer can't release a pack to an unverified or SAMPLE-verified recipient).
2. confirm(): a signed-in person confirms, seeing the recipient, destination and how many people's data it
   holds. Only then is a download link made: secret, for this customer's signed-in users only, expiring after
   LINK_HOURS and MAX_DOWNLOADS downloads.
3. download() and mark_sent() record who, when and to whom. mark_sent only accepts the verified destination.
4. Every pack is checked to contain only this customer's people and files, and its copy is deleted after
   `pack_files_days` (rules/retention.json) by the GDPR purge; the record of it stays."""
import csv
import hmac
import secrets
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from .labels import nice_date
from .report import compliance_register

LINK_HOURS = 72
MAX_DOWNLOADS = 3

STATUS = {"ok": "In order", "expiring": "In order (expires soon)", "missing": "Missing", "expired": "Expired",
          "incomplete": "Incomplete", "content_gap": "Needs revising", "out_of_use": "Out of use"}


def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-")[:60] or "item"


def contractors_for(engine):
    """Main contractors this customer works for, with their sites."""
    out = {}
    for sid, s in engine.customer.sites.items():
        out.setdefault(s["main_contractor"], []).append(sid)
    return out


def rows_for(engine, mc_id, site_ids):
    c = engine.customer
    holders = {"company"}
    for sid in site_ids:
        site = c.sites[sid]
        holders |= {w for w in site.get("workers", []) if w in c.workers and not c.workers[w].get("left_on")}
    holders |= {h for h in list(c.subcontractors) + list(c.assets) if any(s["id"] in site_ids for s in c.holder_sites(h))}
    rows = []
    for r in compliance_register(engine):
        needed_by = [x.strip() for x in (r["required_by"] or "").split(",") if x.strip()]
        if r["holder"] in holders and (r["context"] in ("", *site_ids)) and (mc_id in needed_by or r["requirement"] == "safe_to_use"):
            rows.append(r)
    return rows


def build(engine, mc_id, out_dir, site_id=None, by="engine"):
    kb, c = engine.kb, engine.customer
    mc = kb.main_contractors.get(mc_id)
    if not mc:
        raise ValueError(f"unknown main contractor {mc_id}")
    mine = contractors_for(engine).get(mc_id, [])
    if not mine:
        raise ValueError(f"{c.company['name']} has no sites with {mc['name']}")
    site_ids = [site_id] if site_id else mine
    if site_id and site_id not in mine:
        raise ValueError(f"site {site_id} isn't one of {mc['name']}'s sites")
    spec = mc.get("pack") or {"sections": [], "register_columns": ["Requirement", "Name", "Status", "Expiry"],
                              "file_naming": "{holder_name}_{type}{ext}", "include_photos": True, "file_prefix": ""}
    rows = rows_for(engine, mc_id, site_ids)
    section_of = {req: sec for sec in spec["sections"] for req in sec["requirements"]}
    other = {"code": "X", "title": "Other"}
    docs = {d["id"]: d for d in engine.store.documents()}
    stamp = engine.today.isoformat()
    name = f"{_slug(spec.get('file_prefix') or mc_id)}-{_slug(c.company['id'])}-{stamp}"
    folder = Path(out_dir) / name
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "documents").mkdir(parents=True)
    register, attached = [], 0
    order = [s["code"] for s in spec["sections"]] + ["X"]
    rows.sort(key=lambda r: (order.index(section_of.get(r["requirement"], other)["code"]), r["holder_name"], r["name"]))
    for r in rows:
        sec = section_of.get(r["requirement"], other)
        doc = docs.get(r["document"]) if r["document"] else None
        req = kb.requirements.get(r["requirement"], {})
        reference = ""
        if doc and req.get("share_as") == "confirmation":
            reference = f"Confirmed: signed {nice_date(doc['signed'])}" if doc.get("signed") else "Confirmed on file"
        elif doc:
            reference = doc.get("number") or doc.get("policy_number") or doc.get("reference") or doc["id"]
            ev = (doc.get("evidence") or {}).get("stored_as")
            if spec.get("include_photos") and ev and (engine.evidence_dir / ev).is_file():
                fname = spec["file_naming"].format(prefix=spec.get("file_prefix", ""), section=sec["code"], holder=_slug(r["holder"]),
                                                   holder_name=_slug(r["holder_name"]), type=_slug(r["requirement"]),
                                                   ext=Path(ev).suffix)
                shutil.copy2(engine.evidence_dir / ev, folder / "documents" / fname)
                reference += f" ({fname})"
                attached += 1
        values = {"Section": f"{sec['code']} {sec['title']}", "Requirement": r["name"], "Name": r["holder_name"],
                  "Status": STATUS.get(r["status"], r["status"]), "Expiry": nice_date(r["expires"]) if r["expires"] else "",
                  "Reference": reference}
        register.append({col: values.get(col, "") for col in spec["register_columns"]})
    gaps = [r for r in rows if r["status"] not in ("ok", "expiring")]
    blocking = [r for r in gaps if r["blocks_site_access"]]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=spec["register_columns"])
    w.writeheader()
    w.writerows(register)
    (folder / "register.csv").write_text(buf.getvalue(), encoding="utf-8")
    sample = bool(c.company.get("sample") or mc.get("sample"))
    sites = ", ".join(c.sites[s]["name"] for s in site_ids)
    cover = [f"# Compliance pack for {mc['name']}", "",
             *(["**SAMPLE DATA: fictional company and contractor. Not for submission.**", ""] if sample else []),
             f"- Subcontractor: {c.company['name']}", f"- Site(s): {sites}", f"- Prepared: {nice_date(stamp)}",
             f"- Status: **{'INCOMPLETE' if blocking else 'COMPLETE' if not gaps else 'COMPLETE, with items in progress'}**",
             f"- {len(rows) - len(gaps)} of {len(rows)} items in order; {len(blocking)} could stop work", ""]
    if gaps:
        cover += ["## Outstanding", ""] + [f"- {r['name']}: {r['holder_name']} ({STATUS.get(r['status'], r['status'])})" for r in gaps] + [""]
    cover += ["## Contents", "", "- register.csv: every item in this contractor's format",
              f"- documents/: {attached} supporting file(s)" + ("" if spec.get("include_photos") else " (this contractor asked for none)"),
              "- MANIFEST.json: SHA-256 of every file", "",
              "Employment terms are confirmed, not attached. Accident history is company-level only.",
              "OpsEngine prepares and records this pack; it does not certify compliance. Certificates are issued by "
              "the qualified people and bodies named in each record."]
    (folder / "cover.md").write_text("\n".join(cover) + "\n", encoding="utf-8")
    manifest = {"contractor": mc_id, "customer": c.company["id"], "sites": site_ids, "prepared": stamp, "sample": sample,
                "complete": not blocking, "files": {}}
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            manifest["files"][f.relative_to(folder).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    (folder / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    zpath = folder.with_suffix(".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(f, f"{name}/{f.relative_to(folder).as_posix()}")
    size_mb = zpath.stat().st_size / 1e6
    too_big = spec.get("max_size_mb") and size_mb > spec["max_size_mb"]
    engine.store.audit(by, "pack_exported", mc_id, {"sites": site_ids, "items": len(rows), "gaps": len(gaps),
                                                    "could_stop_work": len(blocking), "files": attached,
                                                    "size_mb": round(size_mb, 2), "too_big": bool(too_big)})
    return {"zip": zpath, "folder": folder, "items": len(rows), "gaps": len(gaps), "could_stop_work": len(blocking),
            "files": attached, "too_big": bool(too_big), "max_size_mb": spec.get("max_size_mb")}


# ---------------- sharing safeguards ----------------
def _now():
    return datetime.now(timezone.utc)


def recipient(engine, mc_id):
    """Where this contractor's packs go, and whether that destination is verified."""
    mc = engine.kb.main_contractors.get(mc_id) or {}
    sub = mc.get("submission", {})
    method, dest = sub.get("method", ""), sub.get("to", "")
    entry = next((v for v in (mc.get("pack") or {}).get("verified_recipients", [])
                  if v.get("destination") == dest and v.get("method") == method), None)
    real_customer = not engine.customer.company.get("sample")
    verified = bool(entry) and not (real_customer and entry.get("sample"))
    return {"name": mc.get("name", mc_id), "method": method, "destination": dest, "verified": verified,
            "verified_by": (entry or {}).get("verified_by", ""), "verified_on": (entry or {}).get("verified_on", "")}


def _record(engine, pack_id):
    row = engine.store.db.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone()
    return dict(row) if row else None


def listing(engine):
    return [dict(r) for r in engine.store.db.execute("SELECT * FROM packs ORDER BY id DESC")]


def _check_scope(engine, folder):
    """Nothing from another customer: every supporting file is one of this customer's evidence files."""
    own = {hashlib.sha256(f.read_bytes()).hexdigest() for f in engine.evidence_dir.glob("*") if f.is_file()} \
        if engine.evidence_dir.exists() else set()
    for f in (folder / "documents").glob("*"):
        if hashlib.sha256(f.read_bytes()).hexdigest() not in own:
            raise ValueError("pack contains a file that isn't this customer's; nothing was released")


def prepare(engine, mc_id, base_dir, site_id=None, by="engine"):
    n = engine.store.db.execute("SELECT COUNT(*) FROM packs").fetchone()[0] + 1
    pack_id = f"PK-{n:04d}"
    built = build(engine, mc_id, Path(base_dir) / pack_id, site_id, by)
    _check_scope(engine, built["folder"])
    rcpt = recipient(engine, mc_id)
    people = len({r["holder"] for r in rows_for(engine, mc_id, [site_id] if site_id else contractors_for(engine)[mc_id])
                  if r["holder"] in engine.customer.workers})
    rec = {"id": pack_id, "contractor": mc_id, "sites": json.dumps([site_id] if site_id else contractors_for(engine)[mc_id]),
           "recipient": rcpt["name"], "method": rcpt["method"], "destination": rcpt["destination"], "verified": int(rcpt["verified"]),
           "people": people, "files": built["files"], "items": built["items"], "gaps": built["gaps"],
           "folder": str(built["folder"]), "zip": str(built["zip"]),
           "zip_sha256": hashlib.sha256(Path(built["zip"]).read_bytes()).hexdigest(),
           "prepared_by": by, "prepared_at": _now().isoformat(timespec="seconds"), "max_downloads": MAX_DOWNLOADS}
    engine.store.db.execute(f"INSERT INTO packs ({', '.join(rec)}) VALUES ({', '.join('?' * len(rec))})", list(rec.values()))
    engine.store.db.commit()
    engine.store.audit(by, "pack_prepared", pack_id, {"contractor": mc_id, "destination": rcpt["destination"],
                                                     "verified": rcpt["verified"], "people": people, "files": built["files"]})
    return {**rec, "could_stop_work": built["could_stop_work"], "too_big": built["too_big"]}


def confirm(engine, pack_id, by, confirmed_contractor, ticked):
    """Explicit confirmation before anything can leave. Returns the one-time secret for the download link."""
    rec = _record(engine, pack_id)
    if not rec or rec["deleted_at"]:
        raise ValueError("no such pack")
    if rec["confirmed_at"]:
        raise ValueError("this pack has already been confirmed; prepare a new one if you need another link")
    if not ticked or confirmed_contractor != rec["contractor"]:
        raise ValueError("confirm the recipient: tick the box for the contractor shown")
    if not rec["verified"]:
        raise ValueError(f"{rec['destination']} isn't a verified destination for {rec['recipient']}; "
                         "an administrator must verify it with the contractor first")
    secret = secrets.token_hex(32)
    expires = (_now() + timedelta(hours=LINK_HOURS)).isoformat(timespec="seconds")
    engine.store.db.execute("UPDATE packs SET confirmed_by=?, confirmed_at=?, token_hash=?, expires_at=? WHERE id=?",
                            (by, _now().isoformat(timespec="seconds"), hashlib.sha256(secret.encode()).hexdigest(), expires, pack_id))
    engine.store.db.commit()
    engine.store.audit(by, "pack_confirmed", pack_id, {"recipient": rec["recipient"], "destination": rec["destination"],
                                                      "people": rec["people"], "expires": expires})
    return secret


def download(engine, pack_id, secret, by):
    """The zip, for a signed-in user of this customer holding the link. Every download is recorded."""
    rec = _record(engine, pack_id)
    if not rec or rec["deleted_at"] or not rec["token_hash"]:
        raise ValueError("this pack isn't available")
    if not hmac.compare_digest(hashlib.sha256((secret or "").encode()).hexdigest(), rec["token_hash"]):
        engine.store.audit(by, "pack_download_refused", pack_id, {"reason": "wrong link"})
        raise ValueError("this link isn't valid")
    if rec["expires_at"] < _now().isoformat(timespec="seconds"):
        raise ValueError("this link has expired; prepare a new pack")
    if rec["downloads"] >= rec["max_downloads"]:
        raise ValueError(f"this link has been used {rec['max_downloads']} times; prepare a new pack")
    data = Path(rec["zip"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != rec["zip_sha256"]:
        raise ValueError("the pack file has changed since it was prepared; prepare a new one")
    engine.store.db.execute("UPDATE packs SET downloads=downloads+1 WHERE id=?", (pack_id,))
    engine.store.db.commit()
    engine.store.audit(by, "pack_downloaded", pack_id, {"download": rec["downloads"] + 1, "of": rec["max_downloads"]})
    return Path(rec["zip"]).name, data


def mark_sent(engine, pack_id, by, sent_to):
    rec = _record(engine, pack_id)
    if not rec or not rec["confirmed_at"]:
        raise ValueError("confirm the pack before recording it as sent")
    if (sent_to or "").strip().lower() != rec["destination"].lower():
        raise ValueError(f"it can only be sent to the verified destination: {rec['destination']}")
    engine.store.db.execute("UPDATE packs SET sent_by=?, sent_at=?, sent_to=? WHERE id=?",
                            (by, _now().isoformat(timespec="seconds"), rec["destination"], pack_id))
    engine.store.db.commit()
    engine.store.audit(by, "pack_sent", pack_id, {"recipient": rec["recipient"], "to": rec["destination"], "method": rec["method"]})


def expired_copies(engine, days, today):
    """Pack copies older than `days` (records are kept)."""
    cutoff = (datetime.combine(today, datetime.min.time(), timezone.utc) - timedelta(days=days)).isoformat()
    return [r for r in listing(engine) if not r["deleted_at"] and r["prepared_at"] < cutoff]


def delete_copy(engine, rec, by):
    shutil.rmtree(Path(rec["zip"]).parent, ignore_errors=True)  # the pack's own folder: copy and zip
    engine.store.db.execute("UPDATE packs SET deleted_at=?, token_hash=NULL WHERE id=?", (_now().isoformat(timespec="seconds"), rec["id"]))
    engine.store.db.commit()
    engine.store.audit(by, "pack_deleted", rec["id"], {"reason": "retention"})
