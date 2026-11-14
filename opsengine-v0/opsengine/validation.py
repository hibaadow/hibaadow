"""Checks every document before it is stored (audit defects D1-D4).

Pure: (document, rules, customer, today) -> (cleaned document, problems). A document with
problems is never stored as proof; the engine holds it for a person to correct. Dates are
normalised to ISO (Irish day-first formats accepted), money and counts to numbers, and
values that are implausible for the document type are flagged instead of trusted."""
import re
from datetime import date, datetime, timedelta

DATE_FIELDS = ("expires", "issued", "signed", "completed_on", "approved_by_main_contractor")
NUMBER_FIELDS = ("limit_eur", "operatives", "reportable_accidents", "lost_time_injuries", "years_trading")
PLAUSIBILITY_GRACE_DAYS = 60  # renewal dates often round to a month end
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d %b, %Y", "%d %B, %Y")


def parse_any_date(value):
    """ISO or Irish day-first dates -> date. Two-digit years and anything else -> None."""
    if isinstance(value, date):
        return value
    text = re.sub(r"\s+", " ", str(value).strip())
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", text):
        text = text[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value):
    """'EUR 6,500,000', '€6.5m', '6.5 million', '13m', 6500000 -> int. Anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace(",", "").replace("€", "").replace("eur", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|million|mn|k|thousand)?", text)
    if not m:
        return None
    n = float(m.group(1)) * {"m": 1e6, "million": 1e6, "mn": 1e6, "k": 1e3, "thousand": 1e3, None: 1}[m.group(2)]
    return int(round(n))


def validate_document(doc, kb, customer, today):
    problems = []
    clean = dict(doc)
    for key in ("id", "type", "holder"):
        if not clean.get(key):
            problems.append(f"missing '{key}'")
    doc_type, holder = clean.get("type"), clean.get("holder")
    req = kb.requirements.get(doc_type) if doc_type else None
    if doc_type and not req:
        problems.append(f"unknown document type {doc_type!r}")
    if holder and holder != "company" and customer.holder_kind(holder) == "unknown":
        problems.append(f"unknown holder {holder!r} (not a worker, subcontractor or asset of {customer.company.get('name')})")
    if doc_type == "corrective_action" and not (clean.get("action") or clean.get("defect")):
        problems.append("corrective action evidence must name the action (ISS-...) or the defect it fixes")
    for f in DATE_FIELDS:
        v = clean.get(f)
        if v in (None, ""):
            continue
        d = parse_any_date(v)
        if d is None:
            problems.append(f"{f} {v!r} is not a date we can read (use e.g. 2027-12-31 or 31/12/2027)")
        else:
            clean[f] = d.isoformat()
    for f in NUMBER_FIELDS:
        v = clean.get(f)
        if v in (None, ""):
            continue
        n = parse_number(v)
        if n is None:
            problems.append(f"{f} {v!r} is not a number we can read")
        else:
            clean[f] = n
    if req and not problems:
        exp = clean.get("expires")
        max_years = req.get("max_validity_years")
        if exp and max_years and date.fromisoformat(exp) > today + timedelta(days=round(365.25 * max_years) + PLAUSIBILITY_GRACE_DAYS):
            problems.append(f"expiry {exp} is more than {max_years} years away, which is not plausible for a {req['name']}")
        issued = clean.get("issued")
        if issued and date.fromisoformat(issued) > today + timedelta(days=1):
            problems.append(f"issue date {issued} is in the future")
    return clean, problems
