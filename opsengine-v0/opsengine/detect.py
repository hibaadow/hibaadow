"""Detection: compares a customer's documents against the rules library and returns findings.

A finding is a problem the engine must resolve: missing, expired, expiring or incomplete.
Detection is a pure function of (rules, customer, documents, today) so it is easy to test."""
from calendar import monthrange
from datetime import date

from .labels import join, money, nice_date


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
    cond = req.get("applies_if", {})

    def demanding(mcs):
        """Main contractors (of mcs) that list this requirement in their extra requirements."""
        return [m for m in mcs if req["id"] in kb.main_contractors.get(m, {}).get("extra_requirements", [])]

    if scope == "company":
        mcs = sorted({s["main_contractor"] for s in sites})
        if cond.get("required_by_main_contractor"):
            mcs = demanding(mcs)
            if not mcs:
                return
        yield "company", None, mcs
    elif scope == "site":
        for s in sites:
            if cond.get("required_by_main_contractor") and not demanding([s["main_contractor"]]):
                continue
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
                if demanding(mcs):
                    yield wid, None, demanding(mcs)
    elif scope == "subcontractor":
        for sid, sub in customer.subcontractors.items():
            trades = cond.get("trades_any")
            if trades and not set(trades) & set(sub.get("trades", [])):
                continue
            yield sid, None, sorted({s["main_contractor"] for s in customer.holder_sites(sid)})
    elif scope == "asset":
        for aid, asset in customer.assets.items():
            types = cond.get("asset_types_any")
            if types and asset.get("type") not in types:
                continue
            if cond.get("uses_any") and not set(cond["uses_any"]) & set(asset.get("uses", [])):
                continue
            yield aid, None, sorted({s["main_contractor"] for s in customer.holder_sites(aid)})
    # scope "manual" (corrective actions) is never detected: people and inspections raise them


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
    W = kb.wording
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
                add("validity", "missing", W.phrase("missing_doc", requirement=req["name"]))
                continue

            try:
                exp = effective_expiry(doc, req)
            except ValueError:
                exp = None
                add("completeness", "incomplete", W.phrase("date_unreadable"))
            if exp is not None and exp < today:
                add("validity", "expired", W.phrase("expired", requirement=req["name"], date=nice_date(exp)),
                    extra={"expires": exp.isoformat()})
            elif exp is not None and (exp - today).days <= req.get("warn_days", 0):
                add("validity", "expiring", W.phrase("expiring", requirement=req["name"], date=nice_date(exp),
                                                     days=(exp - today).days), extra={"expires": exp.isoformat()})

            missing = _missing_fields(doc, req)
            if missing:
                add("completeness", "incomplete", W.phrase("missing_fields", fields=W.fields(missing)))

            for fname, allowed in req.get("field_allowed_values", {}).items():
                value = doc.get(fname)
                if value not in (None, "", []) and value not in allowed:
                    if fname == "result":
                        add("completeness", "incomplete", W.phrase("result_failed", event=W.event(req["id"])))
                    else:
                        add("completeness", "incomplete", W.phrase("not_accepted", field=W.field(fname), value=value,
                                                                   allowed=join(allowed).replace(" and ", " or ")))

            # minimum values: the rule's baseline plus stricter main contractor minimums. One issue per field,
            # at the highest value needed, listing every contractor it satisfies (one fix covers them all).
            fields = set(req.get("field_minimums", {}))
            for mc in required_by:
                fields |= set(kb.main_contractors.get(mc, {}).get("field_minimums", {}).get(req["id"], {}))
            for fname in sorted(fields):
                current = doc.get(fname)
                if current in (None, ""):
                    continue
                needs = [(None, req.get("field_minimums", {}).get(fname))] + [
                    (mc, kb.main_contractors[mc].get("field_minimums", {}).get(req["id"], {}).get(fname))
                    for mc in required_by if mc in kb.main_contractors]
                needs = [(mc, m) for mc, m in needs if m is not None]
                if isinstance(current, bool) or not isinstance(current, (int, float)):
                    add("completeness", "incomplete", W.phrase("not_a_number", field=W.field(fname)),
                        extra={"field": fname, "required_value": max(m for _, m in needs)})
                    continue
                short = [(mc, m) for mc, m in needs if current < m]
                if not short:
                    continue
                required = max(m for _, m in short)
                contractors = [mc for mc, _ in short if mc]
                possessive = "Your" if holder == "company" else f"{customer.holder_name(holder)}'s"
                cover = W.cover(req["id"], req["name"])
                if contractors:
                    named = sorted(contractors, key=lambda mc: -dict(short)[mc])
                    detail = W.phrase("below_minimum", possessive=possessive, cover=cover, current=money(current),
                                      needs=join(f"{kb.main_contractors[mc]['name']} needs {money(dict(short)[mc])}" for mc in named))
                    if len(named) > 1:
                        detail += ". " + W.phrase("covers_all", required=money(required),
                                                  both="both" if len(named) == 2 else f"all {len(named)}")
                else:
                    detail = W.phrase("below_baseline", possessive=possessive, cover=cover, current=money(current),
                                      required=money(required))
                add("completeness", "incomplete", detail,
                    extra={"field": fname, "current_value": current, "required_value": required,
                           "required_by": contractors or required_by})
    findings += content_findings(kb, customer, docs)
    # merge findings that share a key (e.g. two completeness gaps on one document)
    merged = {}
    for f in findings:
        if f["key"] in merged:
            merged[f["key"]]["detail"] += "; " + f["detail"]
        else:
            merged[f["key"]] = f
    return list(merged.values())


# ---------------- content review (spec section 2) ----------------

def _norm(text):
    return " ".join(str(text or "").lower().replace("(sample)", "").split())


def _same_company(a, b):
    drop = {"ltd", "limited", "dac", "plc", "teoranta", "sample", "(sample)"}
    ta = {t.strip(".,()") for t in _norm(a).split()} - drop
    tb = {t.strip(".,()") for t in _norm(b).split()} - drop
    return bool(ta and tb) and (ta <= tb or tb <= ta)


def review_document(req, doc, customer, context=None):
    """Pure content checks on one document. Returns a list of plain-English gaps.

    These are flags for a person, not a verdict: the engine never certifies a document."""
    checks = req.get("content_checks", {})
    gaps = []
    site = customer.sites.get(context or doc.get("context") or "", {})
    if checks.get("activities_cover_tasks") and site:
        text = " ".join(_norm(a) for a in doc.get("activities", []))
        tasks = sorted({t for w in site.get("workers", []) for t in customer.workers.get(w, {}).get("tasks", [])})
        for task in tasks:
            words = checks["activities_cover_tasks"].get(task)
            if words and not any(word in text for word in words):
                who = [customer.holder_name(w) for w in site.get("workers", [])
                       if task in customer.workers.get(w, {}).get("tasks", [])]
                gaps.append(f"does not cover {task} work done on site by {', '.join(who)}")
    if checks.get("briefed_workers_cover_site") and site and doc.get("briefed_workers") is not None:
        missing = [w for w in site.get("workers", []) if w not in doc.get("briefed_workers", [])]
        if missing:
            gaps.append("workers on site not briefed: " + ", ".join(customer.holder_name(w) for w in missing))
    if checks.get("signed_by_owner") and doc.get("signed_by"):
        owner = customer.company.get("owner", {}).get("name")
        directors = customer.company.get("directors", [])
        if owner and _norm(doc["signed_by"]) not in {_norm(owner), *map(_norm, directors)}:
            gaps.append(f"signed by {doc['signed_by']}, who is not listed as owner or director")
    if checks.get("insured_name_matches_holder") and doc.get("insured"):
        holder = customer.holder_name(doc.get("holder"))
        if not _same_company(doc["insured"], holder):
            gaps.append(f"the name on the insurance ({doc['insured']}) doesn't match {holder}")
    if checks.get("insured_name_matches_company") and doc.get("insured"):
        if not _same_company(doc["insured"], customer.company.get("name")):
            gaps.append(f"the name on the insurance ({doc['insured']}) doesn't match {customer.company.get('name')}")
    return gaps


def content_findings(kb, customer, docs):
    out = []
    for req in kb.requirements.values():
        if not req.get("content_checks"):
            continue
        for holder, context, required_by in _targets(req, customer, kb):
            doc = _best_doc(docs, req["id"], holder, context)
            if not doc:
                continue
            gaps = review_document(req, doc, customer, context)
            if gaps:
                out.append({"requirement": req["id"], "holder": holder, "context": context, "required_by": required_by,
                            "key": f"{req['id']}|{holder}|{context or '-'}|content", "category": "content",
                            "kind": "content_gap", "severity": "high" if req.get("blocks_site_access") else "medium",
                            "detail": f"{req['name']} needs review: " + "; ".join(gaps), "doc_id": doc["id"]})
    return out
