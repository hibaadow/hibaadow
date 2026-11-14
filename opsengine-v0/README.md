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
6. **Read a photo:** a card photo is read by Claude, or sent to human review if it can't be read confidently.
7. **Daily run:** two days later reminders go out; five days later stalled items are escalated.
8. **Record:** weekly owner summary, engine metrics and a tamper-evident audit trail.

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

## SAMPLE pilot customer

Until a real pilot is signed, `data/sample/bremore_groundworks/` is a realistic fictional one:
a 16-person Dublin groundworks firm with two sites, one for **Glenmara Construction (SAMPLE)**.
Glenmara's sample prequalification form is in `rules/main_contractors/forms/` and its rules in
`rules/main_contractors/glenmara_construction_sample.json`. Everything is marked SAMPLE.

```bash
python -m opsengine --today 2026-11-11 daily --customer data/sample/bremore_groundworks
python -m opsengine queue --customer data/sample/bremore_groundworks
```

## Everything it can do (commands)

| Command | What it does |
| --- | --- |
| `daily` | Scan and work every customer; chase stalled steps (2 days), escalate (5 days), chase overdue corrective actions, ask providers what happened after a booked date |
| `register` / `risks` | Central compliance record; what could stop work, what lapses soon, by site |
| `subcontractors` / `assets` | Your subcontractors and your plant/equipment, with what each is missing |
| `providers` | The provider network with credential status and track record |
| `queue`, `approve`, `reject` | Approvals: bookings, insurance changes, safety documents, high-risk closures |
| `raise-action`, `actions` | Corrective actions with an owner, deadline and evidence required |
| `appointments`, `appointment` | Training and inspection bookings; mark attended, completed, no-show (rebooks) |
| `read-photo`, `reviews`, `review-accept` | Read card/certificate photos; low-confidence reads go to a person |
| `ingest` | Add a document or evidence that arrived |
| `documents`, `history`, `comms` | Document versions, one issue's full story, communication history |
| `report`, `export`, `insights` | Weekly summary, full record export for audits, patterns and recommendations |

## Add a real customer

```bash
python -m opsengine new-customer acme_drylining --name "Acme Drylining Ltd"
# fill in data/customers/acme_drylining/{company,workers,documents}.json
python -m opsengine check --customer data/customers/acme_drylining   # lists anything missing
```

Real customer folders are git-ignored: they never go into the repository.

## Read card and certificate photos

```bash
python -m opsengine read-photo photo.jpg --holder w02 --type safe_pass --customer data/customers/acme_drylining
python -m opsengine reviews --customer ...                     # reads that need a human
python -m opsengine review-accept REV-0001 --by "Name" --set number=SP-123456 --customer ...
```

Claude reads Safe Pass and CSCS cards and insurance certificates (images or PDF). A read is
accepted automatically only at 90% confidence or more, with the right document type, the right
name and every required field. Anything else waits for a person. Without an API key every photo
goes to a person. Model: `OPSENGINE_VISION_MODEL` (default `claude-opus-5-5`).

## Daily run

```bash
python -m opsengine daily            # every customer in data/customers/
```

Scans and advances every customer, sends a reminder to whoever a step is waiting on after
2 days (including approvers - a reminder never approves anything), and escalates to the ops
team after 5 days. Every action goes into that customer's audit trail. Schedule it with cron:
`5 7 * * * cd /path/to/opsengine-v0 && python -m opsengine daily`.

## Settings and the Claude API key

Settings live in a `.env` file in this folder (git-ignored). Start from the example:

```bash
cp .env.example .env
```

**Where the real key goes:** when you have a key from https://platform.claude.com/settings/keys,
put it on the `ANTHROPIC_API_KEY=` line of `.env` and set `USE_MOCK_AI=false`:

```
ANTHROPIC_API_KEY=sk-ant-...
USE_MOCK_AI=false
```

In a Claude Code cloud session, add the same two values as environment variables in the
environment settings instead (they override `.env`), then start a new session.
Never commit `.env` or paste the key into chat.

| Mode | Photos | Translations | Drafts |
| --- | --- | --- | --- |
| `USE_MOCK_AI=true` (default in `.env.example`) | Sample photos get recorded reads; any other photo goes to human review | Flagged `[TRANSLATION NEEDED]` | Template DRAFT |
| No key, mock off | Every photo goes to human review | Flagged | Template DRAFT |
| Key set, mock off | Claude reads them; below 90% goes to human review | Claude translates; native-speaker review flagged | Claude DRAFT for safety reviewer |

Mock mode never calls Claude, even if a key is set, and never fakes a translation or a read of
a real photo. `python -m opsengine demo` prints which mode is active. Models can be changed with
`OPSENGINE_MODEL` (drafting and translation, default `claude-sonnet-5-5`) and
`OPSENGINE_VISION_MODEL` (photos, default `claude-opus-5-5`).

## How it's built

- **Rules library** (`rules/`): what must be true, as data.
- **Playbooks** (`playbooks/`): how each problem gets fixed, step by step, with approval gates.
- **Provider network** (`data/providers.json`): who can do the physical work.
- **Engine** (`opsengine/`): the detect -> plan -> act -> verify -> record loop.

See `CLAUDE.md` for the architecture, the non-negotiable boundaries and the roadmap.

## Important

All rules are a starting point and must be checked by a competent safety professional and a
solicitor before being used with real customers. Sample companies, people and providers are fictional.
