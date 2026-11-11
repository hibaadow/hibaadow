# Compliance Operations Engine - v0

The engine that powers an outsourced compliance operations team for Irish construction
subcontractors. It **finds** compliance problems, **plans** the fix, **takes action**,
**checks the proof** and **records** everything in an audit trail.

> v0 runs on a fictional sample firm. Nothing is actually sent: all outgoing messages,
> bookings and drafts are written to an outbox folder for review.

## Try it (2 minutes)

You need Python 3.11 or newer. No installs.

```bash
python -m opsengine demo
```

The demo runs a sample drylining firm (Liffey Interiors, 6 workers, 2 sites) through the full loop:

1. **Detect:** 10 problems found, e.g. an expired Safe Pass, a missing site induction,
   an expired Safety Statement, insurance below one main contractor's minimum.
2. **Act:** the engine messages workers, compares training providers, drafts documents and
   asks the broker for certificates, all on its own.
3. **Approve:** it stops for human approval where money or safety judgement is involved
   (course bookings, insurance changes, drafted safety documents).
4. **Verify:** a new Safe Pass photo arrives and the engine checks it against the rules,
   closes the issue and sends the update to the main contractor.
5. **Reject bad proof:** an unreadable card is rejected and the worker is asked again.
6. **Record:** weekly owner summary, engine metrics and a tamper-evident audit trail.

Look in `state/demo/liffey_interiors/outbox/` to see every message, booking request,
provider comparison and draft the engine produced.

## Use it step by step

```bash
python -m opsengine --today 2026-11-11 scan
python -m opsengine --today 2026-11-11 advance
python -m opsengine queue
python -m opsengine approve ISS-0005.3 --by "Ciara Byrne"
python -m opsengine ingest data/sample/liffey_interiors/incoming/new_safe_pass_w02.json
python -m opsengine report
python -m opsengine audit --verify
```

Run the tests with `python -m unittest discover -s tests -v`.

## Turn on Claude (optional)

Set `ANTHROPIC_API_KEY` and the engine will use Claude to translate worker messages and draft
documents (model set by `OPSENGINE_MODEL`, default `claude-sonnet-5-5`). Without a key it uses
templates and flags translations as needed. It never pretends.

## How it's built

- **Rules library** (`rules/`): what must be true, as data.
- **Playbooks** (`playbooks/`): how each problem gets fixed, step by step, with approval gates.
- **Provider network** (`data/providers.json`): who can do the physical work.
- **Engine** (`opsengine/`): the detect -> plan -> act -> verify -> record loop.

See `CLAUDE.md` for the architecture, the non-negotiable boundaries and the roadmap.

## Important

All rules are a starting point and must be checked by a competent safety professional and a
solicitor before being used with real customers. Sample companies, people and providers are fictional.
