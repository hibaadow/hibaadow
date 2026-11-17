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

(PRODUCT.md calls these IDENTIFY -> DETERMINE -> EXECUTE -> VERIFY -> MAINTAIN.)

When the engine finds a problem, it asks "what can I do to resolve this?" and does it,
stopping only at approval gates or while it waits for proof.

**Full product scope and build status: `PRODUCT.md`.** Build towards it.

## Non-negotiable boundaries

These are product rules, not style preferences. Never weaken them in code.

1. **Money and commitments need customer approval.** Bookings, quotes accepted and insurance
   changes always have `"approval": "customer"` in the playbook. The only shortcut is the customer's
   own standing approval (`Engine.set_standing_approval`, set by a customer user, never by staff): bookings
   with a known price under their limit and monthly cap go ahead, recorded as theirs. Never extend it to
   insurance, signatures or safety sign-off.
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
   `state/` and `data/customers/*` (except `_template/` and its README) are git-ignored.
8. **SAMPLE data stays SAMPLE.** Every fictional customer and main contractor has `"sample": true`
   and SAMPLE in its name. Samples live in `data/sample/` (committed); real customers only in
   `data/customers/` (git-ignored). `check` and `daily` refuse to mix them, and a real
   customer on SAMPLE contractor rules is flagged.
9. **Never guess a document.** A photo read is only accepted on its own at >= 90% confidence
   with the right type, the right name and every required field. Everything else goes to the
   human review queue. Reminders and escalations never approve anything.

## Layout

| Path | What it is |
| --- | --- |
| `rules/requirements.json` | Rules library: every requirement as a checkable rule |
| `rules/main_contractors/*.json` | Per main contractor extra requirements and stricter minimums |
| `playbooks/playbooks.json` | Steps that resolve each requirement, per issue category (`validity`, `completeness`) |
| `templates/messages.json` | Plain-English message templates (translated at send time) |
| `data/providers.json` | Provider network (sample data, fictional) |
| `data/sample/liffey_interiors/` | SAMPLE customer: drylining, 6 workers (the scripted demo) |
| `data/sample/bremore_groundworks/` | SAMPLE pilot customer: groundworks, Dublin, 16 workers, 2 sites, 19 designed gaps |
| `rules/main_contractors/forms/` | SAMPLE prequalification form(s) the contractor rules were built from |
| `data/customers/` | Real customers (git-ignored). `_template/` is the starting point |
| `opsengine/detect.py` | Pure detection: rules + documents + date -> findings |
| `opsengine/engine.py` | The loop: scan, advance, approve/reject, ingest, verify |
| `opsengine/actions.py` | Action executors; all outgoing work goes to the outbox |
| `opsengine/llm.py` | Optional Claude API calls (stdlib only); falls back safely |
| `opsengine/config.py` | Loads `.env` (never overrides real env vars); `USE_MOCK_AI` switch |
| `.env.example` | Settings template: `ANTHROPIC_API_KEY=` placeholder, `USE_MOCK_AI=true` |
| `data/sample/mock_ai/` | Recorded Claude replies for the sample photos, keyed by SHA-256 (mock mode + tests) |
| `opsengine/store.py` | SQLite state + hash-chained audit log |
| `opsengine/report.py` | Weekly customer summary + engine metrics |
| `opsengine/vision.py` | Claude vision: photo/scan -> document JSON + confidence score |
| `opsengine/scheduler.py` | Daily run per customer: scan, advance, chase after 2 days, escalate after 5 |
| `opsengine/onboarding.py` | Create a customer folder from the template; list what is missing |
| `opsengine/connectors.py` | One send attempt: email via SMTP (`EMAIL_MODE=smtp`, Message-ID, issue ref in subject), WhatsApp via `whatsapp.py` |
| `opsengine/delivery.py` | Retries with backoff, delivery reports, WhatsApp consent and 24-hour window; failures escalate |
| `opsengine/whatsapp.py` | Meta Cloud API: send text/template, webhook signature, parse, media download |
| `opsengine/inbound.py` | Inbound email (.eml folder or IMAP) and WhatsApp photos -> photo reader, routed by sender and `[ISS-0007]` |
| `opsengine/approval_links.py` | One-time approval links for customer approvals (money and commitments) |
| `opsengine/console.py` | Cross-customer operations console: every queue across all customers, most urgent first (read-only) |
| `opsengine/insights.py` | Patterns and recommendations across customers (spec 11) |
| `data/sample/*/assets.json` | Plant, equipment and facilities register (inspections, spec 6) |
| `opsengine/web.py` | Portal (stdlib): customer, ops and safety reviewer views on the real engine, behind sign-in |
| `opsengine/auth.py` | Accounts: hashed passwords, sessions, staff sign-in codes, lockout, account audit log |
| `opsengine/validation.py` | Document validation before storage: dates, numbers, plausibility (AUDIT.md Phase 0) |
| `opsengine/rules_versions.py` | Rules library version (hash) and competent-person sign-off (`rules/versions.json`) |
| `opsengine/checkpoints.py` | HMAC-signed, chained checkpoints of every audit log, kept outside the data folder |
| `opsengine/backup.py` | Backups with manifest, verify, restore into an empty folder, prune |
| `opsengine/gdpr.py` | Retention purge (`rules/retention.json`), subject access export, data inventory (`docs/data-inventory.json`) |
| `deploy/` | Dockerfile, docker-compose + Caddy (HTTPS), production settings, systemd nightly timer |
| `AUDIT.md` | Implementation audit: what is real, simulated or blocked; defects; roadmap |
| `opsengine/cli.py` | Command line |
| `tests/fixtures/photos/` | Fictional sample card/certificate images |

## Commands

```bash
python -m opsengine demo                      # full scripted walkthrough
python -m opsengine web --demo                # portal with SAMPLE companies + demo accounts (http://127.0.0.1:8000)
python -m opsengine web                       # portal for real customers; needs users:
python -m opsengine user add --email a@b.ie --name "Name" --role admin|ops|reviewer|customer [--customer <id>]
python -m opsengine user list|disable|enable|reset-password|reset-code --email a@b.ie
python -m unittest discover -s tests -v       # tests (always offline)
python -m opsengine scan --customer <folder>  # see cli.py for all commands
python -m opsengine new-customer <id> --name "..."   # then: check --customer data/customers/<id>
python -m opsengine read-photo <file> --holder w01 --customer <folder>
python -m opsengine daily                     # every customer in data/customers/ (run from cron)
python -m opsengine register|risks|subcontractors|assets|actions|appointments|providers|comms|documents --customer <folder>
python -m opsengine raise-action "title" --owner w01 --due YYYY-MM-DD --severity high --by "Name" --customer <folder>
python -m opsengine appointment APT-0001 --status attended|completed|no_show|cancelled --by "Name" --customer <folder>
python -m opsengine nightly --backup-to DIR --checkpoint-file FILE   # production nightly run
python -m opsengine backup make|verify|restore ; checkpoint write|verify ; rules status|register|sign-off
python -m opsengine gdpr inventory|purge [--apply]|export --customer <folder> --person w01 --out <dir>
python -m opsengine inbound-email --dir FOLDER | --imap ; deliveries [--retry]   # Phase 3 messaging
python -m opsengine history ISS-0001 --customer <folder>     # export --out <dir>, insights --customer <folder>
```

No third-party dependencies. Python 3.11+. Keep it stdlib-only unless there's a strong reason.

## Conventions

- **Detection stays pure.** `detect()` takes data in and returns findings out, with no I/O,
  so it is easy to test. Any new rule logic goes there, with a test.
- **Add knowledge as data before code.** A new requirement is a JSON entry in
  `rules/requirements.json` plus a playbook entry. Only write code when the data model
  can't express it. `applies_if: {"required_by_main_contractor": true}` makes a company,
  site or worker rule apply only where a contractor lists it in `extra_requirements`;
  `field_allowed_values` restricts a field (e.g. scheme: Safe-T-Cert or CIRI).
- **New main contractor:** a `rules/main_contractors/<id>.json` (extra requirements, minimums,
  submission) built from their form, with the form or a summary in `forms/` and a mapping
  of each question to a rule id. `test_sample_pilot.py` checks the library stays consistent.
- **New action type:** add an executor in `actions.py`, register it in `EXECUTORS`, use it
  in a playbook, and add a test. Executors return a result dict; return
  `{"status": "blocked", ...}` to escalate to the ops team.
- **Issue keys** are `requirement|holder|context|category`. Expired/expiring/missing share
  the `validity` category so a worsening issue updates instead of duplicating.
- **Dates:** the engine takes `today` explicitly. Tests and the demo pin 2026-11-11.
- Tests set `OPSENGINE_OFFLINE=1`. Never make network calls in tests. Vision tests pass a fake
  transport (`tests/helpers.py`) that returns recorded replies.
- **Mock mode:** `USE_MOCK_AI=true` means no Claude calls at all, even with a key. It may only
  replay recorded replies for the fictional sample photos; it never fakes a translation, a draft
  or a read of any other photo (boundaries 5 and 9 still hold). Tests force `USE_MOCK_AI=false`
  and turn it on explicitly where needed, so a local `.env` can't change results.
- **Validation at ingest** (`opsengine/validation.py`): every document, including onboarding seeds,
  is validated before it is stored. Dates are normalised to ISO, money and counts to numbers.
  Unknown types or holders, unreadable values and implausible dates (`max_validity_years`) are
  held in the review queue, never stored as proof. Detection treats any bad value already on
  file as a finding, never a crash. See AUDIT.md, Phase 0.
- **Customer-facing wording** lives in `templates/labels.json` (field names, issue titles, statuses,
  delivery states) and `templates/messages.json` (messages). `opsengine/labels.py` formats money
  (€6.5m) and dates (13 Nov 2026). `tests/test_wording.py` fails if any customer page, message,
  approval or report shows an internal key (anything_with_underscores, limit_eur, None, `{...}`)
  or a message repeats a sentence. Internal notes (channel `file`) are never shown to customers.
- **Critical corrective actions** use the `corrective_critical` playbook: `isolate_item` first
  ("do not use X until this is repaired"), then the evidence request; the item shows Out of use on
  the register until the evidence is verified; the safety reviewer still signs off.
- **One fix, one issue:** a field below several contractors' minimums is one finding at the highest
  value, listing every contractor (`required_by`). Distribution goes to all of them.
- **Provider choice:** cheapest valid provider (in the worker's language first) that finishes at
  least 7 days before the deadline (expiry, due date, or now if it stops work); fastest only when
  time is tight. The one-line reason is shown in the comparison and the approval.
- **Approvals** of the same kind are grouped in the portal ("Approve all"), but each is approved and
  audited on its own (`Engine.approve_group`).
- **Sign-in and access** (`auth.py`, AUDIT.md Phase 2): every portal page needs a signed-in user.
  Customer users are tied to one customer and can never see or act on another (checked on every
  GET, POST and file). Staff (ops, reviewer, admin) need a 6-digit authenticator code after their
  password. Every form carries a per-session CSRF token. Approvals and evidence are recorded as
  "Name <email>" of the signed-in person. Account events go to `state/<portal>/accounts.db`'s own
  hash-chained audit log. Demo accounts and the demo clock exist only with `web --demo`, which
  refuses non-SAMPLE customers. Never add a way round sign-in, even for testing: tests use
  `tests/helpers.py` `Client`, which signs in like a browser.
- **Versioned rules:** any change to `rules/requirements.json`, `rules/main_contractors/*.json` or
  `playbooks/playbooks.json` is a new rules version. Register it (`rules register`) and have a competent
  person sign it off (`rules sign-off`) before production uses it (`OPSENGINE_REQUIRE_SIGNED_RULES`).
  Never record a sign-off on someone's behalf; the SAMPLE library stays unsigned.
- **Checkpoints and backups:** `nightly` writes a signed checkpoint and a verified backup. Both live
  outside `state/`. A restore never goes over live data. Any new database with an `audit` table is
  picked up automatically.
- **GDPR** (`docs/data-inventory.json`, first-pass review of 16 Nov 2026, awaiting a solicitor):
  - A new kind of personal data needs an inventory entry with its lawful basis. Never use consent for
    workers (the WhatsApp opt-in is a channel preference, not the lawful basis).
  - The immutable audit log holds only identifiers, dates, numbers, hashes and lowercase machine words
    (`Store._scrub` in `audit()`). People become ⟪P-0007⟫ tokens (people table); every other string (notes,
    reasons, subjects, file names, card or policy numbers, nicknames, phone numbers) becomes a ⟪T-00001⟫ token
    whose text and SHA-256 live in `audit_text`. `audit_rows()` puts both back for display (`raw=True` for the
    stored form). `store.erase_text` / `store.forget` erase without breaking the chain; the hash stays as
    evidence and `verify_audit_text` checks the kept text. Never write personal data into `event` names.
  - The customer (controller) sets retention: `company.json` "retention" overrides `rules/retention.json`.
    Purges audit counts, never content, and only run for real once `solicitor_confirmed` is true.
  - Real customers need `data_protection.dpa_signed_on` and the current sub-processor list version
    (`docs/sub-processors.json`) before the daily run touches their data. Adding a sub-processor means
    bumping the list version and giving customers notice and a chance to object.
  - Rules can mark data minimisation: `no_personal_data` (accident history: never names anyone, it could be
    health data) and `share_as: confirmation` (main contractors get a confirmation, not the document).
  - Leavers (`left_on` in workers.json) are never chased; their WhatsApp preferences go on leaving, photos
    after `leaver_photos_months`, the named record after `leaver_records_years`.
  - Never add face matching to card photos (it would make them biometric data).
- **Messages and approvals (Phase 3):** every outgoing message goes through `delivery.dispatch`, which
  never treats a failure as sent: temporary failures are retried, permanent ones (and bounces, opt-outs,
  no WhatsApp opt-in) escalate the issue. Only customer approvals may be given by link
  (`approval_links.py`): secret, single-use, 3-day expiry, opening it changes nothing, recorded as
  "Name <email> (email link)". Safety reviewer and ops sign-off stay in the portal with sign-in and a code.
  Links are only issued when email really goes out, and never appear in saved outbox copies (staff can
  read those). Inbound files are never trusted for the channel they came by: unknown senders are kept
  aside, unverified email senders always go to review, and everything still goes through the photo reader.
  Webhooks (`/hooks/email`, `/hooks/whatsapp`) need a valid signature.
- **Customer trust pages:** `data/service.json` holds what customers are told about setup, commission and
  the safety reviewer (SAMPLE until named). Provider prices and our fee are always shown apart
  (`labels.fee_line`). The "How it works" tab answers who is responsible, cost, setup and data.
- **Pricing** (`data/pricing.json`, `opsengine/pricing.py`): plans Starter €199, Growth €399, Business €699,
  Scale €999 a month (1–10, 11–30, 31–75, 76–150 workers), Enterprise custom; onboarding fee equals one
  month; all excluding VAT. Each customer's plan is `company.json` "plan" (`id`, `extra_worker_blocks`,
  `extra_site_eur`). `pricing.fit_problems` tells our team (ops Insights) when a customer outgrows their
  plan or uses features from a higher one. Revenue figures are staff-only. Extra sites default to €40.
- **Subscription limits** (`opsengine/limits.py`): workers, sites and routine safety reviews a month per plan
  (Starter 10/1/5, Growth 30/3/15, Business 75/10/40, Scale 150/25/100, Enterprise custom). Notices at 80%
  and 100% (once a month each). Limits must never stop monitoring, hide an issue, silence a safety alert or
  approve anything: workers and sites over the limit stay fully monitored; a routine review over the
  allowance waits in the reviewer queue (`LimitReached`) until an admin adds capacity, unless it is urgent:
  anything missing or expired that could stop work, critical/high issues, or a review someone marks urgent
  (`limits.mark_urgent`) is never held (overage recorded for agreement). Held reviews are announced at once
  to the customer, ops and reviewer, and escalate after 2 days (`limits.hold_notices`). One amended
  resubmission (`Engine.resubmit_draft`) is included in a draft's original review. Ordinary RAMS and
  Safety Statement reviews are never specialist work. Admins change limits at `/admin/plans` (audited).
- **Release restrictions:** not production-ready. Don't deploy to live customers, enable deletion, claim
  the photo reader is validated, claim the rules are approved, claim safety reviews run before
  `service.json` has an appointed reviewer, or send real messages before email/WhatsApp are tested.
- **Holders** are `company`, worker ids, subcontractor ids (`company.json` "subcontractors") and asset
  ids (`assets.json`). Rule scopes: company, site, worker, worker_site, subcontractor, asset, manual.
- **Corrective actions** (`requirement: corrective_action`, scope manual) are raised by people or from
  inspection defects, never closed by a rescan, closed only with evidence naming the action
  (`action: ISS-...`) or defect (`defect: <doc id>#<n>`); critical/high need safety reviewer sign-off.
- **Providers** are only recommended when vetted, in date (insurance and qualifications) and covering
  the work's area (`sites[].area`). Booking creates an appointment; outcomes feed provider reliability.
- **Waiting clocks:** steps record `waiting_since` / `awaiting_since` (the engine's `today`) in
  their result; the scheduler uses them and stores `chased_on` / `escalated_on` so each
  reminder or escalation happens once per waiting period.

## Metrics that matter

`report.metrics()` tracks automation rate (actions without a human), approvals waiting,
issues open/resolved and median hours to close. The business depends on **human minutes
per customer falling**. When adding features, ask whether they remove human work.

## Roadmap (next steps, in order)

1. **Connectors (built, Phase 3; waiting on accounts):** email sending with retries and delivery reports,
   inbound email and WhatsApp photos into the photo reader. Needs a mail provider and a Meta account to go live.
2. **Document reading (v0 done: `vision.py`):** use Claude vision to extract fields from card photos and certificates
   into document JSON, with a confidence score; low confidence goes to a human.
3. **Rules library depth (started: SAMPLE Glenmara form adds PI, Safe-T-Cert/CIRI, accident history,
   references, plant CSCS cards):** build from real main contractor prequalification forms; add
   Sectoral Employment Order (SEO) pay/pension evidence, RCT, plant inspections
   (GA2/GA3 style registers), working-at-height and silica controls.
4. **Scheduler (v0 done: `scheduler.py`):** daily `scan` + `advance` per customer, reminders when waiting steps stall
   (e.g. chase after 2 days, escalate after 5).
5. **Approval channel (built for email, Phase 3):** one-tap approve/decline links for customer approvals.
6. **Multi-customer ops console (built: `console.py`, "All customers" tab).**
7. **Main contractor pack export** in each contractor's required format.
