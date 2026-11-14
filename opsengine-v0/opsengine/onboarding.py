"""Onboarding a real customer: create their folder from the template and check it is complete.

Real customer folders live in data/customers/ and are git-ignored (GDPR)."""
import json
import re
import shutil
from pathlib import Path

from .detect import parse_date
from .knowledge import LANGUAGE_NAMES, ROOT, Knowledge

CUSTOMERS = ROOT / "data" / "customers"
TEMPLATE = CUSTOMERS / "_template"
DATE_KEYS = ("expires", "issued", "signed", "completed_on", "approved_by_main_contractor")


def create_customer(customer_id, name, root=CUSTOMERS):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", customer_id):
        raise ValueError("customer id must be lowercase letters, digits and underscores, e.g. acme_drylining")
    dest = Path(root) / customer_id
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    shutil.copytree(TEMPLATE, dest)
    company = json.loads((dest / "company.json").read_text(encoding="utf-8"))
    company["id"], company["name"] = customer_id, name
    (dest / "company.json").write_text(json.dumps(company, indent=2) + "\n", encoding="utf-8")
    return dest


def _placeholders(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _placeholders(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _placeholders(v, f"{path}[{i}]")
    elif isinstance(obj, str) and ("REPLACE" in obj or obj == "YYYY-MM-DD"):
        yield path


def check_customer(folder, kb=None):
    """Return a list of plain-English problems; empty means ready to scan."""
    kb = kb or Knowledge.load()
    folder = Path(folder)
    problems = []
    try:
        company = json.loads((folder / "company.json").read_text(encoding="utf-8"))
        workers = json.loads((folder / "workers.json").read_text(encoding="utf-8"))
        docs = json.loads((folder / "documents.json").read_text(encoding="utf-8")) \
            if (folder / "documents.json").exists() else []
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read customer files: {exc}"]
    for fname, data in (("company.json", company), ("workers.json", workers), ("documents.json", docs)):
        problems += [f"{fname}: {p} still needs filling in" for p in _placeholders(data)]
    problems += sample_problems(folder, company, kb)
    worker_ids = {w.get("id") for w in workers}
    for w in workers:
        if w.get("language", "en") not in LANGUAGE_NAMES:
            problems.append(f"workers.json: {w.get('id')} language {w.get('language')!r} is not supported yet")
        for key in ("name", "phone", "role"):
            if not w.get(key):
                problems.append(f"workers.json: {w.get('id')} has no {key}")
    if not company.get("owner", {}).get("email"):
        problems.append("company.json: owner email missing (needed for approvals)")
    if not company.get("sites"):
        problems.append("company.json: no sites listed")
    for s in company.get("sites", []):
        if s.get("main_contractor") not in kb.main_contractors:
            problems.append(f"company.json: site {s.get('id')} main contractor {s.get('main_contractor')!r} has no "
                            f"rules file in rules/main_contractors/ (send me their prequalification form)")
        for wid in s.get("workers", []):
            if wid not in worker_ids:
                problems.append(f"company.json: site {s.get('id')} lists unknown worker {wid}")
    seen = set()
    for d in docs:
        if d.get("id") in seen:
            problems.append(f"documents.json: duplicate document id {d.get('id')}")
        seen.add(d.get("id"))
        if d.get("type") not in kb.requirements:
            problems.append(f"documents.json: {d.get('id')} has unknown type {d.get('type')!r}")
        if d.get("holder") != "company" and d.get("holder") not in worker_ids:
            problems.append(f"documents.json: {d.get('id')} holder {d.get('holder')!r} is not a worker")
        for key in DATE_KEYS:
            if d.get(key) and "REPLACE" not in str(d[key]) and d[key] != "YYYY-MM-DD":
                try:
                    parse_date(d[key])
                except ValueError:
                    problems.append(f"documents.json: {d.get('id')} {key} is not a date (YYYY-MM-DD)")
    return problems


def is_sample(company):
    return bool(company.get("sample")) or "SAMPLE" in str(company.get("name", "")).upper()


def sample_problems(folder, company, kb):
    """Keep SAMPLE data and real customers apart, in both directions."""
    folder = Path(folder).resolve()
    real_folder = CUSTOMERS.resolve() in folder.parents
    if is_sample(company):
        if real_folder:
            return ["company.json: this is SAMPLE data but it sits in data/customers/ (real customers only) - move it to data/sample/"]
        return []
    out = []
    if not real_folder and (ROOT / "data" / "sample").resolve() in folder.parents:
        out.append("company.json: a real customer is in data/sample/, which is committed to git - move it to data/customers/")
    for s in company.get("sites", []):
        mc = kb.main_contractors.get(s.get("main_contractor"), {})
        if mc.get("sample"):
            out.append(f"company.json: site {s.get('id')} uses SAMPLE main contractor rules ({mc.get('name')}) - "
                       f"replace with rules from the real contractor's prequalification form")
    return out
