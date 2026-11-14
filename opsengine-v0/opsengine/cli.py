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
    _print_events(_engine(args).approve(args.step, args.by))


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
    sp = add("approve", cmd_approve); sp.add_argument("step"); sp.add_argument("--by", required=True)
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
    sp = add("daily", cmd_daily, customer=False)
    sp.add_argument("--root", default=str(scheduler.CUSTOMERS_ROOT), help="folder holding customer folders")
    sp.add_argument("--customer", action="append", help="run only this customer folder (repeatable)")

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
