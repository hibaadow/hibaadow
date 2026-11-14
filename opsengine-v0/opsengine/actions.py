"""Action executors. Each action does one concrete piece of work for an issue and returns a
result dict. Outgoing work (messages, booking requests, drafts) is written to the outbox -
in v0 nothing is actually sent; a connector layer (WhatsApp, email, portals) plugs in later."""
import json
from collections import defaultdict
from pathlib import Path

from datetime import date, timedelta

from . import connectors, llm
from .knowledge import LANGUAGE_NAMES
from .labels import join, money, nice_date


class ActionContext:
    def __init__(self, kb, customer, store, issue, step, prior, outbox, today):
        self.kb, self.customer, self.store = kb, customer, store
        self.issue, self.step, self.prior = issue, step, prior  # prior: {action: result} of earlier steps
        self.outbox, self.today = Path(outbox), today
        self.data = json.loads(issue.get("data") or "{}")
        self.req = kb.requirements[issue["requirement"]]

    # ---- helpers ----
    def vars(self, **extra):
        c, i = self.customer, self.issue
        worker = c.workers.get(i["holder"], {})
        site = c.sites.get(i["context"] or "", {})
        mc_id = site.get("main_contractor") or (i["context"] if i["context"] in self.kb.main_contractors else None)
        if not mc_id:
            mcs = json.loads(i["required_by"] or "[]")
            mc_id = mcs[0] if mcs else None
        mc = self.kb.main_contractors.get(mc_id, {})
        doc = next((d for d in self.store.documents() if d["id"] == self.data.get("doc_id")), {})
        kind = i["kind"]
        status = {"missing": "is not on file", "expired": f"expired on {nice_date(self.data.get('expires'))}",
                  "expiring": f"expires on {nice_date(self.data.get('expires'))}", "incomplete": "is incomplete",
                  "content_gap": "needs revising", "corrective": "needs corrective action",
                  "overdue": "is overdue"}.get(kind, kind)
        v = defaultdict(str, {
            "company_name": c.company["name"], "owner_first_name": c.company["owner"]["name"].split()[0],
            "requirement_name": self.req["name"], "status_phrase": status, "detail": i["detail"],
            "holder_name": c.holder_name(i["holder"]), "worker_name": worker.get("name", ""),
            "first_name": worker.get("name", "").split()[0] if worker else "",
            "site_name": site.get("name", ""), "main_contractor_name": mc.get("name", ""),
            "language_name": LANGUAGE_NAMES.get(worker.get("language", "en"), "English"),
            "policy_number": doc.get("policy_number", ""),
            "required_value": money(self.data["required_value"]) if self.data.get("required_value") else "",
            "current_value": money(self.data["current_value"]) if self.data.get("current_value") else "",
            "required_by_names": join([self.kb.main_contractors[m]["name"] for m in json.loads(i["required_by"] or "[]")
                                       if m in self.kb.main_contractors]),
            "cover_name": self.kb.wording.cover(i["requirement"], self.req["name"]),
        })
        owner = self.data.get("owner")
        v.update({"issue_id": i["id"], "action_title": self.data.get("title", ""), "due_date": nice_date(self.data["due"]) if self.data.get("due") else "",
                  "evidence_required": self.data.get("evidence_required", ""),
                  "owner_name": (c.holder_name(owner).split()[0] if owner in c.workers else
                                 c.company["owner"]["name"].split()[0] if owner in (None, "company") else c.holder_name(owner)),
                  "appointment_date": self.data.get("appointment_date", ""),
                  "action_note": (self.data["note"].strip() + " ") if self.data.get("note") else "",
                  "action_defect": self.data.get("defect") or self.data.get("title", ""),
                  "isolate_target": (c.holder_name(i["holder"]) if i["holder"] in c.assets
                                     else "the affected equipment or work area")})
        v.update(extra)
        return v

    def render(self, template_id, **extra):
        t = self.kb.templates[template_id]
        v = self.vars(**extra)
        return t["subject"].format_map(v), t["body"].format_map(v)

    def recipient(self, who):
        c = self.customer
        if who == "worker":
            w = c.workers[self.issue["holder"]]
            return {"name": w["name"], "channel": "whatsapp", "address": w["phone"], "language": w.get("language", "en")}
        if who == "broker":
            b = c.company.get("broker", {})
            return {"name": b.get("name", "Broker"), "channel": "email", "address": b.get("email", ""), "language": "en"}
        if who == "main_contractor":
            mc_id = c.sites.get(self.issue["context"] or "", {}).get("main_contractor")
            mc = self.kb.main_contractors.get(mc_id, {})
            sub = mc.get("submission", {})
            return {"name": mc.get("name", "Main contractor"), "channel": sub.get("method", "email"),
                    "address": sub.get("to", ""), "language": "en"}
        if who == "provider":
            p = (self.prior.get("find_provider") or {}).get("recommended")
            if p:
                return {"name": p["name"], "channel": "email", "address": p.get("email", ""), "language": "en"}
        if who == "subcontractor" or (who == "holder" and self.issue["holder"] in c.subcontractors):
            sub = c.subcontractors.get(self.issue["holder"], {})
            contact = sub.get("contact", {})
            return {"name": f"{contact.get('name', '')} ({sub.get('name', 'subcontractor')})".strip(),
                    "channel": "email", "address": contact.get("email", ""), "language": contact.get("language", "en")}
        if who == "holder" and self.issue["holder"] in c.workers:
            return self.recipient("worker")
        if who == "owner":
            owner = self.data.get("owner", "company")
            if owner in c.workers:
                w = c.workers[owner]
                return {"name": w["name"], "channel": "whatsapp", "address": w["phone"], "language": w.get("language", "en")}
            if owner in c.subcontractors:
                contact = c.subcontractors[owner].get("contact", {})
                return {"name": contact.get("name", c.subcontractors[owner]["name"]), "channel": "email",
                        "address": contact.get("email", ""), "language": contact.get("language", "en")}
            if owner == "ops":
                return {"name": "Ops team", "channel": "file", "address": "-", "language": "en"}
        if who == "ops":
            return {"name": "Ops team", "channel": "file", "address": "-", "language": "en"}
        o = c.company["owner"]
        return {"name": o["name"], "channel": "email", "address": o["email"], "language": o.get("language", "en")}

    def write_outbox(self, kind, to, subject, body, meta=None):
        self.outbox.mkdir(parents=True, exist_ok=True)
        path = self.outbox / f"{self.step['id']}-{kind}.md"
        lines = [f"# {subject}", "", f"- Kind: {kind}", f"- To: {to['name']} via {to['channel']} ({to['address']})",
                 f"- Issue: {self.issue['id']} ({self.issue['requirement']}, {self.issue['kind']})"]
        for k, v in (meta or {}).items():
            lines.append(f"- {k}: {v}")
        status = "internal" if to.get("channel") == "file" else connectors.send(to.get("channel"), to.get("address"), subject, body)
        lines += [f"- Delivery: {status}", "", body, ""]
        path.write_text("\n".join(lines), encoding="utf-8")
        self.store.log_comm("out", to.get("channel"), to.get("name"), to.get("address"), subject,
                            self.issue["id"], self.step["id"], status, str(path))
        return str(path)

    def localise(self, body, language):
        """Translate for non-English recipients; flag for a human if Claude is unavailable."""
        if language == "en":
            return body, None
        name = LANGUAGE_NAMES.get(language, language)
        translated = llm.translate(body, name)
        if translated:
            return f"{translated}\n\n---\nEnglish original:\n{body}", f"machine-translated to {name}: native review required"
        return f"[TRANSLATION NEEDED: {name}]\n\n{body}", f"needs translation to {name}"


# ---------------- actions ----------------

def message(ctx, who, template_id):
    to = ctx.recipient(who)
    subject, body = ctx.render(template_id)
    retry = (ctx.step.get("result") or {}).get("retry_reason")
    if retry:
        subject = f"Please resend: {subject}"
        body = f"We could not accept the document you sent ({retry}). Please send it again.\n\n{body}"
    body, note = ctx.localise(body, to["language"])
    path = ctx.write_outbox("message", to, subject, body, {"Translation": note} if note else None)
    return {"sent_to": to["name"], "channel": to["channel"], "outbox": path, "translation": note}


def a_message_worker(ctx):
    return message(ctx, "worker", ctx.step["spec"]["template"])


def a_message_customer(ctx):
    return message(ctx, "customer", ctx.step["spec"]["template"])


def a_request_document(ctx):
    return message(ctx, ctx.step["spec"].get("from", "customer"), ctx.step["spec"]["template"])


def provider_problems(p, today, area=None):
    """Reasons a provider can't be used today (spec 7: credentials checked for validity)."""
    out = []
    if not p.get("vetted"):
        out.append("not vetted")
    ins = p.get("insurance") or {}
    if not ins.get("expires"):
        out.append("no insurance on file")
    elif date.fromisoformat(ins["expires"]) < today:
        out.append(f"insurance expired {ins['expires']}")
    for q in p.get("qualifications") or []:
        if q.get("expires") and date.fromisoformat(q["expires"]) < today:
            out.append(f"{q['name']} expired {q['expires']}")
    if not p.get("qualifications"):
        out.append("no qualifications on file")
    areas = p.get("service_areas") or []
    if area and areas and area not in areas and "Ireland" not in areas:
        out.append(f"does not cover {area}")
    return out


MIN_SPARE_DAYS = 7  # the cheapest option must finish at least this long before the deadline


def provider_deadline(ctx):
    """When the work must be done by: the expiry for something about to lapse, today for anything already
    stopping work, or no deadline for lower-priority gaps."""
    if ctx.issue["kind"] == "expiring" and ctx.data.get("expires"):
        return date.fromisoformat(ctx.data["expires"]), "before it expires"
    if ctx.data.get("due"):
        return date.fromisoformat(ctx.data["due"]), "by the deadline"
    if ctx.issue["severity"] == "critical":
        return ctx.today, "needed before they can work on site"
    return None, ""


def choose_provider(ctx, options, lang, reliability):
    """Cheapest option that finishes with 7+ days to spare; faster and dearer only when time is tight.
    Providers teaching in the worker's language come first. Returns (choice, one-line reason, ranked)."""
    lang_name = LANGUAGE_NAMES.get(lang, lang)
    in_lang = [p for p in options if lang in p["languages"]]
    pool = in_lang or options
    note = "" if in_lang or lang == "en" else f" No course is offered in {lang_name}."
    deadline, why = provider_deadline(ctx)
    cheapest = lambda ps: sorted(ps, key=lambda p: (p["price_eur"], p["lead_days"], reliability(p)))
    fastest = lambda ps: sorted(ps, key=lambda p: (p["lead_days"], p["price_eur"], reliability(p)))
    done = lambda p: ctx.today + timedelta(days=p.get("lead_days", 7))
    if deadline is None:
        choice = cheapest(pool)[0]
        reason = "Cheapest option."
    else:
        in_time = [p for p in pool if (deadline - done(p)).days >= MIN_SPARE_DAYS]
        if in_time:
            choice = cheapest(in_time)[0]
            reason = "Cheapest option that's done in time."
        else:
            choice = fastest(pool)[0]
            reason = f"Fastest option: time is tight ({why})." if deadline > ctx.today else f"Fastest option: {why}."
    cheaper_elsewhere = [p for p in options if p["price_eur"] < choice["price_eur"] and lang not in p["languages"]]
    if in_lang and lang != "en" and cheaper_elsewhere and "Cheapest" in reason:
        reason = reason.replace("Cheapest option", f"Cheapest option in {lang_name}")
    ranked = [choice] + [p for p in cheapest(options) if p is not choice]
    return choice, reason + note, ranked


def a_find_provider(ctx):
    category = ctx.step["spec"]["category"]
    lang = ctx.customer.workers.get(ctx.issue["holder"], {}).get("language", "en")
    area = ctx.customer.area_for(ctx.issue["holder"], ctx.issue["context"])
    candidates = [p for p in ctx.kb.providers if p["category"] == category]
    excluded = {p["id"]: provider_problems(p, ctx.today, area) for p in candidates}
    options = [p for p in candidates if not excluded[p["id"]]]
    if not options:
        why = "; ".join(f"{p['name']}: {', '.join(excluded[p['id']])}" for p in candidates) or "none in the network"
        return {"status": "no_provider", "note": f"No usable provider for {category} ({why}): ops team must source one"}
    stats = ctx.store.provider_stats()
    reliability = lambda p: -(stats.get(p["id"], {}).get("reliability") or 0.0)
    choice, reason, ranked = choose_provider(ctx, options, lang, reliability)
    rows = ["| Provider | Price (EUR) | Lead time (days) | In worker's language | Credentials | Track record |",
            "| --- | --- | --- | --- | --- | --- |"]
    for p in ranked:
        st = stats.get(p["id"])
        record = f"{st['completed']}/{st['booked']} completed" if st else "new"
        rows.append(f"| {p['name']} | {p['price_eur']} | {p['lead_days']} | {'yes' if lang in p['languages'] else 'no'} "
                    f"| valid | {record} |")
    for p in candidates:
        if excluded[p["id"]]:
            rows.append(f"| ~~{p['name']}~~ | {p['price_eur']} | {p['lead_days']} | - | excluded: "
                        f"{', '.join(excluded[p['id']])} | - |")
    body = ("\n".join(rows) + f"\n\nRecommended: **{choice['name']}**. {reason} Prices are listed prices "
            "until the provider confirms a quote.")
    path = ctx.write_outbox("quote-comparison", {"name": "Internal", "channel": "file", "address": "-"},
                            f"Provider comparison: {category.replace('_', ' ')}", body)
    return {"recommended": choice, "alternatives": [p["id"] for p in ranked[1:]], "reason": reason,
            "excluded": {k: v for k, v in excluded.items() if v}, "area": area, "outbox": path}


def a_request_quotes(ctx):
    """Ask up to 3 eligible providers for availability and a firm price (spec 4, 6, 7)."""
    found = ctx.prior.get("find_provider") or {}
    if not found.get("recommended"):
        return {"status": "blocked", "note": "No provider to ask for quotes"}
    ids = [found["recommended"]["id"]] + found.get("alternatives", [])[:2]
    asked = []
    holder = ctx.customer.holder_name(ctx.issue["holder"])
    for pid in ids:
        p = next(x for x in ctx.kb.providers if x["id"] == pid)
        body = (f"Hello {p['name']}, please confirm your price and earliest available date for {ctx.req['name']} "
                f"({ctx.step['spec'].get('service', p['category'].replace('_', ' '))}) for {holder}, "
                f"{ctx.customer.company['name']}"
                f"{', area: ' + found['area'] if found.get('area') else ''}. Your listed price is EUR {p['price_eur']}. "
                "Nothing is booked until our customer approves.")
        prev_step = ctx.step
        ctx.step = {**ctx.step, "id": f"{prev_step['id']}-{pid}"}  # one outbox file per provider
        ctx.write_outbox("quote-request", {"name": p["name"], "channel": "email", "address": p["email"]},
                         f"Quote request: {ctx.req['name']}", body)
        ctx.step = prev_step
        ctx.store.add_quote(ctx.issue["id"], pid, p["name"], p["price_eur"], p["lead_days"], "requested (listed price)")
        asked.append(pid)
    return {"requested_from": asked}


def a_book_service(ctx):
    found = ctx.prior.get("find_provider") or {}
    p = found.get("recommended")
    if not p:
        return {"status": "blocked", "note": "No provider recommended; ops team to source manually"}
    problems = provider_problems(p, ctx.today, found.get("area"))
    if problems:  # credentials lapsed between recommendation and approval
        return {"status": "blocked", "note": f"{p['name']} can no longer be used: {', '.join(problems)}"}
    holder = ctx.issue["holder"]
    kind = "inspection" if holder in ctx.customer.assets else ("training" if p["category"].endswith("_course") else "service")
    when = (ctx.today + timedelta(days=p.get("lead_days", 7))).isoformat()
    if kind == "training":
        worker = ctx.customer.workers.get(holder, {})
        body = (f"Please book {worker.get('name', 'the attendee')} on your next available course "
                f"({p['category'].replace('_', ' ')}), on or after {when}. "
                f"Preferred language: {LANGUAGE_NAMES.get(worker.get('language', 'en'))}. ")
        subject = f"Booking request: {worker.get('name')}"
    else:
        asset = ctx.customer.assets.get(holder, {})
        site = ctx.customer.holder_sites(holder)
        body = (f"Please book {ctx.req['name'].lower()} of {ctx.customer.holder_name(holder)}"
                f"{' (serial ' + asset['serial'] + ')' if asset.get('serial') else ''}"
                f"{' at ' + site[0]['name'] if site else ''}, on or after {when}. "
                "Please send the report or certificate when done, listing any defects. ")
        subject = f"Booking request: {ctx.req['name']} - {ctx.customer.holder_name(holder)}"
    body += f"Invoice: {ctx.customer.company['name']}. Agreed price: EUR {p['price_eur']}. Approved by: {ctx.step.get('approved_by')}."
    appt = ctx.store.add_appointment({"issue_id": ctx.issue["id"], "step_id": ctx.step["id"], "provider_id": p["id"],
                                      "provider_name": p["name"], "holder": holder, "kind": kind, "date": when,
                                      "status": "requested", "price_eur": p["price_eur"], "notes": ""})
    ctx.store.audit("engine", "appointment_requested", appt, {"provider": p["id"], "date": when, "kind": kind,
                                                               "approved_by": ctx.step.get("approved_by")})
    to = {"name": p["name"], "channel": "email", "address": p["email"]}
    path = ctx.write_outbox("booking-request", to, subject, body, {"Approved by": ctx.step.get("approved_by"),
                                                                    "Appointment": f"{appt} on or after {when}"})
    return {"booked_with": p["id"], "price_eur": p["price_eur"], "appointment": appt, "date": when, "outbox": path}


def a_message_owner(ctx):
    return message(ctx, "owner", ctx.step["spec"]["template"])


def a_isolate_item(ctx):
    """Critical defect: tell the owner to take the item out of use before anything else."""
    result = message(ctx, "owner", ctx.step["spec"]["template"])
    holder = ctx.issue["holder"]
    ctx.store.audit("engine", "item_isolated", holder, {"issue": ctx.issue["id"], "item": ctx.customer.holder_name(holder),
                                                         "reason": ctx.data.get("defect") or ctx.data.get("title")})
    return {**result, "isolated": ctx.customer.holder_name(holder), "isolated_on": ctx.today.isoformat()}


def a_close_action(ctx):
    """Final sign-off on a high-risk corrective action, after evidence was verified."""
    return {"closed_by": ctx.step.get("approved_by"), "proof": ctx.issue.get("proof")}


def a_draft_document(ctx):
    doc_type = ctx.step["spec"]["doc_type"]
    c = ctx.customer
    facts = {"company": c.company["name"], "trade": c.company.get("trade"), "owner": c.company["owner"]["name"],
             "workers": [{"name": w["name"], "role": w["role"], "language": w.get("language")} for w in c.workers.values()],
             "site": c.sites.get(ctx.issue["context"] or ""), "requirement": ctx.req["name"], "basis": ctx.req["basis"],
             "date": ctx.today.isoformat()}
    text = llm.draft(doc_type, facts)
    source = "claude"
    if not text:
        source = "template"
        text = (f"# DRAFT {ctx.req['name']} - {c.company['name']}\n\n"
                f"Status: DRAFT generated {ctx.today.isoformat()} - must be reviewed by a competent person before use.\n\n"
                f"## Scope\n{c.company.get('trade', '')} works{(' at ' + facts['site']['name']) if facts['site'] else ''}.\n\n"
                "## Hazards and controls\n[CHECK] To be completed from site walk-through and method of work.\n\n"
                "## Responsibilities\n[CHECK]\n\n## Workers briefed\n" +
                "\n".join(f"- {w['name']} ({w['role']}) - briefing language: {LANGUAGE_NAMES.get(w['language'], w['language'])}"
                          for w in facts["workers"]) + "\n")
    path = ctx.write_outbox("draft", {"name": "Reviewer", "channel": "file", "address": "-"},
                            f"Draft {ctx.req['name']}", text, {"Drafted with": source})
    return {"draft": path, "source": source}


def a_request_signature(ctx):
    who = ctx.step["spec"].get("from", "customer")
    to = ctx.recipient(who)
    draft = (ctx.prior.get("draft_document") or {}).get("draft", "the attached document")
    body = (f"Please review and sign the {ctx.req['name']} ({ctx.customer.holder_name(ctx.issue['holder'])}). "
            f"Document: {draft}. Reviewed and approved by: {ctx.step.get('approved_by')}. "
            "Reply with the signed copy and we will file it and send it to the main contractors that need it.")
    body, note = ctx.localise(body, to["language"])
    path = ctx.write_outbox("signature-request", to, f"Signature needed: {ctx.req['name']}", body,
                            {"Translation": note} if note else None)
    return {"sent_to": to["name"], "outbox": path}


def a_distribute(ctx):
    mcs = json.loads(ctx.issue.get("required_by") or "[]") or \
        ctx.customer.main_contractors_for(ctx.issue["holder"], ctx.issue["context"], ctx.kb)
    proof = ctx.issue.get("proof")
    sent = []
    for mc_id in mcs:
        mc = ctx.kb.main_contractors.get(mc_id)
        if not mc:
            continue
        sub = mc.get("submission", {})
        to = {"name": mc["name"], "channel": sub.get("method", "email"), "address": sub.get("to", "")}
        body = (f"Updated compliance record for {ctx.customer.company['name']}: {ctx.req['name']} for "
                f"{ctx.customer.holder_name(ctx.issue['holder'])}. Document reference: {proof}.")
        sent.append(ctx.write_outbox(f"distribute-{mc_id}", to, f"Updated {ctx.req['name']}", body))
    return {"distributed_to": mcs, "outbox": sent}


EXECUTORS = {
    "message_worker": a_message_worker,
    "message_customer": a_message_customer,
    "request_document": a_request_document,
    "find_provider": a_find_provider,
    "request_quotes": a_request_quotes,
    "message_owner": a_message_owner,
    "close_action": a_close_action,
    "isolate_item": a_isolate_item,
    "book_service": a_book_service,
    "draft_document": a_draft_document,
    "request_signature": a_request_signature,
    "distribute": a_distribute,
    # "verify" is handled by the engine itself because it re-runs detection.
}
