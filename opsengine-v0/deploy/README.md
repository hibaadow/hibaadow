# Deploying OpsEngine

This folder turns OpsEngine into a running service on one Linux server in an **EU region**.
It is ready to use as soon as you have a hosting account. Nothing here is live yet.

## What you need first

1. A Linux server (2 vCPU, 4 GB RAM is plenty to start) in an EU region, with **encrypted disks**.
   Docker and Docker Compose installed.
2. A domain name pointing at it (e.g. `portal.yourfirm.ie`).
3. A data processing agreement with the hosting provider (see `docs/data-inventory.json`).

Encryption at rest comes from the host: use encrypted volumes (or a managed database) from the
provider. OpsEngine is stdlib-only and does not encrypt files itself.

## Install

```bash
sudo mkdir -p /opt/opsengine && cd /opt/opsengine
git clone <your repo> . && cd opsengine-v0
cp deploy/production.env.example deploy/production.env      # fill it in; never commit it
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # use as OPSENGINE_CHECKPOINT_KEY
# edit deploy/Caddyfile: replace portal.example.ie with your domain
docker compose -f deploy/docker-compose.yml --env-file deploy/production.env up -d --build
```

Create the first admin (prompts for a password), then sign in at https://your-domain:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/production.env run --rm opsengine \
  python -m opsengine user add --email you@yourfirm.ie --name "Your Name" --role admin
```

Add more users from the portal's **Users** page. Staff set up an authenticator code at first sign-in.

## Nightly run

`opsengine nightly` does, in order: refuse unsigned rules (`OPSENGINE_REQUIRE_SIGNED_RULES`), the
daily run for every customer, the retention purge (only applied once `rules/retention.json` says
`"solicitor_confirmed": true`; otherwise a dry run), a signed audit checkpoint and its
verification, and a backup that is verified before old ones are pruned. It exits non-zero if
anything failed and writes `state/nightly-last.json`.

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now opsengine-nightly.timer opsengine-messages.timer
```

Replace the command in `opsengine-alert@.service` with real alerting (email or chat).

## Backups and checkpoints: keep copies somewhere else

The backup and checkpoint volumes are on the same server. Copy them **off the server** every night
(e.g. to an encrypted object-storage bucket in another EU region, with versioning and limited
access). A backup or checkpoint that only lives next to the data it protects doesn't protect much.

Test a restore at least monthly:

```bash
python -m opsengine backup verify /backups/<folder>
python -m opsengine backup restore /backups/<folder> --to /tmp/restore-test
```

## Before real customers

- Rules signed off by a competent person: `python -m opsengine rules sign-off --by "Name" --qualification "..."`.
- Retention periods and the data inventory confirmed by a solicitor (`rules/retention.json`, `docs/data-inventory.json`).
- `OPSENGINE_SECURE_COOKIES=1` and HTTPS only (Caddy does this).
- An admin account with a strong password; demo mode (`--demo`) never used on this server.

## Email and WhatsApp (Phase 3)

`opsengine-messages.timer` runs every 15 minutes: it retries messages that failed to send (after 15
minutes, 1 hour, 4 hours and 12 hours, then escalates the issue) and collects inbound email.

**Sending email**
1. Pick an EU transactional email provider. Set `EMAIL_MODE=smtp` and the `SMTP_*` settings.
2. Authenticate your domain with the provider: SPF, DKIM and a DMARC record. Without these, mail lands in spam.
3. Set `OPSENGINE_PUBLIC_URL`. Customer approvals are then emailed once a day with a one-time link per
   item (expires in 3 days, works once, opening it changes nothing). Safety and ops sign-off stay in the portal.
4. Delivery reports: point the provider's webhook at `https://<portal>/hooks/email`. It expects a JSON
   list of `{"message_id", "event": "delivered|bounced|complained|failed", "detail"}` signed with
   `OPSENGINE_WEBHOOK_SECRET` (HMAC-SHA256 of the body, hex, in `X-OpsEngine-Signature`). Most providers
   use their own format, so a small adapter for the chosen provider is still to be written.

**Receiving email**: route `docs+<customer id>@<your domain>` (or one shared address) to an IMAP mailbox
and set `IMAP_*`, or have the mail server drop `.eml` files in a folder and run
`python -m opsengine inbound-email --dir <folder>`. Only senders on file are accepted; mail without a
passing DMARC (or SPF and DKIM) result always goes to a person.

**WhatsApp**: needs a Meta WhatsApp Business account and an approved message template. Set the
`WHATSAPP_*` settings, `WHATSAPP_MODE=cloud`, and in Meta's settings point the webhook at
`https://<portal>/hooks/whatsapp` with your `WHATSAPP_VERIFY_TOKEN`. Record each worker's opt-in date as
`"whatsapp_opt_in"` in workers.json; workers without one aren't messaged and the ops team is told.

## Data protection before the first real customer

- Encrypt the backup volume as well as the live disk (the review asks for encrypted backups), and do a
  restore drill; keep the record.
- Sign the data processing agreement with each customer and record `data_protection.dpa_signed_on` and
  `subprocessor_list_version` in their company.json, or the daily run refuses them.
- Set `solicitor_confirmed: true` in rules/retention.json only once a solicitor has confirmed the periods.

## AI on Google Cloud Vertex AI (EU)

1. In Google Cloud, create or pick a project and turn on billing. Enable the **Vertex AI API**.
2. In Vertex AI's Model Garden, open the Claude models you'll use (by default Claude Opus 5.5 for photos and
   Claude Sonnet 5.5 for drafting and translation) and enable them. Check they're offered in the **EU
   multi-region**.
3. Create a service account (e.g. `opsengine-ai`) and give it only the **Vertex AI User** role
   (`roles/aiplatform.user`).
4. Either attach that service account to the machine OpsEngine runs on (Compute Engine or Cloud Run: no key
   file needed), or create a JSON key for it and mount the file into the container (for example at
   `/run/secrets/vertex-service-account.json`). Never commit the key, and keep it readable only by OpsEngine.
5. In `deploy/production.env`: `AI_PROVIDER=vertex`, `VERTEX_PROJECT_ID=<project>`, `VERTEX_REGION=eu`,
   `GOOGLE_APPLICATION_CREDENTIALS=<key path, or empty when attached>`. Models are `OPSENGINE_MODEL` and
   `OPSENGINE_VISION_MODEL`.
6. Run `python -m opsengine ai status`, then `python -m opsengine ai check` (one tiny call, no personal data).
7. Keep `USE_MOCK_AI=true` until the photo reader has been validated on real documents. Whenever the AI is
   unavailable, every photo goes to a person to check, and nothing is faked.
