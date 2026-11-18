> **DRAFT – AWAITING APPROVAL FROM AN IRISH DATA PROTECTION SOLICITOR.**
> Not legal advice. Not approved for use with real customers or workers. Prepared by Claude (an AI)
> from the GDPR first-pass review of 16 Nov 2026, which was itself not written by a solicitor.

# OpsEngine legal document drafts

These are first drafts for a solicitor to review, correct and approve. Until a solicitor approves them:

- do not send them to customers or workers, or publish them;
- automatic deletion stays off (`rules/retention.json`, `solicitor_confirmed: false`);
- nothing in the product may describe them as approved.

Text in `[SQUARE BRACKETS]` is a gap to fill. `[SOLICITOR]` marks a legal decision for the solicitor.

| File | What it is | Who it is for |
| --- | --- | --- |
| `data-processing-agreement.md` | Art 28 agreement between OpsEngine (processor) and each customer (controller) | Customers |
| `worker-privacy-notice-template.md` | Art 13/14 notice the customer adopts and gives to their workers | Customers' workers |
| `opsengine-privacy-notice.md` | Our own notice where OpsEngine is controller | Portal users, website visitors, anyone who contacts us |
| `whatsapp-opt-in-wording.md` | What workers agree to when they say yes to WhatsApp messages | Workers |
| `records-of-processing.md` | Art 30(1) (controller) and Art 30(2) (processor) records | Internal |
| `model-dpia.md` | Model data protection impact assessment customers adopt | Customers |
| `legitimate-interests-assessments.md` | One assessment per legitimate-interests purpose | Internal and customers |
| `breach-procedure.md` | Personal data breach procedure and breach register | Internal |
| `dpo-assessment.md` | Whether a data protection officer is required | Internal |
| `sub-processor-change-notice.md` | Notice to customers before a new sub-processor is used | Customers |

Sources inside the repository: `docs/data-inventory.json` (what we hold and why), `docs/sub-processors.json`
(outside services), `rules/retention.json` (proposed periods), `AUDIT.md` (what is built and what is not).
