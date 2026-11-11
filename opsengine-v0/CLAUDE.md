# CLAUDE.md - Compliance Operations Engine

Guidance for Claude Code when working in this repository.

## What this is

An AI-first **compliance operations engine** for Irish construction subcontractors.
The engine is the product, not the app. It doesn't just report problems: it finds them,
plans the fix, takes the action, checks the proof, and records everything.

Core loop (see `opsengine/engine.py`):

```
detect -> plan -> act -> verify -> record
```

When the engine finds a problem, it asks "what can I do to resolve this?" and does it,
stopping only at approval gates or while it waits for proof.

## Non-negotiable boundaries

These are product rules, not style preferences. Never weaken them in code.

1. **Money and commitments need customer approval.** Bookings, quotes accepted and insurance
   changes always have `"approval": "customer"` in the playbook.
2. **Safety documents need a competent human.** Anything drafted (Safety Statement, RAMS)
   goes through `"approval": "safety_reviewer"` before release. Drafts are always marked DRAFT.
3. **The engine never takes legal duty-holder roles.** No PSCS/PSDP appointments, no legal
   sign-off, no claims of competence. Those go to qualified partners.
4. **Physical work is done by qualified people.** The engine coordinates inspections, repairs
   and training; it never claims they happened without proof.
5. **No fake translations.** If Claude can't translate, the message is flagged
   `[TRANSLATION NEEDED]`. Translated safety content needs native-speaker review.
6. **Everything is audited.** Every state change calls `store.audit(...)`. The audit log is
   append-only and hash-chained; never update or delete audit rows.
7. **Customer data is personal data (GDPR).** Keep real customer data out of the repo;
   `state/` is git-ignored.

## Layout

| Path | What it is |
| --- | --- |
| `rules/requirements.json` | Rules library: every requirement as a checkable rule |
| `rules/main_contractors/*.json` | Per main contractor extra requirements and stricter minimums |
| `playbooks/playbooks.json` | Steps that resolve each requirement, per issue category (`validity`, `completeness`) |
| `templates/messages.json` | Plain-English message templates (translated at send time) |
| `data/providers.json` | Provider network (sample data, fictional) |
| `data/sample/liffey_interiors/` | Fictional customer: company, workers, documents, incoming proof |
| `opsengine/detect.py` | Pure detection: rules + documents + date -> findings |
| `opsengine/engine.py` | The loop: scan, advance, approve/reject, ingest, verify |
| `opsengine/actions.py` | Action executors; all outgoing work goes to the outbox |
| `opsengine/llm.py` | Optional Claude API calls (stdlib only); falls back safely |
| `opsengine/store.py` | SQLite state + hash-chained audit log |
| `opsengine/report.py` | Weekly customer summary + engine metrics |
| `opsengine/cli.py` | Command line |

## Commands

```bash
python -m opsengine demo                      # full scripted walkthrough
python -m unittest discover -s tests -v       # tests (always offline)
python -m opsengine scan --customer <folder>  # see cli.py for all commands
```

No third-party dependencies. Python 3.11+. Keep it stdlib-only unless there's a strong reason.

## Conventions

- **Detection stays pure.** `detect()` takes data in and returns findings out, with no I/O,
  so it is easy to test. Any new rule logic goes there, with a test.
- **Add knowledge as data before code.** A new requirement is a JSON entry in
  `rules/requirements.json` plus a playbook entry. Only write code when the data model
  can't express it.
- **New action type:** add an executor in `actions.py`, register it in `EXECUTORS`, use it
  in a playbook, and add a test. Executors return a result dict; return
  `{"status": "blocked", ...}` to escalate to the ops team.
- **Issue keys** are `requirement|holder|context|category`. Expired/expiring/missing share
  the `validity` category so a worsening issue updates instead of duplicating.
- **Dates:** the engine takes `today` explicitly. Tests and the demo pin 2026-11-11.
- Tests set `OPSENGINE_OFFLINE=1`. Never make network calls in tests.

## Metrics that matter

`report.metrics()` tracks automation rate (actions without a human), approvals waiting,
issues open/resolved and median hours to close. The business depends on **human minutes
per customer falling**. When adding features, ask whether they remove human work.

## Roadmap (next steps, in order)

1. **Connectors:** real sending (WhatsApp Business API, email) and inbound capture
   (WhatsApp photos, email attachments) feeding `engine.ingest()`.
2. **Document reading:** use Claude vision to extract fields from card photos and certificates
   into document JSON, with a confidence score; low confidence goes to a human.
3. **Rules library depth:** build from real main contractor prequalification forms; add CIRI
   registration, Sectoral Employment Order (SEO) pay/pension evidence, RCT, plant inspections
   (GA2/GA3 style registers), working-at-height and silica controls.
4. **Scheduler:** daily `scan` + `advance` per customer, reminders when waiting steps stall
   (e.g. chase after 2 days, escalate after 5).
5. **Approval channel:** approve/reject from WhatsApp or email with one tap, recorded in the audit log.
6. **Multi-customer ops console** for the internal team (queues across customers).
7. **Main contractor pack export** in each contractor's required format.
