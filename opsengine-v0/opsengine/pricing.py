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


def customer_plan(customer, prices=None, extras=None):
    """The customer's plan and monthly bill (excluding VAT). `extras` comes from limits.extras when an engine
    is at hand (it includes administrator changes); otherwise company.json "plan"."""
    prices = prices or load()
    chosen = customer.company.get("plan") or {}
    ex = extras or {"extra_worker_blocks": chosen.get("extra_worker_blocks", 0) or 0,
                    "extra_sites": chosen.get("extra_sites", 0) or 0, "extra_site_eur": chosen.get("extra_site_eur")}
    p = plan(chosen.get("id"), prices)
    items = []
    if p and ex["extra_sites"]:
        each = ex["extra_site_eur"] or default_site_eur(prices)
        items.append({"name": f"{ex['extra_sites']} additional site(s)", "monthly_eur": each * ex["extra_sites"],
                      "price": f"{money_(each)} a month each"})
    if p and ex["extra_worker_blocks"]:
        blocks = ex["extra_worker_blocks"]
        items.append({"name": f"{blocks * 25} additional workers", "monthly_eur": 100 * blocks, "price": "€100 a month per 25"})
    total = (p["monthly_eur"] + sum(x["monthly_eur"] for x in items)) if p and p["monthly_eur"] is not None else None
    return {"plan": p, "extras": items, "monthly_total_eur": total, "vat": prices["vat"],
            "onboarding_eur": (p or {}).get("onboarding_eur"), "agreed": chosen.get("agreed_monthly_eur")}


def default_site_eur(prices=None):
    prices = prices or load()
    return next(a["monthly_eur"] for a in prices["add_ons"] if a["id"] == "extra_site")


def is_specialist(document_type, prices=None):
    """Routine reviews of RAMS and Safety Statements are never specialist work."""
    prices = prices or load()
    return document_type not in prices["routine_reviews_never_specialist"]


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
    from .limits import offer, usage
    for m, u in usage(engine).items():
        if u["level"] in ("at", "over"):
            out.append(f"{u['used']} of {u['allowance']} {u['label']} ({u['level']} the limit): {offer(engine, m)}.")
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
        if f == "multiple_sites":
            continue  # sites are counted against the plan's site limit instead
        out.append(f"Uses {included(up['id'], prices)[f].lower()}, which is in {up['name']}, not {p['name']}.")
    return out
