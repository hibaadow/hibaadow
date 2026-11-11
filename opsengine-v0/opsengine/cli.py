"""Command line for running the engine.

    python -m opsengine scan      --customer data/sample/liffey_interiors
    python -m opsengine advance   --customer ...
    python -m opsengine queue     --customer ...
    python -m opsengine approve ISS-0002.3 --by "Ciara Byrne" --customer ...
    python -m opsengine ingest path/to/doc.json --customer ...
    python -m opsengine report    --customer ...
    python -m opsengine audit     --customer ... [--verify]
    python -m opsengine demo      (full scripted walkthrough on the sample firm)
"""
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

from .engine import Engine
from .knowledge import ROOT
from .report import metrics, weekly_summary

SAMPLE = ROOT / "data" / "sample" / "liffey_interiors"


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


def cmd_demo(args):
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

    h("7. RECORD: weekly summary sent to the owner")
    print(weekly_summary(e))

    ok, _ = e.store.verify_audit()
    h(f"8. AUDIT: {len(e.store.audit_rows())} entries, hash chain {'intact' if ok else 'BROKEN'}")
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

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
