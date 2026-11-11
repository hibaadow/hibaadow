"""Detection: compares a customer's documents against the rules library and returns findings.

A finding is a problem the engine must resolve: missing, expired, expiring or incomplete.
Detection is a pure function of (rules, customer, documents, today) so it is easy to test."""
from calendar import monthrange
from datetime import date


def parse_date(value):
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def effective_expiry(doc, req):
    if doc.get("expires"):
        return parse_date(doc["expires"])
    if req.get("review_every_months") and doc.get("issued"):
        return add_months(parse_date(doc["issued"]), req["review_every_months"])
    return None


def _targets(req, customer, kb):
    """Yield (holder, context, required_by) for every place this requirement applies."""
    scope = req["scope"]
    sites = customer.company.get("sites", [])
    if scope == "company":
        yield "company", None, sorted({s["main_contractor"] for s in sites})
    elif scope == "site":
        for s in sites:
            yield "company", s["id"], [s["main_contractor"]]
    elif scope == "worker_site":
        for s in sites:
            for w in s.get("workers", []):
                yield w, s["id"], [s["main_contractor"]]
    elif scope == "worker":
        cond = req.get("applies_if", {"all_workers": True})
        for wid, w in customer.workers.items():
            mcs = sorted({s["main_contractor"] for s in customer.worker_sites(wid)})
            if cond.get("all_workers"):
                yield wid, None, mcs
            elif cond.get("tasks_any") and set(cond["tasks_any"]) & set(w.get("tasks", [])):
                yield wid, None, mcs
            elif cond.get("required_by_main_contractor"):
                demanding = [m for m in mcs if req["id"] in kb.main_contractors.get(m, {}).get("extra_requirements", [])]
                if demanding:
                    yield wid, None, demanding


REQUIRED_FIELDS = {}  # requirement id -> required fields; refreshed by detect() from the rules library


def _best_doc(docs, req_id, holder, context):
    matches = [d for d in docs if d["type"] == req_id and d["holder"] == holder
               and (context is None or d.get("context") == context)]
    if not matches:
        return None
    # Prefer complete documents, then the latest expiry, so a bad upload never hides a good record.
    req_fields = REQUIRED_FIELDS.get(req_id, [])
    return max(matches, key=lambda d: (all(d.get(f) not in (None, "", []) for f in req_fields),
                                       d.get("expires") or d.get("issued") or "", d.get("id")))


def _missing_fields(doc, req):
    out = []
    for f in req.get("required_fields", []):
        v = doc.get(f)
        if v is None or v == "" or v == []:
            out.append(f)
    return out


def _severity(req, category):
    blocks = req.get("blocks_site_access", False)
    if category == "missing" or category == "expired":
        return "critical" if blocks else "medium"
    return "high" if blocks else "medium"


def detect(kb, customer, docs, today):
    REQUIRED_FIELDS.update({r["id"]: r.get("required_fields", []) for r in kb.requirements.values()})
    findings = []
    for req in kb.requirements.values():
        for holder, context, required_by in _targets(req, customer, kb):
            doc = _best_doc(docs, req["id"], holder, context)
            base = {"requirement": req["id"], "holder": holder, "context": context,
                    "required_by": required_by}

            def add(category, kind, detail, ctx=context, extra=None):
                key = f"{req['id']}|{holder}|{ctx or '-'}|{category}"
                f = {**base, "context": ctx, "key": key, "category": category, "kind": kind,
                     "severity": _severity(req, kind), "detail": detail, "doc_id": doc["id"] if doc else None}
                f.update(extra or {})
                findings.append(f)

            if doc is None:
                add("validity", "missing", f"No {req['name']} on file")
                continue

            exp = effective_expiry(doc, req)
            if exp is not None and exp < today:
                add("validity", "expired", f"{req['name']} expired on {exp.isoformat()}", extra={"expires": exp.isoformat()})
            elif exp is not None and (exp - today).days <= req.get("warn_days", 0):
                add("validity", "expiring", f"{req['name']} expires on {exp.isoformat()} ({(exp - today).days} days)",
                    extra={"expires": exp.isoformat()})

            missing = _missing_fields(doc, req)
            if missing:
                add("completeness", "incomplete", f"Missing: {', '.join(missing)}")

            # minimum values: rule baseline plus stricter main contractor overrides
            mins = dict(req.get("field_minimums", {}))
            checks = [(None, mins)] + [
                (mc, kb.main_contractors[mc].get("field_minimums", {}).get(req["id"], {}))
                for mc in required_by if mc in kb.main_contractors
            ]
            for mc, minimums in checks:
                for fname, minimum in minimums.items():
                    current = doc.get(fname)
                    if isinstance(current, (int, float)) and current < minimum:
                        who = kb.main_contractors[mc]["name"] if mc else "the baseline rule"
                        add("completeness", "incomplete",
                            f"{fname} {current:,} is below {minimum:,} required by {who}",
                            ctx=mc or context,
                            extra={"field": fname, "current_value": current, "required_value": minimum,
                                   **({"required_by": [mc]} if mc else {})})
    # merge findings that share a key (e.g. two completeness gaps on one document)
    merged = {}
    for f in findings:
        if f["key"] in merged:
            merged[f["key"]]["detail"] += "; " + f["detail"]
        else:
            merged[f["key"]] = f
    return list(merged.values())
