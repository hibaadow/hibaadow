#!/bin/sh
# Nightly backup: consistent copies of every SQLite database, plus customer data, uploads and
# evidence, encrypted with BACKUP_PASSPHRASE (from /opt/opsengine/.env), kept for 30 days.
# Copy the backups off this server too (e.g. object storage in an EU region) - see SETUP.md.
set -eu
cd /opt/opsengine
. ./.env
: "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE in .env}"
STAMP=$(date +%Y-%m-%d)
WORK=$(mktemp -d)
DEST=/opt/opsengine-backups
mkdir -p "$DEST" "$WORK/state"
find state -name '*.db' | while read -r db; do
  mkdir -p "$WORK/$(dirname "$db")"
  python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "$db" "$WORK/$db"
done
tar -C /opt/opsengine -cf "$WORK/files.tar" data/customers $(cd /opt/opsengine && ls -d state/uploads state/*/evidence state/*/outbox 2>/dev/null || true)
tar -C "$WORK" -czf - state files.tar | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$DEST/opsengine-$STAMP.tar.gz.enc"
rm -rf "$WORK"
find "$DEST" -name 'opsengine-*.tar.gz.enc' -mtime +30 -delete
echo "backup ok: $DEST/opsengine-$STAMP.tar.gz.enc"
# Restore: openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in FILE | tar -xz
