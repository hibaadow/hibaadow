# OpsEngine implementation audit

**Date:** 14 November 2026 · **Code audited:** `opsengine-v0` at branch `claude/new-session-n3aize` (PR #7 head)
**Scope:** every capability in `PRODUCT.md`, plus security, data protection, failure handling and audit integrity.

## How this was audited

- Read the code paths behind each capability rather than relying on the demo or the sample run.
- Ran the full suite: 108 tests, all passing, all offline. The breakdown is `test_capabilities` 35,
  `test_sample_pilot` 16, `test_vision` 15, `test_engine` 12, `test_scheduler` 11, `test_mock_ai` 8,
  `test_web` 6 and `test_onboarding` 5.
- Probed failure handling with bad, missing and duplicate input against a fresh engine.
- Traced every write to the state database to see whether it reaches the audit log.
- Nothing has run against a real external service. There is no Anthropic API key, no email
  server, no WhatsApp account, no real provider, no real customer and no hosting. **All end-to-end
  evidence comes from fictional SAMPLE data and recorded or faked responses.**

## Classification key

| Code | Meaning |
| --- | --- |
| **1** | Fully implemented and tested (logic exists and automated tests exercise it) |
| **2** | Implemented but not fully tested (logic exists; important paths have no test or have a known defect) |
| **3** | Partially implemented (some of the capability exists; a material part does not) |
| **4** | Simulated using sample data (the mechanism runs, but only against fictional data or stand-ins) |
| **5** | Not implemented |
| **6** | Blocked by an external integration or API (code may exist but cannot work without an outside service) |

"Tested" means automated tests on SAMPLE data. Nothing in this table has been proven with a real
customer, a real document or a real provider.

---

## Verdict

**OpsEngine today is a well-tested compliance rules and workflow engine. It is not yet a
production service.**

- **What is real.** The core loop is genuine and tested: configurable rules, detection, playbooks,
  approval gates, proof re-checking, corrective actions, scheduling, reminders, escalation, the
  register and the audit log. A new requirement or main contractor really is data, not code.
- **What is simulated or blocked.** Everything that touches the outside world: messages are
  written to an outbox and nothing is delivered; providers, prices and credentials are fictional;
  photo reading, translation and AI drafting have never run against the real API; quotes and
  bookings are records and emails nobody receives.
- **What is missing for production.** There is no authentication, no tenant isolation, no
  encryption, no backups, no hosting, no input validation on ingest, and no external verification
  of any document. Probing found data-integrity defects (D1 to D4 below) that can let wrong
  information through or stop a customer's daily run.
- **Correction to earlier claims.** The "Build status" table in `PRODUCT.md` and the shared
  capabilities page describe every section as "Built". That overstates it. The classifications
  below replace them.

---

## Answers to the eight questions

### 1. Does the engine genuinely check documents against configurable requirements?
**Yes, for structured data. No, for the documents themselves.**

- **Configurable rules.** 30 requirements live in `rules/requirements.json`, with per-contractor
  extras and minimums in `rules/main_contractors/*.json`. The checks cover scope, conditions,
  expiry and review cycles, required fields, minimum values, allowed values and content rules.
  Detection is a pure function with tests.
- **What "document" means.** It means a JSON record of fields (number, expiry, insurer, limit,
  signer, activities). The engine checks those fields. It does not open the PDF or photo behind
  the record, except through the photo reader, which has never run against the real API.
- **Defects found:**
  - A malformed date in any stored record crashes every later scan for that customer (D1).
  - A non-numeric value, for example a limit of "6.5m", silently passes a minimum check (D2).
- **Rule content is unverified.** Intervals, limits and legal references were written from general
  knowledge. The six inspection rules are marked [CHECK]. None of the rules has been reviewed by a
  competent safety professional or a solicitor.

### 2. Can AI independently identify problems and execute resolution workflows?
**No. Problems are found by deterministic rules, and workflows are fixed playbooks. AI is used
only for reading photos, translating and drafting, and none of these has run live.**

- **Detection.** Problems are found by rules, not by AI. That is the right choice for compliance,
  because every finding can be explained. But nothing outside the rules is ever noticed. A
  problem with no rule is only caught if a person raises a corrective action.
- **Resolution.** Each problem type has a fixed playbook. The engine executes it on its own up to
  approval gates. It cannot plan a resolution for a situation without a playbook. Those fall to
  `_default`, a generic request to the customer.
- **"Execution".** It means writing a message to the outbox, recording a booking, or updating
  state. Nothing is sent and nothing is booked in the real world.

### 3. Does extraction and verification work with real PDFs and images?
**Unproven. Blocked by the API key.**

- **Images.** `vision.py` sends images to the Messages API and scores the reply. It applies a 90%
  threshold plus type, name and field checks, and sends anything uncertain to human review. The
  tests use recorded replies for fictional images rendered from text.
- **PDFs.** The code maps `.pdf` to a document block, but no test, fixture or live call exercises
  that path.
- **Never tested:** real phone photos (glare, angle, both sides of a card), scanned insurance
  schedules, multi-page certificates, handwriting, and non-English documents.
- **API version.** The request sends `anthropic-version: 2023-06-01` together with the
  server-side `fallbacks` parameter. That combination has not been verified against the live API.
- **Verification means rule compliance, not authenticity.** Nothing checks a Safe Pass number,
  CSCS card, tax clearance, insurance policy or CRO number with the body that issued it. A typed
  or forged record that has the right fields closes the issue (probe P7).

### 4. Do provider discovery, credential checks, quotes and booking work with real providers?
**No. All simulated.**

- **The network.** It is 21 fictional providers in `data/providers.json`. "Vetted" is a true/false
  value set by hand.
- **Credential checks.** They compare expiry dates stored in that file. Nothing is checked with
  insurers, SOLAS, CSCS assessors, Safe Electric or the Central Bank register.
- **Quotes.** Requests are written to the outbox. Replies are not captured, so comparisons use
  the listed prices.
- **Booking.** It creates an appointment record and an outbox email. There is no confirmation,
  calendar, payment or cancellation flow with a provider.

### 5. Can it manage multiple customers, projects, sites, workers and subcontractors securely?
**It can model them. It cannot do it securely.**

- **Separation.** Each customer has its own folder and its own SQLite database, and the daily run
  loops over customers.
- **Projects.** There is no project entity, only sites.
- **Shared people.** Workers and subcontractors belong to one customer. Agency workers, or a
  subcontractor used by several customers, are duplicated.
- **Security.** There is no authentication anywhere.
  - In the web portal, the "role" is a cookie anyone can set, and every customer's data is visible
    to every visitor.
  - Approvals record a name the caller supplies.
  - Data is unencrypted on disk, with no backups, retention or deletion.

### 6. Are all actions recorded in the audit trail?
**Most state changes, yes. Not all. And the trail is tamper-evident only against casual edits.**

- **Covered.** Issue creation, updates and resolution; every executed action, approval, rejection,
  verification, review decision, booking change, reminder and escalation; every document added.
- **Gaps:**
  - The status change from "open" to "in progress" is not audited (`engine.py`, `_advance_issue`).
  - The message log, quotes, appointments and the photo review queue are ordinary tables. They can
    be edited without breaking the chain. Their creation is mostly echoed in audit payloads, but
    later edits to those tables are not.
  - The audit records who acted as a name string, not an authenticated identity.
  - Anyone who can write to the database file can rebuild the whole chain. Nothing anchors it
    externally, for example with a periodic signed checkpoint.

### 7. Do external communications and approvals work?
**Not externally.**

- **Outgoing.** Every message is written to the outbox and logged. SMTP sending exists but has
  only been tested against a fake server. WhatsApp has no connector.
- **Incoming.** There is no inbound email or WhatsApp capture. Documents enter only as JSON
  through the CLI, as a portal upload, or as a simulated arrival.
- **Approvals.** These happen in the CLI or the local portal. There is no customer login,
  approve-by-link or e-signature, and nothing verifies who approved.
- **Translation.** The engine correctly refuses to fake it. Live translation has never run.

### 8. Can it handle failures, incorrect information and uncertain decisions safely?
**Uncertain decisions: mostly yes, by design. Failures and incorrect information: not yet.**

- **Uncertainty is handled well.**
  - Photos below 90% confidence, or with a wrong name, wrong type or missing field, go to a person.
  - Money and commitments need customer approval. Safety documents and high-risk closures need a
    reviewer.
  - A credential that lapses between approval and booking blocks the booking.
  - Content gaps are flagged to a person, never auto-fixed.
- **Failures are not.**
  - There is no input validation on ingest. Bad data crashes the engine (D1, D3) or passes
    silently (D2).
  - There is no per-issue error isolation. One failing action stops `advance()` for that customer.
  - Failed sends are logged but never retried.
  - Concurrent use of the portal is untested, and SQLite locking isn't configured.
  - Clocks are naive (UTC versus Irish time is not handled).

---

## Defects found during this audit

| ID | Severity | What happens | How to reproduce |
| --- | --- | --- | --- |
| D1 | **Critical** | A stored document with a non-ISO date (e.g. `"31/12/2027"`) makes every later `scan()` raise `ValueError`. That customer's daily run fails every day until someone edits the database. | `ingest({"type":"safe_pass","expires":"31/12/2027",...})` then `scan()` |
| D2 | **Critical** | Minimum checks only apply to numbers. A limit stored as text (`"6.5m"`, `"EUR 6,500,000"`) silently passes, and the issue can close as compliant. | Ingest public liability with `limit_eur: "6.5m"`; no finding is raised |
| D3 | High | Ingesting a record without `holder` or `type` raises `KeyError`. Records for unknown holders or unknown types are stored silently. | `ingest({"id":"x","type":"safe_pass"})` |
| D4 | High | Any record with the right fields closes an issue. There is no authenticity check and no plausibility check (e.g. a Safe Pass expiring decades ahead, or a number in the wrong format). | Ingest a made-up Safe Pass for a worker; the issue resolves |
| D5 | Medium | `_advance_issue` has no error isolation. An executor exception (missing template, bad provider data) aborts the whole customer's `advance()`. | Reference a missing template in a playbook |
| D6 | Medium | Portal roles are a client-set cookie. Anyone can act as the customer, ops or the safety reviewer, and see every customer. | Set `role=reviewer` in the browser |
| D7 | Medium | Status change from open to in progress is not audited. The message, quote, appointment and review tables sit outside the hash chain. | Code read: `engine.py` `_advance_issue`; `store.py` side tables |
| D8 | Low | The API version header (`2023-06-01`) with the beta `fallbacks` parameter is unverified. The first live call may be rejected, in which case every photo goes to review. | First real API call |
| D9 | Low | No retry for failed email sends. A `failed:` status is recorded and the step is treated as sent. | `EMAIL_MODE=smtp` with an unreachable server |

---

## Capability-by-capability classification

### 1. Compliance monitoring

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Continuously monitors compliance status | 1 | `daily` scans and advances every customer and chases stalls; tested | Run by itself: nothing schedules it, no hosting | Host it, schedule it, alert on failed runs |
| Tracks legal and regulatory requirements | 3 | 30 configurable rules with legal-basis notes, plus per-contractor rules | Rules unreviewed; no tracking of regulation changes; no versioning (a rule change silently changes past results) | Professional and legal review; rule versioning; change log; regulatory watch process |
| Identifies missing, expired or incomplete documents | 2 | Tested for well-formed records | Malformed data crashes or passes (D1, D2, D3) | Input validation and type coercion at ingest; tests for bad data |
| Monitors employee, subcontractor and site compliance | 1 | Worker, subcontractor, site and asset scopes, tested on SAMPLE data | Projects; people shared across customers | Project entity; shared people records |
| Tracks renewals, inspections and deadlines | 1 | Expiry and review-interval logic, warning windows, inspection intervals | Real inspection intervals are unconfirmed ([CHECK]) | Competent-person sign-off of intervals |
| Flags potential risks | 1 | `risks`: what blocks site access, what lapses soon, by site | Risk beyond document status (e.g. high-risk activities without controls) | Activity-based risk rules once real data exists |
| Identifies gaps needing corrective action | 1 | Findings become issues; inspection defects become corrective actions | Gaps outside the rules | Easy ways for ops and customers to raise actions (exists in portal and CLI) |

### 2. Document management

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Collects and organises documents | 3 | Records via JSON, photo upload in the portal or CLI; files stored by SHA-256 | Inbound email or WhatsApp capture; a subcontractor or worker upload portal | Inbound channels; per-person upload links |
| Reads card and certificate photos | 6 | Claude vision code with confidence scoring and human review; mock mode for samples | Run on real photos (no API key); PDF path untested | API key; evaluation set of real anonymised documents; measured accuracy before auto-accept |
| Reviews Safety Statements and risk assessments | 3 | Signer must be owner or director; RAMS activities must mention site tasks (keyword match) and brief every site worker | Read the document; judge whether hazards and controls are adequate | PDF text extraction plus AI review flagged to a competent person; never auto-approval |
| Checks RAMS for missing information | 3 | Required fields, task coverage and briefing coverage from structured fields | Anything inside the RAMS file | As above |
| Identifies inconsistencies | 3 | Insured name, signer and photo holder name; holder-name mismatch on photos | Cross-document checks (policy numbers, dates, addresses), duplicates, implausible values | Plausibility rules (D4); cross-document checks |
| Prepares documents for human review | 3 (AI 6) | Template DRAFT Safety Statement and RAMS, released only by the safety reviewer | AI drafting (never run live); useful content | API key; drafting evaluated by a safety professional |
| Requests missing documents | 1 (delivery 6) | Correct request to the correct person, with a translation flag | Deliver it | Email and WhatsApp connectors |
| Tracks versions and expiry dates | 1 | Every version kept, current one identified; tested | Note why a version was superseded | Fine for v1 |
| Maintains organised digital records | 3 | SQLite per customer plus evidence folder; export tested | Backups, encryption, access control, retention | Managed database or object storage with encryption, backups and retention policy |

### 3. Automated problem resolution

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Creates an action per issue | 1 | Every finding becomes an issue with playbook steps | — | — |
| Determines what needs to happen | 1 | A fixed playbook per requirement and category; deterministic | Plan for situations without a playbook | Ops review of `_default` cases; grow playbooks from real cases |
| Completes admin tasks where permitted | 4 | Writes messages, comparisons, booking requests and drafts to the outbox | Anything outside the system | Connectors (email, WhatsApp, booking confirmation) |
| Requests missing information | 1 (delivery 6) | As above | Deliver it | Connectors |
| Contacts people and follows up | 1 (delivery 6) | Reminders after 2 days, escalation after 5, once per waiting period; tested | Deliver; notice replies | Connectors and inbound capture |
| Coordinates corrective actions | 1 | Owner, deadline, evidence, chase, escalate, reviewer sign-off | Deliver | Connectors |
| Arranges services and appointments | 4 | Appointment records with fictional providers after approval | Real booking, confirmation or payment | Real providers and a confirmation flow |
| Tracks issues until resolved and verified | 1 | Re-runs the rule on new proof; rejects and asks again | Verify authenticity (D4) | External verification where available; plausibility checks |
| Escalates when judgement or approval is needed | 1 | Escalations recorded and written to an internal file | Notify a real person | Ops notifications (email or Slack) and an ops rota |

### 4. Training and certification coordination

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Tracks training requirements | 1 | Safe Pass, CSCS categories, manual handling, inductions by task and contractor | Other training (working at height, abrasive wheels, first aid…) | Add as data from real contractor forms |
| Identifies expired or missing certifications | 2 | Tested | Malformed dates (D1); authenticity (D4) | Validation; verification |
| Finds suitable providers | 4 | Ranking by language, urgency, price and record; excludes lapsed or out-of-area providers | Real providers | Recruit and vet real providers |
| Requests quotes and compares | 3 / 4 | Quote requests to up to 3 providers, written to the outbox; compares listed prices | Receive or parse replies | Inbound email; a quote reply form for providers |
| Arranges sessions with approval | 4 | Customer approval gate, then a booking record | Confirmed seat on a real course | Provider confirmation flow; calendar |
| Tracks attendance and completion evidence | 3 | Ops marks attended or no-show (no-show rebooks); the new card closes the issue | Attendance from the provider; certificate import | Provider confirmation; certificate ingest |
| Updates training records | 1 | New card replaces old as current; versions kept | — | — |
| Monitors upcoming renewals | 1 | Warning windows per rule | — | — |

### 5. Contractor and subcontractor management

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Collects subcontractor documentation | 3 | Requests written to the outbox for the subcontractor contact | Receive their uploads | Subcontractor upload link and inbound email |
| Checks insurance certificates and expiry | 1 (reading 6) | Limits, expiry and insured name on structured records | Read the certificate; confirm with the insurer | Photo or PDF reading live; insurer or broker confirmation where offered |
| Tracks qualifications and training | 3 | One aggregate operatives register document using the earliest expiry | Individual operatives' cards | Operatives as people under each subcontractor |
| Identifies missing or expired documents | 1 | Tested | — | — |
| Requests outstanding information | 1 (delivery 6) | Customer flagged; subcontractor asked | Deliver | Connectors |
| Maintains subcontractor profiles | 1 | Register per subcontractor, CLI and portal | Shared profiles across customers | Shared subcontractor directory with consent |
| Monitors documentation across projects | 3 | Across sites of one customer | Projects; across customers | Project entity |
| Flags subcontractors not meeting requirements | 1 | "Does not meet requirements" when a blocking item is missing or expired; customer told | — | — |

### 6. Inspection and maintenance coordination

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Tracks required inspections and servicing | 1 (content unverified) | Six inspection and service rules on an asset register | Correct legal intervals and forms (marked [CHECK]) | Competent-person review; statutory form references |
| Identifies overdue inspections | 1 | Tested | — | — |
| Finds qualified inspectors | 4 | Fictional inspectors, filtered by credentials and area | Real inspectors | Real network |
| Requests and compares quotes | 3 / 4 | As in training | Replies | As in training |
| Books approved providers | 4 | Record after approval | Real booking | Confirmation flow |
| Coordinates appointments | 3 | "On or after" date from lead time; follow-up message after the date | Agreed date and time; reschedule; site access arrangements | Two-way scheduling with providers and site contacts |
| Follows up on incomplete work | 1 | Follow-up after the date; no-show returns to approval; tested | Deliver | Connectors |
| Collects inspection reports and certificates | 3 | Report as a structured record, including defects | Read a report PDF | PDF reading; evaluation on real reports |
| Tracks corrective actions from inspections | 1 | Defects and failed results become actions; tested | — | — |

### 7. Provider network management

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Maintains a network of vetted providers | 4 | 21 fictional providers in a JSON file; "vetted" is a hand-set flag | A vetting process | Vetting procedure, agreements, onboarding |
| Stores qualifications, insurance and service areas | 1 (data 4) | Data model and checks exist | Real data | Real providers |
| Matches businesses with providers | 1 | Category, area, credentials, language, urgency, price, record; tested | — | — |
| Checks credentials and their validity | 3 | Expiry dates in our own file | Check with issuing bodies or insurers | Document collection from providers, with expiry chasing; registry lookups where public |
| Requests availability and pricing | 3 | Outbound only | Replies | Inbound capture or provider reply form |
| Coordinates bookings and delivery | 4 | Records only | Real coordination | Confirmation flow |
| Tracks performance and completed work | 2 | Completed, no-show and cancelled counts from appointment status; reliability used in ranking | Quality and timeliness of reports; customer feedback | Feedback capture; time-to-report |
| Maintains provider records and documentation | 3 | JSON edited by hand | Provider documents and their expiry | Treat providers as holders with their own rules |

### 8. Corrective action management

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Records safety and compliance issues | 1 | CLI, portal and inspection defects | Photos attached at raising time; mobile capture on site | Photo attachment at raise |
| Assigns responsibility | 1 | Owner: worker, subcontractor, owner or ops | — | — |
| Establishes deadlines | 1 | Default by severity, or set by a person | — | — |
| Sends follow-up requests | 1 (delivery 6) | Assignment message, evidence request, 2/5-day chase, overdue escalation | Deliver | Connectors |
| Tracks progress | 1 | Steps and status visible in CLI and portal | — | — |
| Collects evidence of completed work | 2 | Evidence record or note matched to the action or defect | Assess whether the evidence shows the fix | Photo evidence with human review for high-risk items |
| Escalates unresolved issues | 1 | Overdue and stalled escalation; tested | Notify a person | Ops notifications |
| Keeps a record of how each issue was addressed | 1 | Issue history plus audit | — | — |
| Verifies evidence before closing | 2 | Evidence must exist and have content; critical and high need safety reviewer sign-off; tested | Judge evidence quality for medium items | Spot-check sampling by ops |

### 9. Communication and administration

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Sends emails and notifications | 6 | Outbox; SMTP code tested only against a fake server | Deliver email; WhatsApp, SMS or push | Transactional email provider with domain authentication (SPF/DKIM); WhatsApp Business account and templates |
| Requests documents and information | 1 (delivery 6) | Correct content and recipient; translation flagged | Deliver | As above |
| Follows up with employees, subcontractors and providers | 1 (delivery 6) | As above | Deliver | As above |
| Prepares reports and summaries | 1 | Weekly summary, register, export | Deliver on a schedule | Scheduled delivery |
| Schedules appointments | 3 / 4 | Date estimated from provider lead time | Agreed slots | Scheduling flow |
| Maintains communication histories | 2 | Every outbox message and ingested document logged | Replies; delivery receipts; tamper protection (D7) | Inbound capture; delivery webhooks; chain the comms log |
| Requests customer approval first | 1 | Gates in playbooks; tested, including role checks in the portal | Reach the customer outside the portal or CLI | Approve-by-link (signed, expiring) or customer login |
| Records approvals and decisions | 1 (identity 5) | Audited with name, time and role | Prove who approved | Authenticated approvers |
| Automates repetitive admin | 1 | Internal workflow | External delivery | Connectors |

### 10. Reporting and audit trails

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Maintains a central compliance record | 1 | `register`; tested | — | — |
| Records every issue | 1 | All findings and corrective actions | — | — |
| Tracks actions by AI and humans | 2 | Engine and human actors in the audit; a few gaps (D7) | Authenticated identity | Close the gaps; authentication |
| Stores supporting evidence | 3 | Local files named by SHA-256 when a file exists | Backup; documents typed as JSON have no file | Object storage with encryption and backups; require a file for proof where possible |
| Records approvals and decisions | 1 | Audited | Identity (see 9) | Authentication |
| Produces compliance reports | 1 | Weekly summary, register, risks, export | Contractor-format packs | Main contractor pack export |
| Overview of outstanding and resolved issues | 1 | CLI and portal | — | — |
| History of changes | 2 | Append-only, hash-chained audit log | Resist a full chain rebuild by someone with database access | Periodic signed checkpoints stored separately; database write controls |
| Records accessible for audits | 1 | `export` with CSVs, documents, evidence and a chain check; tested | Controlled access for third parties | Access-controlled sharing |

### 11. Continuous improvement

| Capability | Class | What it does today | What it can't do | Needed for production |
| --- | --- | --- | --- | --- |
| Identifies recurring problems | 2 | Counts reopened issue keys; no test exercises a real recurrence | — | Test with history; real data |
| Highlights patterns across projects and sites | 1 | Hotspots by site and customer | Projects | Project entity |
| Identifies frequently missing documents | 1 | Tested | — | — |
| Tracks provider performance | 2 | From appointment outcomes | Quality | Feedback capture |
| Measures resolution speed | 2 | Median hours to close | Meaningful numbers: the demo and test clocks are compressed | Real usage data |
| Identifies prevention opportunities | 3 | Simple rules (warn earlier, ask at onboarding, root cause) | Deeper analysis | Grows with real data |
| Uses historical data to improve workflows | 3 | Recommendations for a person; by design no self-modification | — | Process for reviewing and adopting recommendations |

### Cross-cutting

| Capability | Class | Notes |
| --- | --- | --- |
| Web portal (customer, ops, reviewer) | 2 | Real engine behind it; 6 tests; no authentication (D6); local only |
| Shareable clickable preview | 4 | Snapshot of engine output; buttons simulated in the browser |
| Multi-customer support | 3 | Folder and database per customer; no tenancy, projects or shared people |
| Security (authentication, authorisation, encryption) | 5 | None |
| Data protection (GDPR) | 3 | Real data kept out of git; SAMPLE separation enforced. No retention, deletion, subject access, data processing agreements or encryption |
| Translation | 6 | Correctly flags; live translation never run |
| Mock AI mode | 1 | Tested; cannot fake reads of real photos or translations |
| Customer onboarding checks | 1 | `new-customer` and `check`; tested |

---

## Important capabilities missing from the specification

1. **Identity and access.** Customer, worker, subcontractor, provider, ops and reviewer accounts;
   multi-factor authentication for ops and reviewers; per-customer tenancy.
2. **Data protection and GDPR.**
   - Lawful basis and privacy notices for workers.
   - Data processing agreements with customers and with providers (including Anthropic and any
     email or WhatsApp provider).
   - Retention schedules, deletion, subject access requests, a breach procedure, and data
     residency.
   - Special-category data such as occupational health information needs extra safeguards.
3. **Document authenticity and verification.** Checks with issuing bodies or insurers where
   possible, plausibility rules, and fraud signals.
4. **Inbound channels.** Email and WhatsApp capture with attachment handling, matched to the right
   customer, person and issue.
5. **Approval channel with identity.** Signed approve and decline links and e-signature for
   documents that need a signature.
6. **Rule governance.** Versioned rules, effective dates, professional sign-off per version, and
   the rule version applied to each finding.
7. **Operations tooling.** An ops rota, SLAs and workload queues; alerting when the daily run
   fails; monitoring.
8. **Reliability.** Hosting, backups, disaster recovery, retry queues, idempotent sends, error
   isolation per issue and per customer, and Irish-time scheduling.
9. **Projects and people over time.** Projects as well as sites; people who move between
   customers or sites; leavers; agency workers.
10. **Main contractor submission.** Export packs in each contractor's format, and portal
    submission where contractors use supplier portals.
11. **Commercial layer.** Customer contracts, pricing, billing; provider payment or invoicing
    terms; who pays for bookings.
12. **Liability and professional cover.** OpsEngine's own professional indemnity insurance; clear
    terms that it coordinates and does not certify; escalation paths to qualified partners.
13. **Accessibility and languages.** An accessible worker-facing interface; verified translations
    for safety content, with native-speaker review as already required.
14. **Rules depth.** RCT, SEO pay and pension, working at height, silica, abrasive wheels, first
    aid, and others named in the roadmap. These come from real contractor forms.

---

## Outstanding dependencies

| Dependency | Unblocks | Owner | Status |
| --- | --- | --- | --- |
| Anthropic API key (or Bedrock or Vertex access) | Photo and PDF reading, translation, drafting | Founder | Blocked: identity verification needs a second ID; support contact suggested |
| Real anonymised documents (photos, scans, PDFs) | Measured extraction accuracy before auto-accept | Founder and pilot customer | Not started |
| Competent safety professional | Rule content, inspection intervals, safety reviewer role | Founder | Not started |
| Solicitor | Legal basis wording, customer terms, liability, GDPR documents | Founder | Not started |
| Pilot customer and their main contractors' forms | Real rules and workflows | Founder | Not started |
| Real providers (training, inspection, consultancy) | Discovery, quotes, booking | Founder | Not started |
| Transactional email account and domain | Sending email | Founder | Not started |
| Meta WhatsApp Business account and approved templates | WhatsApp messages | Founder | Not started (business verification needed) |
| Hosting (EU region), managed database and object storage | Running as a service | Founder and engineering | Not started |
| Data processing agreements (customers, Anthropic, email and WhatsApp providers) | Lawful processing of worker data | Founder and solicitor | Not started |
| Professional indemnity insurance for OpsEngine | Operating as a service | Founder | Not started |

---

## Prioritised roadmap to production

Each phase has exit criteria. Do not start a later phase's external work until the earlier
phase's criteria are met.

### Phase 0: Make the engine safe with bad data (no new features; days)
1. **Validate at ingest.** Required keys, a known type, a known holder, dates parsed to ISO, and
   numbers parsed from text such as "EUR 6,500,000" or "6.5m". Reject or route to human review;
   never store unparseable values (D1, D2, D3).
2. **Make detection defensive.** An unparseable stored value becomes a finding ("cannot read
   expiry"), not a crash (D1).
3. **Plausibility checks.** Expiry windows per card type and number formats. Implausible values go
   to review (D4).
4. **Isolate errors per issue in `advance()`.** A failing action blocks and escalates that issue
   only (D5).
5. **Audit the remaining status change, and chain or append-only the side tables** (D7).
6. **Add tests for every probe in this audit.**

*Exit:* all probes in this document produce findings or review items, never crashes or silent
passes.

### Phase 1: Prove the AI on real documents (blocked on the API key)
1. Get API access, through the Anthropic Console, Bedrock or Vertex.
2. Verify the API version and the fallbacks call (D8).
3. Build an evaluation set of at least 100 real, anonymised cards and certificates, photos and
   PDFs, with correct answers. Measure accuracy and confidence calibration.
4. Set the auto-accept threshold from the measurements. Until it is measured, keep human review
   for everything.
5. Measure translation and drafting with native speakers and the safety professional.

*Exit:* measured accuracy per document type, and a documented threshold.

### Phase 2: Production foundations (before any real customer data)
1. **Authentication and tenancy:** customer, ops and reviewer logins; MFA for staff; per-customer
   isolation in the portal and API (D6).
2. **Hosting** in an EU region: managed Postgres or SQLite with backups, encrypted object storage
   for evidence, scheduled `daily` run, alerting on failures.
3. **Audit hardening:** authenticated actors, signed checkpoints stored separately.
4. **Rule versioning,** with professional sign-off recorded per version.
5. **GDPR pack:** privacy notice, data processing agreements, retention and deletion jobs,
   subject access export (reuse `export`).

*Exit:* a security review passed; GDPR documents signed off by the solicitor.

### Phase 3: Real communications and approvals
1. **Transactional email:** domain authentication, delivery webhooks, retries (D9).
2. **Inbound email** with attachments, routed to the right customer and issue.
3. **Approve-by-link:** signed, expiring and single-use, recorded with identity.
4. **WhatsApp Business:** templates, opt-in, inbound photos into the photo reader.

*Exit:* a message round trip and an approval round trip work end to end with a test customer.

### Phase 4: Pilot with one real customer (limited scope)
1. Load real rules from the customer's main contractor forms, reviewed by the safety professional.
2. Recruit and vet 3 to 5 real providers per category the pilot needs. Collect their insurance
   and qualification documents, and track them as records with expiry.
3. Run with human review of every outbound message for the first weeks. Then relax by category
   as accuracy is shown.
4. Measure human minutes per customer, false positives and missed items.

*Exit:* 8 weeks with no missed blocking item, and measured human minutes per customer.

### Phase 5: Scale
Projects and shared people, main contractor pack export, provider confirmations and quote replies,
external verification where registers allow it, deeper rules (RCT, SEO, working at height, silica),
and an ops console with SLAs.

---

*This audit replaces the "Build status" table in `PRODUCT.md`. The capabilities page and the
clickable preview published earlier describe the target product; anyone reading them should be
pointed to this audit for what works today.*
