# Putting OpsEngine online (EU server, about 45 minutes)

One small Linux server in an EU data centre runs everything: the portal (behind HTTPS), the
daily run, the inbox check every 5 minutes and a nightly encrypted backup. Any failure emails
you. No third-party Python packages are needed.

**What the founder does:** create the server and point the domain at it (steps 1-2, about 15
minutes). Claude can talk you through the rest, or run it with you.

## 1. Create the server (founder)
- Any EU host is fine (e.g. Hetzner in Germany/Finland, or an EU region at another provider).
- Smallest plan with Ubuntu 24.04 is enough to start. Add your SSH key when asked.
- Note the server's IP address.

## 2. Point a domain at it (founder)
- In your domain's DNS settings add an **A record**: `app` -> the server's IP address.
- Result: `app.yourdomain.ie` reaches the server.

## 3. Install (on the server, as root)
```bash
apt update && apt install -y python3 caddy openssl git
useradd --system --create-home --home-dir /opt/opsengine opsengine
git clone <your repo url> /tmp/repo && cp -r /tmp/repo/opsengine-v0/. /opt/opsengine/
mkdir -p /opt/opsengine/state /opt/opsengine-backups && chown -R opsengine: /opt/opsengine /opt/opsengine-backups
```

## 4. Settings
```bash
cp /opt/opsengine/.env.example /opt/opsengine/.env && chmod 600 /opt/opsengine/.env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"      # paste as OPSENGINE_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"      # paste as BACKUP_PASSPHRASE (store a copy safely!)
nano /opt/opsengine/.env       # also set PUBLIC_URL, EMAIL_*, SMTP_*, IMAP_*, ALERT_EMAIL
```

## 5. HTTPS + services
```bash
sed "s/app.example.ie/app.yourdomain.ie/" /opt/opsengine/deploy/Caddyfile > /etc/caddy/Caddyfile && systemctl reload caddy
cp /opt/opsengine/deploy/*.service /opt/opsengine/deploy/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now opsengine-web opsengine-daily.timer opsengine-inbox.timer opsengine-backup.timer
curl -s https://app.yourdomain.ie/health        # -> ok
```

## 6. First accounts and first customer
```bash
cd /opt/opsengine
sudo -u opsengine python3 -m opsengine add-user you@yourdomain.ie --name "Your Name" --role ops
sudo -u opsengine python3 -m opsengine new-customer acme_groundworks --name "Acme Groundworks"
# fill in data/customers/acme_groundworks/ (see launch/07_pilot_onboarding.md), then:
sudo -u opsengine python3 -m opsengine check --customer data/customers/acme_groundworks
sudo -u opsengine python3 -m opsengine add-user owner@acme.ie --name "Owner Name" --role customer --customer acme_groundworks
sudo -u opsengine python3 -m opsengine add-user reviewer@safety.ie --name "Reviewer Name" --role reviewer
```

## 7. Check it all works
- Log in at `https://app.yourdomain.ie` as ops and as the customer (each sees only what they should).
- `systemctl start opsengine-daily` then `journalctl -u opsengine-daily` (no errors).
- `systemctl start opsengine-backup` and check `/opt/opsengine-backups/`.
- Copy backups off the server weekly at least (object storage in an EU region, or download them).
- Restore test once: `openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in FILE | tar -xz -C /tmp/restore`.

## Updating later
```bash
cd /tmp/repo && git pull && cp -r opsengine-v0/opsengine /opt/opsengine/ && systemctl restart opsengine-web
```
