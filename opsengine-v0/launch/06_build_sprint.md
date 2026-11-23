# Build sprint: pilot-ready this week

Goal: by the end of the week OpsEngine can run one real pilot customer safely. Claude builds;
the founder only plugs in accounts (the "Needs you" column, about 10 minutes each).

| Day | Build (Claude) | Needs you | Status |
| --- | --- | --- | --- |
| 1 | **Logins and per-customer isolation.** Accounts (customer / ops / safety reviewer), hashed passwords, lockout after 5 wrong tries, sessions, cross-site form protection, customers only ever see their own company and files, demo controls switched off, `web --live` uses the real date and never wipes data. Commands: `add-user`, `users`, `remove-user`. 11 new tests. | Nothing | Done |
| 2 | **Real email.** Send through a transactional email provider, delivery status, retries; replies and photo attachments come back into the right customer and issue. | Pick a domain + create an email-sending account | Done (code) |
| 3 | **Approve by link.** Signed, single-use, expiring approve/decline links in emails, recorded with who approved. | Nothing | Done |
| 4 | **Hosting.** EU server setup, HTTPS, nightly backups, the daily run on a timer, alert if it fails. | Create the hosting account | Done (code) |
| 5 | **GDPR basics + pilot onboarding.** Data export and deletion per customer, privacy notice draft, a guided onboarding checklist for the first customer. End-to-end rehearsal with a test customer. | Nothing | Done in tests; live rehearsal once the server exists |

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

## What was built (all five days, done ahead of time)
- **Email out** (`connectors.py`): SMTP with SSL/STARTTLS, 3 tries for temporary failures, refused
  addresses fail at once, a reply address per customer and issue (`inbox+<customer>.<issue>@...`).
- **Email in** (`inbound.py`, `python -m opsengine inbox`): replies and photo attachments are filed
  against the right customer and issue; photos go through the photo reader (a person checks
  anything uncertain); unknown senders are kept for the ops team, never guessed.
- **Approve by link** (`links.py`, `/a/<token>`, `python -m opsengine approval-emails`): signed,
  single-use, 7-day links; opening a link never approves, the button press does; recorded as
  "<name> (via email link)".
- **Hosting** (`../deploy/`): systemd services and timers (portal, daily run 07:00, inbox every 5
  min, backup 02:30), Caddy for HTTPS, encrypted nightly backups kept 30 days, failure alert emails,
  `/health` check, step-by-step `deploy/SETUP.md`.
- **GDPR + onboarding**: `erase-customer` (with export first), `08_gdpr_pack.md` drafts (privacy
  notice, processing terms, retention), `07_pilot_onboarding.md` checklist.
- Tests: 24 new (logins 11, email + links 13); all 165 pass.
- **Not yet tried for real:** sending through a real email provider, a real mailbox, and the
  server files on a real server. Those need the accounts below; we test each one as it's set up.

## The only things left are accounts (founder, ~10 minutes each)
1. Business name -> domain.
2. Email provider account (SMTP) + a mailbox for replies (IMAP).
3. EU server (deploy/SETUP.md steps 1-2).
