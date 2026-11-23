# Pilot onboarding checklist (first real customer)

Claude runs this with you, one step at a time. Real customer data never goes into git
(`data/customers/*` and `state/` are ignored).

## Before day one
- [ ] Pilot agreement signed (draft: `08_gdpr_pack.md` section 3 + the pitch's pilot terms).
- [ ] Safety reviewer agreed and has an account (`add-user ... --role reviewer`).
- [ ] Server online and `/health` says ok (`../deploy/SETUP.md`).
- [ ] Email sending + inbox set in `.env` and a test email sent to yourself.

## Collect from the customer (one email; Claude drafts it)
- [ ] Company: name, owner name/email/phone, Safety Statement date, insurance certificates
      (employer's liability, public liability, PI if needed), tax clearance.
- [ ] Sites they work on now and which main contractor runs each.
- [ ] Each main contractor's prequalification form or requirements list.
- [ ] Workers: name, role, phone, language, and photos of their Safe Pass / CSCS cards.
- [ ] Their subcontractors (if any): contact email.
- [ ] Plant and equipment they bring to site, with last inspection dates.

## Load it (Claude does this with you)
- [ ] `python -m opsengine new-customer <id> --name "..."` and fill in the JSON files.
- [ ] Add each main contractor's rules (`rules/main_contractors/`), reviewed by the safety reviewer.
- [ ] `python -m opsengine check --customer data/customers/<id>`: fix anything it lists.
- [ ] Card photos: upload in the portal; every photo is checked by a person at first.
- [ ] First run: `python -m opsengine daily --customer data/customers/<id>` and read the outbox
      before anything is sent (keep `EMAIL_MODE=outbox` for the first week; send by hand).

## First week
- [ ] Send the customer their first compliance check (from the weekly report).
- [ ] Customer account created; walk them through the portal in 10 minutes.
- [ ] Switch `EMAIL_MODE=smtp` only after you've checked a week of outbox messages.
- [ ] Note how many minutes you spent: the business depends on that number falling.
