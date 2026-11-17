"""Compliance pack for one main contractor, in that contractor's own format ("pack" in
rules/main_contractors/<id>.json): their sections, their register columns, their file naming, photos
or not, and their size limit.

What goes in: only the company, the workers on that contractor's sites (not leavers), and the
subcontractors and equipment on those sites, and only the requirements that contractor needs.
Gaps are listed, never left out: a pack with anything that could stop work is marked INCOMPLETE.
Documents marked `share_as: confirmation` (written terms) are confirmed in the register, never attached.
Every file has a SHA-256 in MANIFEST.json, and each export is audited."""
import csv
import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from .labels import nice_date
from .report import compliance_register

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
