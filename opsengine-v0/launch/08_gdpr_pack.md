# Data protection pack (drafts for a solicitor to check)

These are working drafts so the pilot can start on a sound footing. They are not legal advice:
have a solicitor review them before real worker data is loaded. Placeholders are in [brackets].

## 1. Roles
- **The customer (the subcontractor) is the controller** of its workers' data.
- **[Business name] (OpsEngine) is the processor**: it handles the data only to run the
  compliance service the customer asked for.
- **Sub-processors:** the server host ([provider], EU region), the email provider ([provider]),
  and, once enabled, Anthropic for reading card photos (customer told before it's switched on).

## 2. Privacy notice for workers (customer shares this with their team)
> [Company] uses [Business name] to keep your site paperwork up to date: your Safe Pass, CSCS
> and other cards, training and inductions. We hold your name, role, phone number, language,
> and copies of your cards and certificates, so you can work on sites that require them.
> We use them only for this, keep them while you work with [Company] plus [12] months, and keep
> them in the EU. You can ask [Company] for a copy, a correction or deletion at any time.
> Contact: [owner email].

## 3. Data processing terms (for the pilot agreement)
1. We process worker and company data only on the customer's documented instructions, to provide
   the compliance service.
2. Everyone with access is bound by confidentiality. Access is by personal login; customers see
   only their own company.
3. Security: encrypted connections (HTTPS), hashed passwords, nightly encrypted backups, an
   audit trail of every action, data stored in the EU.
4. Sub-processors are listed above; we tell the customer before adding one.
5. We help the customer answer data requests from workers (export: `python -m opsengine export`).
6. We tell the customer without undue delay (and within 48 hours) if we become aware of a breach.
7. At the end of the contract we return the data (export) and then delete it
   (`python -m opsengine erase-customer <id> --yes`), unless the law requires us to keep it.
8. The customer can ask for evidence of these measures once a year.

## 4. Retention
- Active customer: kept while the contract runs.
- After the contract: exported to the customer, then erased within 30 days.
- Backups roll over after 30 days, so erased data leaves the backups within 30 days.
- Erasures are logged without personal data (`state/erasures.log`).

## 5. Before switching on AI photo reading
- Sign Anthropic's data processing terms (commercial terms include a DPA).
- Tell the customer it's being switched on, and add it to the sub-processor list.
