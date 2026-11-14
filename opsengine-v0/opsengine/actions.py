"""Action executors. Each action does one concrete piece of work for an issue and returns a
result dict. Outgoing work (messages, booking requests, drafts) is written to the outbox -
in v0 nothing is actually sent; a connector layer (WhatsApp, email, portals) plugs in later."""
import json
from collections import defaultdict
from pathlib import Path

from . import llm
from .knowledge import LANGUAGE_NAMES


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
        status = {"missing": "is not on file", "expired": f"expired on {self.data.get('expires')}",
                  "expiring": f"expires on {self.data.get('expires')}", "incomplete": "is incomplete"}[kind]
        v = defaultdict(str, {
            "company_name": c.company["name"], "owner_first_name": c.company["owner"]["name"].split()[0],
            "requirement_name": self.req["name"], "status_phrase": status, "detail": i["detail"],
            "holder_name": c.holder_name(i["holder"]), "worker_name": worker.get("name", ""),
            "first_name": worker.get("name", "").split()[0] if worker else "",
            "site_name": site.get("name", ""), "main_contractor_name": mc.get("name", ""),
            "language_name": LANGUAGE_NAMES.get(worker.get("language", "en"), "English"),
            "policy_number": doc.get("policy_number", ""),
            "required_value": f"{self.data.get('required_value', ''):,}" if self.data.get("required_value") else "",
            "current_value": f"{self.data.get('current_value', ''):,}" if self.data.get("current_value") else "",
        })
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
        o = c.company["owner"]
        return {"name": o["name"], "channel": "email", "address": o["email"], "language": o.get("language", "en")}

    def write_outbox(self, kind, to, subject, body, meta=None):
        self.outbox.mkdir(parents=True, exist_ok=True)
        path = self.outbox / f"{self.step['id']}-{kind}.md"
        lines = [f"# {subject}", "", f"- Kind: {kind}", f"- To: {to['name']} via {to['channel']} ({to['address']})",
                 f"- Issue: {self.issue['id']} ({self.issue['requirement']}, {self.issue['kind']})"]
        for k, v in (meta or {}).items():
            lines.append(f"- {k}: {v}")
        lines += ["", body, ""]
        path.write_text("\n".join(lines), encoding="utf-8")
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


def a_find_provider(ctx):
    category = ctx.step["spec"]["category"]
    lang = ctx.customer.workers.get(ctx.issue["holder"], {}).get("language", "en")
    options = [p for p in ctx.kb.providers if p["category"] == category]
    if not options:
        return {"status": "no_provider", "note": f"No provider for {category}: ops team must source one"}
    # Prefer providers teaching in the worker's language, then urgency (lead time) for blocking issues, then price.
    urgent = ctx.issue["severity"] == "critical"
    ranked = sorted(options, key=lambda p: (lang not in p["languages"],
                                            p["lead_days"] if urgent else p["price_eur"],
                                            p["price_eur"] if urgent else p["lead_days"]))
    rows = ["| Provider | Price (EUR) | Lead time (days) | Teaches in worker's language |", "| --- | --- | --- | --- |"]
    for p in ranked:
        rows.append(f"| {p['name']} | {p['price_eur']} | {p['lead_days']} | {'yes' if lang in p['languages'] else 'no'} |")
    choice = ranked[0]
    reason = ("fastest available" if urgent else "cheapest") + (" with a course in the worker's language"
                                                                 if lang in choice["languages"] else "")
    body = "\n".join(rows) + f"\n\nRecommended: **{choice['name']}** ({reason})."
    path = ctx.write_outbox("quote-comparison", {"name": "Internal", "channel": "file", "address": "-"},
                            f"Provider comparison: {category}", body)
    return {"recommended": choice, "alternatives": [p["id"] for p in ranked[1:]], "reason": reason, "outbox": path}


def a_book_service(ctx):
    found = ctx.prior.get("find_provider") or {}
    p = found.get("recommended")
    if not p:
        return {"status": "blocked", "note": "No provider recommended; ops team to source manually"}
    worker = ctx.customer.workers.get(ctx.issue["holder"], {})
    body = (f"Please book {worker.get('name', 'the attendee')} on your next available course "
            f"({ctx.step['spec'].get('category', found.get('recommended', {}).get('category'))}). "
            f"Preferred language: {LANGUAGE_NAMES.get(worker.get('language', 'en'))}. "
            f"Invoice: {ctx.customer.company['name']}. Agreed price: EUR {p['price_eur']}.")
    to = {"name": p["name"], "channel": "email", "address": p["email"]}
    path = ctx.write_outbox("booking-request", to, f"Booking request: {worker.get('name')}", body,
                            {"Approved by": ctx.step.get("approved_by")})
    return {"booked_with": p["id"], "price_eur": p["price_eur"], "outbox": path}


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
    "book_service": a_book_service,
    "draft_document": a_draft_document,
    "request_signature": a_request_signature,
    "distribute": a_distribute,
    # "verify" is handled by the engine itself because it re-runs detection.
}
