> **DRAFT – AWAITING APPROVAL FROM AN IRISH DATA PROTECTION SOLICITOR.**
> Not legal advice. Not approved for use with real customers or workers. Prepared by Claude (an AI).
> The under-250-employees exemption does not apply: this processing is regular, not occasional.

# Records of processing activities (Article 30)

Organisation: [OPSENGINE LEGAL ENTITY], [address]. Contact: [name, email]. DPO: see `dpo-assessment.md`.
Kept up to date by: [name]. Reviewed: [DATE], then at least yearly and whenever processing changes.

## Part A – OpsEngine as processor (Article 30(2))

| Item | Entry |
| --- | --- |
| Controllers | Each customer (list kept in the customer register: name, contact, DPA date, sub-processor list version) |
| Categories of processing | Compliance tracking for construction work: storing and checking worker, subcontractor and company records; reading card photos; sending reminders and requests; arranging approved bookings; keeping records and reports |
| Transfers outside the EEA | Anthropic PBC (US) and possibly Meta, under [DPF / SCCs]. See `docs/sub-processors.json` |
| Security measures | DPA Annex 2 |

## Part B – OpsEngine as controller (Article 30(1))

| Purpose | Data subjects | Data | Recipients | Transfers | Retention | Security |
| --- | --- | --- | --- | --- | --- | --- |
| Portal access and security | Portal users | Name, email, role, password hash, code secret, sign-in history with IP (tokens) | Hosting provider | [None expected] | Account life; IPs 12 months | DPA Annex 2 |
| Handling unmatched inbound messages | Anyone who contacts the service | Message and attachments | Hosting and email providers | [None expected] | 30 days after review | DPA Annex 2 |
| Customer relationship and billing | Customer contacts | Name, email, phone, billing records | Accountant, hosting | [None expected] | [SOLICITOR] / 6 years for billing | DPA Annex 2 |

## Part C – Category detail
Kept in `docs/data-inventory.json` (who, what, where, why, lawful basis, retention), which this record
points to rather than repeats. [SOLICITOR: confirm that referencing it is acceptable.]
