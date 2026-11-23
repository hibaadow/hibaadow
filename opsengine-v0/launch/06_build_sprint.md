# Build sprint: pilot-ready this week

Goal: by the end of the week OpsEngine can run one real pilot customer safely. Claude builds;
the founder only plugs in accounts (the "Needs you" column, about 10 minutes each).

| Day | Build (Claude) | Needs you | Status |
| --- | --- | --- | --- |
| 1 | **Logins and per-customer isolation.** Accounts (customer / ops / safety reviewer), hashed passwords, lockout after 5 wrong tries, sessions, cross-site form protection, customers only ever see their own company and files, demo controls switched off, `web --live` uses the real date and never wipes data. Commands: `add-user`, `users`, `remove-user`. 11 new tests. | Nothing | Done |
| 2 | **Real email.** Send through a transactional email provider, delivery status, retries; replies and photo attachments come back into the right customer and issue. | Pick a domain + create an email-sending account | |
| 3 | **Approve by link.** Signed, single-use, expiring approve/decline links in emails, recorded with who approved. | Nothing | |
| 4 | **Hosting.** EU server setup, HTTPS, nightly backups, the daily run on a timer, alert if it fails. | Create the hosting account | |
| 5 | **GDPR basics + pilot onboarding.** Data export and deletion per customer, privacy notice draft, a guided onboarding checklist for the first customer. End-to-end rehearsal with a test customer. | Nothing | |

## Not this week (outside our control)
- **Reading photos with real AI** needs the Anthropic API key; the earlier ID verification was
  blocked (see `../AUDIT.md`). Until then every photo goes to a person to check, which is the safe
  default anyway.
- **WhatsApp** needs Meta business verification, which can take weeks. Email first; WhatsApp after.
- **The safety reviewer, solicitor and insurance** (see `04_only_you_checklist.md`).

## Logins: how to use them
```bash
python -m opsengine add-user you@example.ie --name "Your Name" --role ops
python -m opsengine add-user owner@firm.ie --name "Owner" --role customer --customer <customer id>
python -m opsengine web --login            # samples, but with accounts
python -m opsengine web --live --secure    # real customers in data/customers/, behind HTTPS
```
