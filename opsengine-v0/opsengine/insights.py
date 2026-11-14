"""Continuous improvement (spec 11): patterns in the history, across one or many customers.

Recommendations are suggestions for a person to accept; the engine does not change its own
rules or playbooks."""
from collections import Counter, defaultdict
from datetime import datetime
from statistics import median


def _hours(i):
    if not i["resolved_at"]:
        return None
    return (datetime.fromisoformat(i["resolved_at"]) - datetime.fromisoformat(i["created_at"])).total_seconds() / 3600


def insights(engines):
    issues = [(e, i) for e in engines for i in e.store.issues()]
    by_req = Counter(i["requirement"] for _, i in issues)
    missing = Counter(i["requirement"] for _, i in issues if i["kind"] == "missing")
    reached_expired = Counter(i["requirement"] for _, i in issues if i["kind"] == "expired")
    keys = Counter((e.customer.company["id"], i["key"]) for e, i in issues)
    recurring = Counter(k.split("|")[0] for (_, k), n in keys.items() if n > 1)
    sites = Counter()
    for e, i in issues:
        names = [i["context"]] if i["context"] in e.customer.sites else [s["id"] for s in e.customer.holder_sites(i["holder"])]
        for s in names or ["company-wide"]:
            sites[f"{e.customer.company['name']} / {e.customer.sites.get(s, {}).get('name', s)}"] += 1
    close = defaultdict(list)
    for _, i in issues:
        h = _hours(i)
        if h is not None:
            close[i["requirement"]].append(h)
    providers = {}
    for e in engines:
        for pid, st in e.store.provider_stats().items():
            agg = providers.setdefault(pid, {"name": st["name"], "booked": 0, "completed": 0, "no_show": 0, "cancelled": 0})
            for k in ("booked", "completed", "no_show", "cancelled"):
                agg[k] += st[k]
    names = lambda rid: engines[0].kb.requirements.get(rid, {}).get("name", rid) if engines else rid
    recs = []
    for rid, n in reached_expired.most_common():
        if n >= 2:
            warn = engines[0].kb.requirements.get(rid, {}).get("warn_days", 0)
            recs.append(f"{names(rid)}: {n} items reached 'expired'. Consider warning earlier than {warn} days "
                        "(warn_days in rules/requirements.json) or booking renewals in a batch.")
    for rid, n in missing.most_common(3):
        if n >= 2:
            recs.append(f"{names(rid)} is often missing at onboarding ({n} times). Ask for it in the first request "
                        "to new customers and new starters.")
    for rid, n in recurring.most_common():
        recs.append(f"{names(rid)} keeps coming back ({n} recurring items). Look at the root cause, e.g. a standing "
                    "renewal booking or a named owner.")
    for pid, st in providers.items():
        closed = st["completed"] + st["no_show"] + st["cancelled"]
        if closed >= 2 and st["completed"] / closed < 0.75:
            recs.append(f"Provider {st['name']} completed only {st['completed']} of {closed} bookings. Review before using again.")
    return {
        "issues_total": len(issues),
        "most_common_problems": [(names(r), n) for r, n in by_req.most_common(8)],
        "frequently_missing": [(names(r), n) for r, n in missing.most_common(8)],
        "recurring": [(names(r), n) for r, n in recurring.most_common(8)],
        "hotspots": sites.most_common(8),
        "hours_to_close": {names(r): round(median(v), 1) for r, v in close.items()},
        "providers": providers,
        "recommendations": recs or ["Not enough history yet for recommendations."],
    }
