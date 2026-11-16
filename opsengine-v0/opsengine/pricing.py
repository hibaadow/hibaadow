"""Plans and prices (data/pricing.json): which plan a customer is on, what it includes, what they pay,
and whether their plan still fits them. Display and checks only: nothing here stops work."""
import json

from .knowledge import ROOT

# what the engine actually does -> the plan feature that covers it
USES = {"multiple_sites": "multiple_sites", "subcontractors": "subcontractors", "corrective_actions": "corrective_actions",
        "find_provider": "provider_comparisons", "request_quotes": "provider_comparisons", "book_service": "bookings",
        "weekly_reports": "weekly_reports"}


def load(root=ROOT):
    return json.loads((root / "data" / "pricing.json").read_text(encoding="utf-8"))


def plan(plan_id, prices=None):
    prices = prices or load()
    return next((p for p in prices["plans"] if p["id"] == plan_id), None)


def suggested(workers, prices=None):
    prices = prices or load()
    for p in prices["plans"]:
        if p["workers_max"] is None or workers <= p["workers_max"]:
            return p
    return prices["plans"][-1]


def included(plan_id, prices=None):
    """Every feature in a plan, including those of the plans below it (Enterprise is custom)."""
    prices = prices or load()
    out = {}
    for p in prices["plans"]:
        if p.get("includes_previous", True) or p["id"] == plan_id:
            out.update(p["features"])
        if p["id"] == plan_id:
            return out
    return {}


def first_plan_with(feature, prices=None):
    prices = prices or load()
    return next((p for p in prices["plans"] if feature in included(p["id"], prices)), None)


def active_workers(customer):
    return sum(1 for w in customer.workers.values() if not w.get("left_on"))


def customer_plan(customer, prices=None):
    """The customer's plan and monthly bill (excluding VAT)."""
    prices = prices or load()
    chosen = customer.company.get("plan") or {}
    p = plan(chosen.get("id"), prices)
    extras = []
    if p:
        sites = len(customer.sites)
        if p.get("sites_included") and sites > p["sites_included"]:
            each = chosen.get("extra_site_eur")
            extras.append({"name": f"{sites - p['sites_included']} additional site(s)",
                           "monthly_eur": each * (sites - p["sites_included"]) if each else None,
                           "price": f"{money_(each)} a month each" if each else "€30–€50 a month each, agreed with you"})
        blocks = chosen.get("extra_worker_blocks") or 0
        if blocks:
            extras.append({"name": f"{blocks * 25} additional workers", "monthly_eur": 100 * blocks, "price": f"€100 a month per 25"})
    known = p and p["monthly_eur"] is not None and all(x["monthly_eur"] is not None for x in extras)
    total = (p["monthly_eur"] + sum(x["monthly_eur"] for x in extras)) if known else None
    return {"plan": p, "extras": extras, "monthly_total_eur": total, "vat": prices["vat"],
            "onboarding_eur": (p or {}).get("onboarding_eur"), "agreed": chosen.get("agreed_monthly_eur")}


def money_(v):
    from .labels import money
    return money(v)


def fit_problems(engine, prices=None):
    """Plain-English notes for our team when a customer's plan no longer fits (never shown as a block)."""
    prices = prices or load()
    c = engine.customer
    p = plan((c.company.get("plan") or {}).get("id"), prices)
    if not p:
        return [f"No plan recorded. Suggested by size: {suggested(active_workers(c), prices)['name']}."]
    out = []
    workers = active_workers(c)
    allowed = (p["workers_max"] or 10 ** 6) + 25 * ((c.company.get("plan") or {}).get("extra_worker_blocks") or 0)
    if workers > allowed:
        nxt = suggested(workers, prices)
        out.append(f"{workers} workers is more than {p['name']} covers ({allowed}). Options: {nxt['name']} "
                   f"({money_(nxt['monthly_eur']) if nxt['monthly_eur'] else 'custom'} a month) or additional 25-worker blocks at €100 a month.")
    have = included(p["id"], prices)
    used = set()
    if len(c.sites) > 1:
        used.add("multiple_sites")
    if c.subcontractors:
        used.add("subcontractors")
    steps = engine.store.steps()
    used |= {USES[s["action"]] for s in steps if s["action"] in USES}
    if any(i["requirement"] == "corrective_action" for i in engine.store.issues()):
        used.add("corrective_actions")
    for f in sorted(used - set(have)):
        up = first_plan_with(f, prices)
        if f == "multiple_sites" and p.get("sites_included"):
            continue  # covered by the additional-site add-on
        out.append(f"Uses {included(up['id'], prices)[f].lower()}, which is in {up['name']}, not {p['name']}.")
    return out
