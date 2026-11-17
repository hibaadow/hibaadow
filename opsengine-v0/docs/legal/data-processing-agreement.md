> **DRAFT – AWAITING APPROVAL FROM AN IRISH DATA PROTECTION SOLICITOR.**
> Not legal advice. Not approved for use with real customers or workers. Prepared by Claude (an AI).

# Data Processing Agreement

**Between** [CUSTOMER LEGAL NAME], [address], CRO [number] (the **Customer**, controller)
**and** [OPSENGINE LEGAL ENTITY], [address], CRO [number] (**OpsEngine**, processor).

This agreement forms part of the OpsEngine subscription agreement dated [DATE] (the **Main Agreement**).
It meets Article 28 of the GDPR (Regulation (EU) 2016/679) and the Data Protection Act 2018.
If the two conflict on data protection, this agreement wins. [SOLICITOR: confirm order of precedence.]

## 1. Subject matter, duration, nature and purpose

| Item | Detail |
| --- | --- |
| Subject matter | Compliance administration for the Customer's construction work |
| Duration | The term of the Main Agreement, then until return or deletion under clause 11 |
| Nature | Collecting, storing, checking, organising, sending and deleting records; reading text from card and certificate photos (with AI assistance) |
| Purpose | Tracking that the Customer's workers, subcontractors, plant and company hold the cards, training, insurance and documents their work and main contractors require; arranging renewals the Customer approves; keeping records |
| Data subjects | The Customer's workers (including leavers and any apprentices aged 16 or 17), owners and directors, subcontractors' contacts, and people who send documents to the service |
| Personal data | Names, roles, phone numbers, email addresses, preferred language, trades and sites; card and certificate details and photos of cards; site inductions; messages sent and received; WhatsApp opt-in and opt-out; approvals given; challenges to a status |
| Special category data | None intended. Accident and incident history is held at company level only and must not name individuals. Card photos are not used for face recognition. [SOLICITOR: confirm.] |

## 2. Instructions

2.1 OpsEngine processes the personal data only on the Customer's documented instructions. These are: this
agreement, the Main Agreement, the compliance standard the Customer sets (which requirements apply to whom),
the approvals the Customer gives in the portal or by email link, and the retention periods the Customer
chooses.

2.2 OpsEngine tells the Customer at once if it believes an instruction breaks data protection law.

2.3 OpsEngine does not use the personal data for its own purposes. In particular it does not use it to
develop, train or evaluate its products, and it takes no referral fee or commission from providers.
[SOLICITOR: confirm this wording keeps OpsEngine a processor.]

## 3. Confidentiality

Everyone at OpsEngine who can access the personal data is bound by confidentiality, through their
employment contract or a separate undertaking.

## 4. Security (Article 32)

OpsEngine keeps the measures in Annex 2 in place and reviews them at least yearly.

## 5. Sub-processors

5.1 The Customer gives OpsEngine general written authorisation to use the sub-processors in Annex 3
(list version [N]).

5.2 OpsEngine gives the Customer at least [30] days' written notice before adding or replacing a
sub-processor. The Customer may object on reasonable data protection grounds within that period. If the
parties can't resolve the objection, the Customer may end the affected service without penalty.
[SOLICITOR: confirm.]

5.3 Each sub-processor is bound by data protection terms at least as protective as this agreement.
OpsEngine stays fully liable to the Customer for its sub-processors.

## 6. Transfers outside the EEA

OpsEngine transfers personal data outside the EEA only with a valid transfer mechanism: an adequacy
decision (including the EU-US Data Privacy Framework where the recipient is certified on the day of
transfer), or Standard Contractual Clauses with a transfer impact assessment. Where it relies on the
Data Privacy Framework, Standard Contractual Clauses are kept in place as a fallback. [SOLICITOR: confirm,
given Case C-703/25 P is pending.]

## 7. Data subject rights

OpsEngine helps the Customer answer requests from data subjects (access, rectification, erasure,
restriction, objection). It can export everything held about a person, and forward any request it
receives directly to the Customer within [5] working days without answering it itself.
People can also challenge a compliance status through the portal or WhatsApp; a person reviews every challenge. [Depends on the challenge process, PR #10, being merged.]

## 8. Personal data breaches

OpsEngine tells the Customer without undue delay, and in any case within [24] hours, after becoming aware
of a personal data breach affecting the Customer's data. It gives what it knows at the time (nature,
categories and approximate numbers of people and records, likely consequences, measures taken) and
follows up as more is known. The Customer decides whether to notify the Data Protection Commission and the
people affected. [SOLICITOR: confirm the deadline.]

## 9. DPIAs and consultation

OpsEngine gives the Customer a model data protection impact assessment and the information the Customer
needs to complete its own, and helps with any prior consultation with the Data Protection Commission.

## 10. Audits

OpsEngine makes available the information needed to show it complies with Article 28, including its
security measures, audit-log checks and the results of its security review, and allows audits by the
Customer or an auditor the Customer appoints, on [30] days' notice, no more than once a year unless there
has been a breach. [SOLICITOR: confirm.]

## 11. End of the agreement

At the end of the Main Agreement, the Customer chooses whether OpsEngine returns the personal data (a
complete export) or deletes it. OpsEngine does so within [30] days and confirms in writing, except for
copies it must keep by law, which stay protected by this agreement until deleted. Backups are deleted on
their normal rotation of [14] days.

## 12. Retention during the agreement

OpsEngine applies the retention periods the Customer chooses (Annex 4 gives the proposed defaults).

## 13. Liability

As set out in the Main Agreement. [SOLICITOR.]

---

### Annex 1 – Processing details
See clause 1 and `docs/data-inventory.json`.

### Annex 2 – Security measures (summary of what is built)
- Every portal page requires sign-in; staff also use an authenticator code; customers can turn codes on.
- Passwords stored as salted PBKDF2-SHA256 hashes; sessions as hashed random tokens; accounts lock after 5 failed attempts.
- Each customer can see only their own data, checked on every page, action and file.
- Append-only, hash-chained audit log; people appear in it only as tokens kept in a separate, deletable table; daily HMAC-signed checkpoints stored separately.
- Daily backups, checked after they are made; restores only into a new location.
- HTTPS for all web traffic. Encryption of stored data and backups through the hosting provider's encrypted storage. [Confirm once hosting is chosen.]
- Messages from unknown senders are set aside; unverified email senders always go to a person.
- A named, qualified safety reviewer signs off safety documents. [Not yet appointed.]
- [To complete before go-live: security review, restore drill.]

### Annex 3 – Sub-processors (list version [N])
From `docs/sub-processors.json`: hosting provider (EU, to be chosen), email provider (EU, to be chosen),
Anthropic PBC (US; reading photos and translating), Meta Platforms Ireland (WhatsApp Business Cloud API).
[Complete names, entities, locations and transfer mechanisms once chosen.]

### Annex 4 – Proposed default retention (the Customer may change these)
| Data | Default |
| --- | --- |
| Photos rejected at review | 60 days |
| Leavers' card photos | 12 months after leaving |
| Leavers' named training records | 6 years after leaving, then deleted and the person removed from the audit log |
| Leavers' WhatsApp preferences | On leaving |
| Message files for resolved issues | 6 years |
| Directors' details | Contract + 6 years |
| Subcontractor contacts and documents | Engagement + 6 years |
| Audit log | Contract + 6 years (people as tokens) |
