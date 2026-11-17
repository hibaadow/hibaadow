"""Subscription limits: workers, sites and routine safety document reviews per month (data/pricing.json).

Usage is shown to the customer and our team, with a notice at 80% and at 100% (once each per month).
At the limit we offer an upgrade or extra capacity. Limits never switch off monitoring, hide a compliance
issue, silence a safety notification or approve anything:
- workers and sites over the limit are still fully monitored; the customer is offered capacity and our
  team is told to follow up (charging for it needs the customer's agreement);
- a routine review over the month's allowance waits, visibly, in the reviewer's queue until an
  administrator adds capacity (once the customer has agreed) or the customer upgrades. It is never
  released or declined automatically.
One amendment resubmission of a declined draft is included in that draft's original review.

Administrators can change plan limits (state/plan-limits.json) and each customer's limits and extra
capacity (customer settings `plan_overrides`); every change is audited."""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import pricing
from .labels import money

ROUTINE_REVIEW_ACTION = "request_signature"   # a drafted RAMS / Safety Statement released or declined by the reviewer
METRICS = ("workers", "sites", "reviews_per_month")
LABELS = {"workers": "workers", "sites": "sites", "reviews_per_month": "routine safety document reviews this month"}


class LimitReached(Exception):
    """Plain-English reason a reviewer can't release or decline a draft yet."""


def _month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _state_root(engine):
    return engine.store.path.parent.parent


def plan_limit_overrides(state_root):
    f = Path(state_root) / "plan-limits.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def set_plan_limits(state_root, plan_id, limits, by, audit):
    """Administrator: change a plan's limits for every customer on it."""
    if not pricing.plan(plan_id):
        raise ValueError(f"unknown plan {plan_id!r}")
    clean = {m: int(limits[m]) for m in METRICS if limits.get(m) not in (None, "")}
    if any(v < 0 or v > 100000 for v in clean.values()):
        raise ValueError("limits must be between 0 and 100,000")
    data = plan_limit_overrides(state_root)
    data[plan_id] = clean
    (Path(state_root) / "plan-limits.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    audit(by, "plan_limits_changed", plan_id, clean)


def overrides(engine):
    return engine.store.setting("plan_overrides", {}) or {}


def set_overrides(engine, values, by):
    """Administrator: this customer's custom limits (enterprise), extra capacity and extra-site price."""
    allowed = {"workers", "sites", "reviews_per_month", "extra_worker_blocks", "extra_sites", "extra_site_eur"}
    clean = {}
    for k, v in values.items():
        if k in allowed and v not in (None, ""):
            n = float(v) if k == "extra_site_eur" else int(v)
            if n < 0 or n > 100000:
                raise ValueError(f"{k} must be between 0 and 100,000")
            clean[k] = n
    extra = overrides(engine).get("extra_reviews", {})
    if values.get("extra_reviews_this_month") not in (None, ""):
        extra = {**extra, _month(): int(values["extra_reviews_this_month"])}
    clean["extra_reviews"] = extra
    engine.store.set_setting("plan_overrides", clean, by)


def limits_for(engine):
    """{metric: number or None (no limit / custom not set)} after admin overrides."""
    c = engine.customer
    plan = pricing.plan((c.company.get("plan") or {}).get("id"))
    base = dict((plan or {}).get("limits") or {})
    base.update(plan_limit_overrides(_state_root(engine)).get((plan or {}).get("id"), {}))
    o = overrides(engine)
    for m in METRICS:
        if m in o:
            base[m] = o[m]
    return {m: base.get(m) for m in METRICS}


def extras(engine):
    o, plan = overrides(engine), engine.customer.company.get("plan") or {}
    return {"extra_worker_blocks": o.get("extra_worker_blocks", plan.get("extra_worker_blocks", 0)) or 0,
            "extra_sites": o.get("extra_sites", plan.get("extra_sites", 0)) or 0,
            "extra_reviews": (o.get("extra_reviews") or {}).get(_month(), 0),
            "extra_site_eur": o.get("extra_site_eur", plan.get("extra_site_eur"))}


def review_decisions(engine, month=None):
    """Reviewer decisions on drafted documents, in order, with whether each one counts toward the allowance."""
    month = month or _month()
    steps = {s["id"]: s for s in engine.store.steps() if s["action"] == ROUTINE_REVIEW_ACTION and s["approval_role"] == "safety_reviewer"}
    seen, out = {}, []
    for a in engine.store.audit_rows(raw=True):
        if a["event"] in ("approved", "rejected") and a["ref"] in steps:
            n = seen[a["ref"]] = seen.get(a["ref"], 0) + 1
            out.append({"step": a["ref"], "month": a["ts"][:7], "n": n, "counts": n != 2})  # the 2nd is the amendment
    return [d for d in out if d["month"] == month]


def usage(engine):
    c = engine.customer
    lim, ex = limits_for(engine), extras(engine)
    used = {"workers": pricing.active_workers(c), "sites": len(c.sites),
            "reviews_per_month": sum(1 for d in review_decisions(engine) if d["counts"])}
    allowance = {"workers": None if lim["workers"] is None else lim["workers"] + 25 * ex["extra_worker_blocks"],
                 "sites": None if lim["sites"] is None else lim["sites"] + ex["extra_sites"],
                 "reviews_per_month": None if lim["reviews_per_month"] is None else lim["reviews_per_month"] + ex["extra_reviews"]}
    out = {}
    for m in METRICS:
        a = allowance[m]
        pct = None if not a else round(100 * used[m] / a)
        level = "custom" if a is None else "over" if used[m] > a else "at" if used[m] >= a else "near" if pct is not None and pct >= 80 else "ok"
        out[m] = {"used": used[m], "allowance": a, "percent": pct, "level": level, "label": LABELS[m]}
    return out


def next_review_counts(engine, step_id):
    """Would deciding on this draft now use up allowance? (No for the included amendment resubmission.)"""
    previous = sum(1 for a in engine.store.audit_rows(raw=True) if a["event"] in ("approved", "rejected") and a["ref"] == step_id)
    return previous != 1


def check_review_allowed(engine, step):
    if step["action"] != ROUTINE_REVIEW_ACTION or step["approval_role"] != "safety_reviewer":
        return
    u = usage(engine)["reviews_per_month"]
    if u["allowance"] is not None and next_review_counts(engine, step["id"]) and u["used"] >= u["allowance"]:
        raise LimitReached(f"{engine.customer.company['name']} has used all {u['allowance']} routine reviews in their plan "
                           "this month. This draft stays in the queue until extra capacity is added or they upgrade.")


def offer(engine, metric):
    """What we offer at the limit."""
    plan = pricing.plan((engine.customer.company.get("plan") or {}).get("id"))
    prices = pricing.load()
    plans = prices["plans"]
    nxt = next((p for p in plans[plans.index(plan) + 1:]), None) if plan in plans else None
    up = (f"upgrade to {nxt['name']} ({money(nxt['monthly_eur']) + ' a month' if nxt['monthly_eur'] else 'custom pricing'})"
          if nxt else "talk to us about custom limits")
    if metric == "sites":
        site = extras(engine)["extra_site_eur"] or next(a["monthly_eur"] for a in prices["add_ons"] if a["id"] == "extra_site")
        return f"add sites at {money(site)} a month each, or {up}"
    if metric == "workers":
        return f"add 25 workers for €100 a month, or {up}"
    return f"ask us for extra review capacity this month, or {up}"


def notify(engine):
    """Notices at 80% and 100%, once each per metric per month, to the customer and our team."""
    from . import delivery
    events = []
    owner = engine.customer.company["owner"]
    for m, u in usage(engine).items():
        if u["level"] in ("ok", "custom"):
            continue
        level = 80 if u["level"] == "near" else 100
        key = f"usage_notice:{m}:{_month()}:{level}"
        if engine.store.setting(key):
            continue
        what = f"{u['used']} of {u['allowance']} {u['label']}"
        if level == 80:
            body = (f"Hi {owner['name'].split()[0]}, you're using {what} ({u['percent']}%) on your plan. "
                    f"Nothing changes yet. If you'll need more, you can {offer(engine, m)}.")
        else:
            keep = ("Every site and worker is still fully monitored and you'll still get every safety alert."
                    if m != "reviews_per_month" else
                    "New drafts wait in the safety reviewer's queue until capacity is added. Nothing is approved automatically, "
                    "and every compliance issue and safety alert stays visible.")
            body = (f"Hi {owner['name'].split()[0]}, you've reached your plan's limit: {what}. {keep} "
                    f"To carry on as normal, you can {offer(engine, m)}. Reply or use the portal and we'll set it up.")
        subject = f"Your OpsEngine plan: {u['label']} at {level}%"
        to = {"name": owner["name"], "channel": "email", "address": owner["email"], "language": owner.get("language", "en")}
        engine.outbox.mkdir(parents=True, exist_ok=True)
        path = engine.outbox / f"usage-{m}-{_month()}-{level}.md"
        status = delivery.dispatch(engine.store, engine.customer, to, subject, body)
        path.write_text(f"# {subject}\n\n- To: {to['name']} via email ({to['address']})\n- Delivery: {status}\n\n{body}\n", encoding="utf-8")
        engine.store.log_comm("out", "email", to["name"], to["address"], subject, "", "", status, str(path))
        engine.store.set_setting(key, {"used": u["used"], "allowance": u["allowance"]}, "limits")
        engine.store.audit("limits", "usage_notice", m, {"level": level, "used": u["used"], "allowance": u["allowance"],
                                                         "ops_follow_up": level == 100})
        events.append((m, level))
    return events
