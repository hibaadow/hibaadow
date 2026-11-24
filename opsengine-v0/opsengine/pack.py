"""Main contractor pack: everything one main contractor asks for, in one place.

    python -m opsengine pack --customer <folder> --contractor <id> --out <dir>

Writes <out>/<contractor>/pack.html (print or save as PDF from any browser) and an evidence/
folder with a copy of every card, certificate and document on file. It shows exactly what's in
date, what's outstanding and why, and never presents a missing or expired item as fine.
"""
import html
import json
import shutil
from datetime import date
from pathlib import Path

from . import config
from .labels import nice_date
from .report import compliance_register

e_ = html.escape
STATUS = {"ok": ("In date", "ok"), "expiring": ("Expiring soon", "warn"), "expired": ("Expired", "bad"),
          "missing": ("Missing", "bad"), "incomplete": ("Incomplete", "bad"), "content_gap": ("Needs updating", "warn"),
          "out_of_use": ("Out of use", "bad")}


def pack_rows(engine, contractor_id):
    """Register rows that matter to this main contractor: its sites, the people on them, and the company."""
    c = engine.customer
    sites = [s for s in c.company.get("sites", []) if s.get("main_contractor") == contractor_id]
    if not sites:
        raise ValueError(f"{c.company['name']} has no site for main contractor {contractor_id}")
    site_ids = {s["id"] for s in sites}
    workers = {w for s in sites for w in s.get("workers", [])}
    rows = []
    for r in compliance_register(engine):
        kind = r["holder_kind"]
        if r["context"] and r["context"] not in site_ids and r["context"] != contractor_id:
            continue
        if kind == "worker" and r["holder"] not in workers:
            continue
        rows.append(r)
    return sites, rows


def build_pack(engine, contractor_id, out_dir):
    kb, c = engine.kb, engine.customer
    mc = kb.main_contractors.get(contractor_id, {"name": contractor_id})
    sites, rows = pack_rows(engine, contractor_id)
    out = Path(out_dir) / contractor_id
    if out.exists():
        shutil.rmtree(out)
    (out / "evidence").mkdir(parents=True)
    docs = {d["id"]: d for d in engine.store.documents()}
    copied = {}
    for r in rows:
        d = docs.get(r["document"])
        ev = (d or {}).get("evidence")
        if ev and r["document"] not in copied:
            src = engine.evidence_dir / ev["stored_as"]
            if src.is_file():
                name = f"{r['document']}{src.suffix}"
                shutil.copy2(src, out / "evidence" / name)
                copied[r["document"]] = name
    good = sum(1 for r in rows if r["status"] == "ok")
    outstanding = [r for r in rows if r["status"] not in ("ok", "expiring")]
    blocking = [r for r in outstanding if r["blocks_site_access"]]
    groups = [("Company", [r for r in rows if r["holder_kind"] == "company"]),
              ("Workers", [r for r in rows if r["holder_kind"] == "worker"]),
              ("Subcontractors", [r for r in rows if r["holder_kind"] == "subcontractor"]),
              ("Plant and equipment", [r for r in rows if r["holder_kind"] == "asset"])]

    def row_html(r):
        label, cls = STATUS.get(r["status"], (r["status"], "warn"))
        file = copied.get(r["document"])
        link = f'<a href="evidence/{e_(file)}">{e_(r["document"])}</a>' if file else e_(r["document"] or "-")
        exp = nice_date(date.fromisoformat(r["expires"])) if r["expires"] else "-"
        return (f'<tr><td>{e_(r["holder_name"])}</td><td>{e_(r["name"])}</td><td><span class="s {cls}">{label}</span></td>'
                f'<td>{exp}</td><td>{link}</td></tr>')

    sections = "".join(
        f'<h2>{title}</h2><table><tr><th>Who / what</th><th>Requirement</th><th>Status</th><th>Expires</th><th>On file</th></tr>'
        + "".join(row_html(r) for r in sorted(g, key=lambda r: (r["holder_name"], r["name"]))) + "</table>"
        for title, g in groups if g)
    todo = "".join(f'<li><b>{e_(r["holder_name"])}</b>: {e_(r["name"])} ({e_(STATUS.get(r["status"], (r["status"],))[0].lower())})'
                   f'{" - <i>stops site access</i>" if r["blocks_site_access"] else ""}</li>' for r in outstanding)
    brand = config.brand()
    verdict = ("Ready for site: everything this main contractor requires is in date." if not outstanding else
               f"Not ready yet: {len(outstanding)} item(s) outstanding" + (f", {len(blocking)} of which stop site access." if blocking else "."))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e_(c.company['name'])} - pack for {e_(mc['name'])}</title>
<style>
body{{font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#16181d;margin:32px auto;max-width:900px;padding:0 20px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:17px;margin:26px 0 8px}} .muted{{color:#5b6170}}
.top{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #1f9d55;padding-bottom:12px;margin-bottom:18px}}
.brand{{font-weight:800;color:#1f9d55}} .verdict{{padding:12px 16px;border-radius:10px;font-weight:700;margin:14px 0}}
.verdict.ok{{background:#e3f5ea;color:#11643a}} .verdict.no{{background:#fdecea;color:#9b1c1c}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e4e1d8;vertical-align:top}}
th{{background:#f6f5f1}} .s{{padding:2px 8px;border-radius:999px;font-weight:700;font-size:12px;white-space:nowrap}}
.s.ok{{background:#e3f5ea;color:#11643a}} .s.warn{{background:#fff4d6;color:#7a5600}} .s.bad{{background:#fdecea;color:#9b1c1c}}
.note{{font-size:12px;color:#5b6170;margin-top:28px}} @media print{{body{{margin:0}} a{{color:inherit}}}}
</style></head><body>
<div class="top"><div><h1>{e_(c.company['name'])}</h1>
<div class="muted">Compliance pack for <b>{e_(mc['name'])}</b> · prepared {nice_date(engine.today)}</div></div>
<div class="brand">{e_(brand)}</div></div>
<div class="muted">Sites: {", ".join(e_(s['name']) for s in sites)}</div>
<div class="verdict {'ok' if not outstanding else 'no'}">{e_(verdict)}</div>
<div class="muted">{good} of {len(rows)} requirements in date.</div>
{f'<h2>Outstanding</h2><ul>{todo}</ul>' if outstanding else ''}
{sections}
<p class="note">Prepared by {e_(brand)} from the records on file on {nice_date(engine.today)}. {e_(brand)} coordinates and records
compliance work; it does not certify compliance. Certificates and sign-offs come from the qualified people named on each document.
Copies of the documents marked "on file" are in the evidence folder.</p>
</body></html>"""
    (out / "pack.html").write_text(page, encoding="utf-8")
    (out / "pack.json").write_text(json.dumps({"customer": c.company["id"], "contractor": contractor_id, "prepared": engine.today.isoformat(),
                                               "ready": not outstanding, "in_date": good, "total": len(rows),
                                               "outstanding": [{k: r[k] for k in ("holder", "requirement", "status", "context")} for r in outstanding],
                                               "evidence": copied}, indent=1), encoding="utf-8")
    engine.store.audit("engine", "contractor_pack_built", contractor_id,
                       {"ready": not outstanding, "in_date": good, "total": len(rows), "evidence_files": len(copied)})
    return out
