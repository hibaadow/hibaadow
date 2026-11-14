"""Command line for running the engine.

    python -m opsengine scan      --customer data/sample/liffey_interiors
    python -m opsengine advance   --customer ...
    python -m opsengine queue     --customer ...
    python -m opsengine approve ISS-0002.3 --by "Ciara Byrne" --customer ...
    python -m opsengine ingest path/to/doc.json --customer ...
    python -m opsengine report    --customer ...
    python -m opsengine audit     --customer ... [--verify]
    python -m opsengine new-customer acme_drylining --name "Acme Drylining Ltd"
    python -m opsengine check     --customer data/customers/acme_drylining
    python -m opsengine read-photo photo.jpg --holder w02 [--type safe_pass] --customer ...
    python -m opsengine reviews   --customer ...
    python -m opsengine review-accept REV-0001 --by "Name" [--type safe_pass] [--set number=SP-1 ...]
    python -m opsengine review-reject REV-0001 --by "Name" --reason "..."
    python -m opsengine daily     [--root data/customers] [--customer folder ...]
    python -m opsengine demo      (full scripted walkthrough on the sample firm)
"""
import argparse
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from . import onboarding, scheduler
from .engine import Engine
from .knowledge import ROOT
from .report import metrics, weekly_summary

SAMPLE = ROOT / "data" / "sample" / "liffey_interiors"


def ai_mode():
    from . import config, llm
    if config.mock_ai():
        return "mock (USE_MOCK_AI=true) - no Claude calls; sample photos use recorded reads"
    if llm.available():
        return f"live Claude ({llm.DEFAULT_MODEL})"
    return "off (no ANTHROPIC_API_KEY) - photos go to human review, translations are flagged"


def _engine(args):
    today = date.fromisoformat(args.today) if args.today else None
    return Engine(args.customer, state_dir=args.state, today=today)


def _print_events(events):
    for ref, what in events:
        print(f"  {ref:<12} {what}")


def cmd_scan(args):
    e = _engine(args)
    r = e.scan()
    print(f"Scanned: {r['findings']} finding(s). Opened {len(r['opened'])}, updated {len(r['updated'])}, closed {len(r['closed'])}.")
    for i in e.store.issues("open"):
        print(f"  {i['id']}  {i['severity']:<8} {e.customer.holder_name(i['holder']):<34} {i['detail']}")


def cmd_advance(args):
    e = _engine(args)
    _print_events(e.advance())


def cmd_queue(args):
    q = _engine(args).approval_queue()
    if not q:
        print("Nothing waiting for approval.")
    for item in q:
        print(f"  {item['step']:<12} [{item['role']}] {item['summary']}")


def cmd_approve(args):
    _print_events(_engine(args).approve_group(args.step, args.by))


def cmd_reject(args):
    _engine(args).reject(args.step, args.by, args.reason)
    print(f"Rejected {args.step}; issue escalated to the ops team.")


def cmd_ingest(args):
    doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
    _print_events(_engine(args).ingest(doc))


def cmd_report(args):
    print(weekly_summary(_engine(args)))


def cmd_audit(args):
    e = _engine(args)
    if args.verify:
        ok, bad = e.store.verify_audit()
        print("Audit chain intact." if ok else f"Audit chain BROKEN at entry {bad}.")
        sys.exit(0 if ok else 1)
    for row in e.store.audit_rows():
        print(f"{row['seq']:>4} {row['ts']} {row['actor']:<22} {row['event']:<20} {row['ref']}")


def cmd_new_customer(args):
    dest = onboarding.create_customer(args.id, args.name)
    print(f"Created {dest} (git-ignored). Fill in company.json, workers.json and documents.json, then run:")
    print(f"  python -m opsengine check --customer {dest}")


def cmd_check(args):
    problems = onboarding.check_customer(args.customer)
    if not problems:
        print("Ready: no missing information found.")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1 if problems else 0)


def cmd_read_photo(args):
    r = _engine(args).ingest_photo(args.file, args.holder, context=args.context, expected_type=args.type,
                                   received_via=args.via)
    if r["status"] == "ingested":
        tag = " [mock AI]" if r["source"] == "mock" else ""
        print(f"Read {r['document']} with {r['confidence']:.0%} confidence; ingested.{tag}")
        _print_events(r["events"])
    else:
        print(f"Sent to human review as {r['review']} ({r['confidence']:.0%} confidence):")
        for reason in r["reasons"]:
            print(f"  - {reason}")


def cmd_reviews(args):
    q = _engine(args).review_queue()
    if not q:
        print("Nothing waiting for review.")
    for r in q:
        ex = r["extraction"]
        print(f"  {r['id']}  {r['holder']:<8} {ex.get('document_type') or '?':<20} {r['confidence']:.0%}  {r['file']}")
        print(f"           read: {json.dumps(ex.get('values') or {})}")
        for reason in r["reasons"]:
            print(f"           - {reason}")


def cmd_review_accept(args):
    corrections = {}
    for item in args.set or []:
        k, _, v = item.partition("=")
        corrections[k] = int(v) if k == "limit_eur" else v
    _print_events(_engine(args).accept_review(args.review, args.by, doc_type=args.type, corrections=corrections))


def cmd_review_reject(args):
    _engine(args).reject_review(args.review, args.by, args.reason)
    print(f"Rejected {args.review}.")


def cmd_daily(args):
    today = date.fromisoformat(args.today) if args.today else None
    folders = [Path(c) for c in args.customer] if args.customer else scheduler.customer_folders(args.root)
    if not folders:
        print(f"No customers found under {args.root}.")
        return
    failed = 0
    for r in scheduler.daily_run(folders, state_dir=args.state, today=today):
        if r["status"] != "ok":
            failed += 1
            print(f"  {r['customer']:<24} FAILED: {r['error']}")
            continue
        print(f"  {r['customer']:<24} opened {len(r['opened'])}, closed {len(r['closed'])}, actions {r['actions']}, "
              f"chased {len(r['chased'])}, escalated {len(r['escalated'])}, approvals waiting "
              f"{r['approvals_waiting']}, reviews waiting {r['reviews_waiting']}")
    sys.exit(1 if failed else 0)


# ---------------- corrective actions, appointments, providers (spec 4-8) ----------------
def cmd_raise_action(args):
    e = _engine(args)
    issue_id = e.raise_corrective_action(args.title, holder=args.holder, owner=args.owner, due=args.due,
                                         severity=args.severity, context=args.site, detail=args.detail or "",
                                         evidence_required=args.evidence, raised_by=args.by)
    print(f"Raised {issue_id}.")
    _print_events(e._advance_issue(issue_id))


def cmd_actions(args):
    e = _engine(args)
    rows = e.corrective_actions(None if args.all else "open")
    if not rows:
        print("No corrective actions.")
    for a in rows:
        late = " OVERDUE" if a["status"] != "resolved" and a.get("due") and a["due"] < e.today.isoformat() else ""
        print(f"  {a['id']}  {a['severity']:<8} due {a.get('due')}{late}  owner {e.customer.holder_name(a.get('owner')):<22} "
              f"{a['status']:<11} {a.get('title')}")


def cmd_appointments(args):
    e = _engine(args)
    rows = e.store.appointments()
    if not rows:
        print("No appointments.")
    for a in rows:
        print(f"  {a['id']}  {a['date']}  {a['status']:<10} {a['kind']:<10} {a['provider_name']:<40} "
              f"{e.customer.holder_name(a['holder'])} ({a['issue_id']})")


def cmd_appointment(args):
    _print_events(_engine(args).update_appointment(args.id, args.status, args.by, date=args.date, notes=args.notes or ""))
    print(f"{args.id} marked {args.status}.")


def cmd_providers(args):
    from .actions import provider_problems
    e = _engine(args)
    stats = e.store.provider_stats()
    for p in e.kb.providers:
        if args.category and p["category"] != args.category:
            continue
        probs = provider_problems(p, e.today)
        st = stats.get(p["id"])
        record = f"{st['completed']}/{st['booked']} completed, {st['no_show']} no-show" if st else "no bookings yet"
        print(f"  {p['id']:<7} {p['category']:<30} {p['name']:<44} EUR {p['price_eur']:<5} "
              f"{'OK' if not probs else 'NOT USABLE: ' + ', '.join(probs)} | {', '.join(p.get('service_areas', []))} | {record}")


def cmd_subcontractors(args):
    from .report import compliance_register
    e = _engine(args)
    reg = [r for r in compliance_register(e) if r["holder_kind"] == "subcontractor"]
    for sid, sub in e.customer.subcontractors.items():
        rows = [r for r in reg if r["holder"] == sid]
        bad = [r for r in rows if r["status"] != "ok"]
        verdict = "MEETS REQUIREMENTS" if not bad else ("DOES NOT MEET REQUIREMENTS" if any(
            r["blocks_site_access"] and r["status"] in ("missing", "expired") for r in bad) else "attention needed")
        print(f"  {sid}  {sub['name']}  ({', '.join(sub.get('trades', []))}; sites {', '.join(sub.get('sites', []))}): {verdict}")
        for r in rows:
            print(f"        {r['status']:<11} {r['name']:<45} {r['document'] or '-':<18} {r['expires']}")


def cmd_assets(args):
    from .report import compliance_register
    e = _engine(args)
    reg = [r for r in compliance_register(e) if r["holder_kind"] == "asset"]
    out = {o["holder"]: o for o in e.out_of_use()}
    for aid, a in e.customer.assets.items():
        flag = f"  ** OUT OF USE: {out[aid]['reason']} ({out[aid]['issue']}) **" if aid in out else ""
        print(f"  {aid}  {a['name']} ({a.get('type')}, sites {', '.join(a.get('sites', []))}){flag}")
        for r in [r for r in reg if r["holder"] == aid]:
            print(f"        {r['status']:<11} {r['name']:<50} last record {r['document'] or '-':<22} due {r['expires']}")


def cmd_documents(args):
    e = _engine(args)
    for g in e.document_history(holder=args.holder):
        print(f"  {e.customer.holder_name(g['holder'])} - {g['type']}{' (' + g['context'] + ')' if g['context'] else ''}")
        for d in g["versions"]:
            mark = "current " if d["id"] == g["current"] else "previous"
            ev = f" evidence {d['evidence']['stored_as'][:12]}..." if d.get("evidence") else ""
            print(f"        {mark} {d['id']:<28} {d.get('expires') or d.get('issued') or ''}{ev}")


def cmd_history(args):
    h = _engine(args).issue_history(args.issue)
    i = h["issue"]
    print(f"{i['id']} [{i['status']}] {i['detail']}")
    for s in h["steps"]:
        print(f"  step {s['id']:<10} {s['action']:<18} {s['state']:<17} {('approved by ' + s['approved_by']) if s['approved_by'] else ''}")
    for c in h["comms"]:
        print(f"  {c['direction']:<3} {c['channel']:<9} {c['to_name']:<34} {c['status']:<30} {c['subject']}")
    for a in h["appointments"]:
        print(f"  appointment {a['id']} {a['date']} {a['status']} with {a['provider_name']}")
    print(f"  proof: {h['proof']['id'] if h['proof'] else '-'}; audit entries: {len(h['audit'])}")


def cmd_comms(args):
    for c in _engine(args).store.comms(args.issue):
        print(f"  {c['ts'][:16]} {c['direction']:<3} {c['channel']:<9} {c['to_name']:<36} {c['status']:<34} {c['subject']}")


def cmd_register(args):
    from .report import compliance_register
    rows = compliance_register(_engine(args))
    if not args.all:
        rows = [r for r in rows if r["status"] != "ok"]
    for r in rows:
        print(f"  {r['status']:<11} {r['holder_name'][:34]:<34} {r['name'][:48]:<48} {r['document'] or '-':<22} {r['expires']}")
    print(f"{len(rows)} row(s){'' if args.all else ' needing attention (use --all for everything)'}.")


def cmd_risks(args):
    from .report import risk_overview
    e = _engine(args)
    r = risk_overview(e)
    print(f"Could stop work on site: {len(r['blocking'])}")
    for x in r["blocking"]:
        print(f"  {x['status']:<8} {x['holder_name'][:34]:<34} {x['name']}")
    print(f"Lapsing soon: {len(r['lapsing_soon'])}")
    for x in r["lapsing_soon"]:
        print(f"  {x['expires']} {x['holder_name'][:34]:<34} {x['name']}")
    print("By site: " + ", ".join(f"{e.customer.sites.get(k, {}).get('name', k)}: {v['blocking']} blocking, {v['other']} other"
                                  for k, v in r["by_site"].items()))
    print(f"Overdue corrective actions: {len(r['overdue_actions'])}")


def cmd_export(args):
    from .report import export_records
    print(f"Records exported to {export_records(_engine(args), args.out)}")


def cmd_insights(args):
    from .insights import insights
    today = date.fromisoformat(args.today) if args.today else None
    folders = [Path(c) for c in args.customer] if args.customer else scheduler.customer_folders(args.root)
    engines = [Engine(f, state_dir=args.state, today=today) for f in folders]
    r = insights(engines)
    print(f"Issues analysed: {r['issues_total']} across {len(engines)} customer(s)")
    for title, key in (("Most common problems", "most_common_problems"), ("Frequently missing", "frequently_missing"),
                       ("Recurring", "recurring"), ("Hotspots", "hotspots")):
        print(f"{title}: " + ("; ".join(f"{n} ({c})" for n, c in r[key]) or "none"))
    print("Median hours to close: " + ("; ".join(f"{k}: {v}" for k, v in r["hours_to_close"].items()) or "none closed yet"))
    print("Recommendations:")
    for rec in r["recommendations"]:
        print(f"  - {rec}")


def cmd_web(args):
    from .web import serve
    serve(host=args.host, port=args.port, fresh=args.reset, demo=args.demo, state_dir=args.state)


def _accounts(args):
    from .auth import Accounts
    folder = Path(args.state) if args.state else ROOT / "state" / "web"
    folder.mkdir(parents=True, exist_ok=True)
    return Accounts(folder / "accounts.db")


def _ask_password(args):
    import getpass
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("New password (12+ characters): ")
    if first != getpass.getpass("Repeat it: "):
        raise SystemExit("Passwords don't match.")
    return first


def cmd_user(args):
    try:
        _user(args)
    except ValueError as exc:
        raise SystemExit(f"Not done: {exc}")


def _user(args):
    from .auth import STAFF
    a = _accounts(args)
    by = "cli"
    if args.action == "list":
        for u in a.users():
            flags = [x for x, on in (("disabled", u["disabled"]), ("demo", u["demo"]),
                                     ("code set", u["mfa_secret"]), ("locked", u["locked_until"])) if on]
            print(f"  {u['email']:<40} {u['role']:<9} {u['customer_id'] or '-':<28} {u['name']}  {', '.join(flags)}")
        return
    if not args.email:
        raise SystemExit("--email is required")
    if args.action == "add":
        if not args.name or not args.role:
            raise SystemExit("--name and --role are required")
        uid = a.add_user(args.email, args.name, args.role, _ask_password(args), customer_id=args.customer, by=by)
        print(f"Created {args.email} ({args.role}).")
        if args.role in STAFF:
            print("They'll set up a sign-in code from an authenticator app the first time they sign in.")
        return
    u = a.user(email=args.email)
    if not u:
        raise SystemExit("No user with that email.")
    if args.action in ("disable", "enable"):
        a.set_disabled(u["id"], args.action == "disable", by=by)
    elif args.action == "reset-password":
        a.set_password(u["id"], _ask_password(args), by=by)
    elif args.action == "reset-code":
        a.reset_mfa(u["id"], by=by)
    print(f"Done: {args.action} {args.email}.")


def cmd_demo(args):
    print(f"AI mode: {ai_mode()}")
    state = Path(args.state or ROOT / "state" / "demo")
    if state.exists():
        shutil.rmtree(state)
    today = date.fromisoformat(args.today or "2026-11-11")
    e = Engine(SAMPLE, state_dir=state, today=today)
    incoming = SAMPLE / "incoming"

    def h(t):
        print(f"\n=== {t} ===")

    h("1. DETECT: scan Liffey Interiors against the rules library")
    r = e.scan()
    for i in e.store.issues("open"):
        print(f"  {i['id']}  {i['severity']:<8} {e.customer.holder_name(i['holder']):<34} {i['detail']}")

    h("2. PLAN + ACT: the engine works every issue as far as it can alone")
    _print_events(e.advance())

    h("3. APPROVALS: what needs a human")
    for q in e.approval_queue():
        print(f"  {q['step']:<12} [{q['role']}] {q['summary']}")

    h("4. Customer approves every training booking; safety reviewer releases drafted documents")
    for q in e.approval_queue():
        who = "Ciara Byrne (customer)" if q["role"] == "customer" else "Safety reviewer (chartered)"
        _print_events(e.approve(q["step"], who))

    h("5. PROOF ARRIVES: Joao sends a photo of his new Safe Pass")
    _print_events(e.ingest(json.loads((incoming / "new_safe_pass_w02.json").read_text())))

    h("6. BAD PROOF: Andrei sends an unreadable card - the engine rejects it and asks again")
    _print_events(e.ingest(json.loads((incoming / "wrong_card_w03.json").read_text())))

    h("7. PHOTO: Lucas sends a photo of his Safe Pass - Claude vision reads it")
    r = e.ingest_photo(incoming / "photo_safe_pass_w06.png", "w06", expected_type="safe_pass")
    if r["status"] == "ingested":
        tag = " [mock AI: recorded read of the sample photo]" if r["source"] == "mock" else ""
        print(f"  Read with {r['confidence']:.0%} confidence and ingested{tag}")
        _print_events(r["events"])
    else:
        print(f"  Not confident enough ({r['confidence']:.0%}) - sent to human review as {r['review']}:")
        for reason in r["reasons"]:
            print(f"    - {reason}")
        print("  Ops reviewer checks the photo and types in the card details:")
        _print_events(e.accept_review(r["review"], "Ops reviewer", doc_type="safe_pass",
                                      corrections={"number": "SP-300006", "expires": "2030-11-20"}))

    h("8. DAILY RUN, 2 days later: reminders for anything still waiting")
    for days in (2, 5):
        if days == 5:
            h("9. DAILY RUN, 5 days later: stalled items escalated to the ops team")
        r = scheduler.run_customer(SAMPLE, state_dir=state, today=today + timedelta(days=days))
        print(f"  chased {len(r['chased'])}: {', '.join(r['chased']) or '-'}")
        print(f"  escalated {len(r['escalated'])}: {', '.join(r['escalated']) or '-'}")

    h("10. RECORD: weekly summary sent to the owner")
    e = Engine(SAMPLE, state_dir=state, today=today + timedelta(days=5))
    print(weekly_summary(e))

    ok, _ = e.store.verify_audit()
    h(f"11. AUDIT: {len(e.store.audit_rows())} entries, hash chain {'intact' if ok else 'BROKEN'}")
    print(f"  Outbox (messages, bookings, drafts): {e.outbox}")
    print(f"  Metrics: {json.dumps(metrics(e))}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="opsengine", description="Compliance operations engine v0")
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.add_argument("--state", help="state folder (default ./state)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, customer=True):
        sp = sub.add_parser(name)
        if customer:
            sp.add_argument("--customer", default=str(SAMPLE), help="customer data folder")
        sp.set_defaults(fn=fn)
        return sp

    add("scan", cmd_scan)
    add("advance", cmd_advance)
    add("queue", cmd_queue)
    sp = add("approve", cmd_approve); sp.add_argument("step", nargs="+"); sp.add_argument("--by", required=True)
    sp = add("reject", cmd_reject); sp.add_argument("step"); sp.add_argument("--by", required=True); sp.add_argument("--reason", required=True)
    sp = add("ingest", cmd_ingest); sp.add_argument("file")
    add("report", cmd_report)
    sp = add("audit", cmd_audit); sp.add_argument("--verify", action="store_true")
    add("demo", cmd_demo, customer=False)
    sp = add("new-customer", cmd_new_customer, customer=False); sp.add_argument("id"); sp.add_argument("--name", required=True)
    add("check", cmd_check)
    sp = add("read-photo", cmd_read_photo); sp.add_argument("file"); sp.add_argument("--holder", required=True)
    sp.add_argument("--type", help="what the sender says it is, e.g. safe_pass"); sp.add_argument("--context")
    sp.add_argument("--via", default="whatsapp")
    add("reviews", cmd_reviews)
    sp = add("review-accept", cmd_review_accept); sp.add_argument("review"); sp.add_argument("--by", required=True)
    sp.add_argument("--type"); sp.add_argument("--set", action="append", metavar="FIELD=VALUE")
    sp = add("review-reject", cmd_review_reject); sp.add_argument("review"); sp.add_argument("--by", required=True)
    sp.add_argument("--reason", required=True)
    sp = add("raise-action", cmd_raise_action); sp.add_argument("title"); sp.add_argument("--owner", default="company")
    sp.add_argument("--holder", default="company"); sp.add_argument("--due"); sp.add_argument("--site")
    sp.add_argument("--severity", default="medium", choices=["critical", "high", "medium"]); sp.add_argument("--detail")
    sp.add_argument("--evidence", default="photo or document showing the work is done"); sp.add_argument("--by", required=True)
    sp = add("actions", cmd_actions); sp.add_argument("--all", action="store_true")
    add("appointments", cmd_appointments)
    sp = add("appointment", cmd_appointment); sp.add_argument("id")
    sp.add_argument("--status", required=True, choices=["confirmed", "attended", "completed", "no_show", "cancelled"])
    sp.add_argument("--by", required=True); sp.add_argument("--date"); sp.add_argument("--notes")
    sp = add("providers", cmd_providers); sp.add_argument("--category")
    add("subcontractors", cmd_subcontractors)
    add("assets", cmd_assets)
    sp = add("documents", cmd_documents); sp.add_argument("--holder")
    sp = add("history", cmd_history); sp.add_argument("issue")
    sp = add("comms", cmd_comms); sp.add_argument("--issue")
    sp = add("register", cmd_register); sp.add_argument("--all", action="store_true")
    add("risks", cmd_risks)
    sp = add("export", cmd_export); sp.add_argument("--out", required=True)
    sp = add("insights", cmd_insights, customer=False)
    sp.add_argument("--root", default=str(scheduler.CUSTOMERS_ROOT)); sp.add_argument("--customer", action="append")
    sp = add("web", cmd_web, customer=False); sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000); sp.add_argument("--reset", action="store_true")
    sp.add_argument("--demo", action="store_true", help="SAMPLE companies with demo accounts")
    sp = add("user", cmd_user, customer=False)
    sp.add_argument("action", choices=["add", "list", "disable", "enable", "reset-password", "reset-code"])
    sp.add_argument("--email"); sp.add_argument("--name"); sp.add_argument("--role", choices=["customer", "ops", "reviewer", "admin"])
    sp.add_argument("--customer", help="customer id, for customer users"); sp.add_argument("--password-stdin", action="store_true")
    sp = add("daily", cmd_daily, customer=False)
    sp.add_argument("--root", default=str(scheduler.CUSTOMERS_ROOT), help="folder holding customer folders")
    sp.add_argument("--customer", action="append", help="run only this customer folder (repeatable)")

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
