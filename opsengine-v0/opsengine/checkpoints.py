"""Signed audit checkpoints (AUDIT.md Phase 2).

The audit log in each database is hash-chained, so editing one row breaks the chain. But someone
with write access to the database file could rebuild the whole chain. A checkpoint records, for
every audit log, how many entries it had and the hash of the last one, signed with a secret key
(HMAC-SHA256) that is not stored with the data. Checkpoints are appended to a file kept somewhere
else (ideally a different machine or bucket), each one chained to the one before.

Verification recomputes every signature, then checks each database still has, at the recorded
position, exactly the recorded hash, and that its chain is intact. A rewritten history fails,
even if its own chain looks fine.

The key comes from OPSENGINE_CHECKPOINT_KEY (at least 32 characters). It is never written to disk
by this code. Keep it in the host's secret store."""
import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIN_KEY = 32


def _key():
    key = os.environ.get("OPSENGINE_CHECKPOINT_KEY", "")
    if len(key) < MIN_KEY:
        raise PermissionError(f"Set OPSENGINE_CHECKPOINT_KEY to a secret of at least {MIN_KEY} characters "
                              "(kept in your host's secret store, not in the code or the data).")
    return key.encode()


def _sign(record, key):
    body = json.dumps({k: v for k, v in record.items() if k != "signature"}, sort_keys=True).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def audit_dbs(state_dir):
    """Every database under the state folder that has an audit table (customers and accounts)."""
    out = []
    for db in sorted(Path(state_dir).rglob("*.db")):
        con = sqlite3.connect(db)
        try:
            if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit'").fetchone():
                out.append(db)
        finally:
            con.close()
    return out


def _head(db):
    con = sqlite3.connect(db)
    try:
        row = con.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        count = con.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    finally:
        con.close()
    return {"entries": count, "last_seq": row[0] if row else 0, "last_hash": row[1] if row else "GENESIS"}


def _read(file):
    file = Path(file)
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_checkpoint(state_dir, file):
    """Append one signed checkpoint covering every audit log under state_dir."""
    key = _key()
    state_dir = Path(state_dir)
    previous = _read(file)
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "previous": previous[-1]["signature"] if previous else "GENESIS",
              "logs": {db.relative_to(state_dir).as_posix(): _head(db) for db in audit_dbs(state_dir)}}
    record["signature"] = _sign(record, key)
    Path(file).parent.mkdir(parents=True, exist_ok=True)
    with open(file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def verify(state_dir, file):
    """Returns a list of problems; empty means every checkpoint holds."""
    from .store import Store
    key = _key()
    state_dir = Path(state_dir)
    problems, previous = [], "GENESIS"
    records = _read(file)
    if not records:
        return ["no checkpoints found"]
    for n, rec in enumerate(records, start=1):
        if not hmac.compare_digest(_sign(rec, key), rec.get("signature", "")):
            problems.append(f"checkpoint {n} ({rec.get('at')}): signature doesn't match (checkpoint file altered, or wrong key)")
        if rec.get("previous") != previous:
            problems.append(f"checkpoint {n} ({rec.get('at')}): not chained to the one before (a checkpoint was removed or reordered)")
        previous = rec.get("signature")
        for rel, head in rec.get("logs", {}).items():
            db = state_dir / rel
            if not db.exists():
                problems.append(f"checkpoint {n}: {rel} is missing")
                continue
            if head["last_seq"]:
                con = sqlite3.connect(db)
                try:
                    row = con.execute("SELECT hash FROM audit WHERE seq=?", (head["last_seq"],)).fetchone()
                finally:
                    con.close()
                if not row or row[0] != head["last_hash"]:
                    problems.append(f"checkpoint {n} ({rec.get('at')}): {rel} history was rewritten "
                                    f"(entry {head['last_seq']} no longer matches)")
    for db in audit_dbs(state_dir):
        store = Store(db)
        try:
            ok, bad = store.verify_audit()
        finally:
            store.db.close()
        if not ok:
            problems.append(f"{db.relative_to(state_dir).as_posix()}: hash chain broken at entry {bad}")
    return problems
