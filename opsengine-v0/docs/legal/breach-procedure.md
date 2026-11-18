> **DRAFT – AWAITING APPROVAL FROM AN IRISH DATA PROTECTION SOLICITOR.**
> Not legal advice. Not approved for use with real customers or workers. Prepared by Claude (an AI).

# Personal data breach procedure

**Breach lead:** [NAME, phone]. **Deputy:** [NAME, phone]. Anyone who suspects a breach tells the breach
lead at once, any time of day.

## 1. Detect
Signs include: a failed audit-chain or checkpoint check (`nightly` alert), a backup that fails
verification, unexpected sign-ins or lockouts in the account log, a message sent to the wrong person, a
lost device, a sub-processor's breach notice, or a report from a customer or worker.

## 2. Contain (first hour)
Disable affected accounts; rotate keys (`OPSENGINE_CHECKPOINT_KEY`, webhook secrets, API tokens); stop
sending (`EMAIL_MODE=outbox`, `WHATSAPP_MODE=queue`); preserve logs and the audit chain; do not delete
evidence.

## 3. Assess (within 24 hours)
What happened, which customers and people, which data, how many, likely consequences, whether the data
was encrypted or tokenised, whether it is still exposed.

## 4. Notify
- **Customer data (OpsEngine is processor):** tell each affected customer without undue delay and within
  [24] hours of becoming aware (DPA clause 8). The customer decides whether to notify the DPC (within 72
  hours unless unlikely to risk people's rights) and the people affected (if high risk). Help them.
- **OpsEngine's own data (controller):** we decide. Notify the DPC within 72 hours unless the breach is
  unlikely to result in a risk to people's rights; tell the people affected if the risk is high.
- **Sub-processor breaches:** pass on to affected customers as above.

## 5. Record
Every breach goes in the register, whether reported or not (Article 33(5)).

## 6. Review
Within two weeks: what went wrong, what changes, who does what by when.

---

## Breach register

| Ref | Found (date, time) | What happened | Customers / people affected | Data | Risk assessment | Customer told (when) | DPC told (when, or why not) | People told (when, or why not) | Actions | Closed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [BR-0001] | | | | | | | | | | |
