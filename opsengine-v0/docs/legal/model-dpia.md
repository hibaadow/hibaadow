> **DRAFT – AWAITING APPROVAL FROM AN IRISH DATA PROTECTION SOLICITOR.**
> Not legal advice. Not approved for use with real customers or workers. Prepared by Claude (an AI).
> A model for each customer (the controller) to adopt, adjust and sign. The legal duty to carry out a DPIA
> is the customer's; OpsEngine provides this and helps (Article 28(3)(f)).

# Model data protection impact assessment: site compliance with OpsEngine

Customer: [NAME]. Prepared: [DATE]. Reviewed by: [NAME, ROLE]. Next review: [DATE, at least yearly].

## 1. Why a DPIA is needed
Several high-risk indicators apply: workers are employees and many are migrant workers with language
barriers (people in a weaker position); new technology (AI reading documents); systematic monitoring of
workers' compliance; combining data from different sources (workers, providers, main contractors).

## 2. What the processing is
Tracking that workers hold the cards, training and inductions their work needs; reading card photos;
reminding workers and others; arranging training the customer approves; sharing proof with main
contractors; keeping records. Data and flows: see `docs/data-inventory.json`.

## 3. Necessity and proportionality
- Safe Pass, CSCS and site inductions are required by the Construction Regulations 2013.
- Other processing relies on legitimate interests, each with an assessment (`legitimate-interests-assessments.md`).
- Minimisation: main contractors get a confirmation of employment terms, not the contract; accident history is company-level only; only the text of a card is read.
- Retention: customer-set periods with defaults (DPA Annex 4).
- Transparency: worker notice in each worker's language.
- Rights: export of everything held about a person; challenges reviewed by a person.

## 4. Risks and measures

| Risk to people | Likelihood / severity (before) | Measures | Residual |
| --- | --- | --- | --- |
| Wrong status stops someone working | Medium / High | A person approves anything that stops work; anyone can challenge a status and a person decides within 5 days; every status shows its reason | Low / Medium |
| AI misreads a card | Medium / Medium | Accepted on its own only at 90%+ confidence with the right name, type and fields; everything else to a person. **Not yet validated on real documents** | [Re-assess after validation] |
| Workers don't understand what happens | High / Medium | Notice and messages in their language, checked by native speakers; plain wording | Medium / Low |
| Excessive sharing with main contractors | Medium / Medium | Only what each contractor's rules require; confirmations instead of contracts | Low / Low |
| Unauthorised access | Low / High | Sign-in for every page, codes for staff, per-customer separation, audit log, encryption by host | Low / Medium |
| Data kept too long | Medium / Medium | Retention schedule, staged deletion for leavers, people removed from the audit log | Low / Low |
| Transfer to the US (AI, WhatsApp) | Medium / Medium | DPF or SCCs with transfer assessment | [SOLICITOR] |
| Under-18 workers | Low / Medium | Notice and messages suitable for 16 and 17 year olds | Low / Low |
| Health data in accident records | Low / High | Company-level only; named entries held back | Low / Low |

## 5. EU AI Act
Annex III lists AI used to make decisions about work relationships or to monitor workers as high-risk.
Reading cards to check compliance may be a narrow procedural task outside that list. [SOLICITOR: assess.
Annex III obligations apply from 2 December 2027.]

## 6. Consultation
Workers or their representatives consulted: [how and when]. DPO advice: [if any]. Prior consultation
with the Data Protection Commission needed: [yes/no, with reasons].

## 7. Sign-off
Measures approved by: [NAME]. Residual risks accepted by: [NAME]. Date: [DATE].
