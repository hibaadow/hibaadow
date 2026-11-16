"""Backups that are proven to restore (AUDIT.md Phase 2).

backup:  copies every database with SQLite's online backup (safe while the portal is running) and
         every other file (evidence, messages, uploads) into <dest>/<UTC time>/, then writes a
         manifest with each file's SHA-256 and each audit log's entry count and last hash.
verify:  re-hashes every file, runs SQLite's integrity check, re-verifies every audit chain and
         compares with the manifest.
restore: verifies, copies into a new empty folder (never over live data), then verifies the copy.
prune:   keeps the newest N backups.

Backups contain personal data. Keep the destination on encrypted storage with access limited to
the people who need it; see deploy/README.md."""
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "MANIFEST.json"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _audit_head(db):
    con = sqlite3.connect(db)
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit'").fetchone():
            return None
        row = con.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        return {"entries": con.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
                "last_hash": row[1] if row else "GENESIS"}
    finally:
        con.close()


def _files(state_dir):
    for p in sorted(Path(state_dir).rglob("*")):
        if p.is_file() and not p.name.endswith(("-wal", "-shm", "-journal")):
            yield p


def backup(state_dir, dest):
    state_dir, dest = Path(state_dir), Path(dest)
    live = state_dir.resolve()
    if dest.resolve() == live or live in dest.resolve().parents:
        raise ValueError("put backups outside the live data folder (ideally on separate, encrypted storage)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = dest / stamp
    n = 1
    while target.exists():
        n += 1
        target = dest / f"{stamp}-{n}"
    target.mkdir(parents=True)
    manifest = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": str(state_dir.resolve()),
                "files": {}}
    for src in _files(state_dir):
        rel = src.relative_to(state_dir).as_posix()
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".db":
            s, d = sqlite3.connect(src), sqlite3.connect(out)
            try:
                s.backup(d)
            finally:
                s.close()
                d.close()
        else:
            shutil.copy2(src, out)
        entry = {"sha256": _sha256(out), "bytes": out.stat().st_size}
        if src.suffix == ".db":
            entry["audit"] = _audit_head(out)
        manifest["files"][rel] = entry
    (target / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return target


def verify(backup_dir):
    """Returns a list of problems; empty means the backup is complete and restorable."""
    from .store import Store
    backup_dir = Path(backup_dir)
    try:
        manifest = json.loads((backup_dir / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["manifest missing or unreadable"]
    problems = []
    for rel, entry in manifest["files"].items():
        f = backup_dir / rel
        if not f.exists():
            problems.append(f"{rel}: missing")
            continue
        if _sha256(f) != entry["sha256"]:
            problems.append(f"{rel}: contents changed since the backup was made")
            continue
        if f.suffix == ".db":
            con = sqlite3.connect(f)
            try:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append(f"{rel}: database integrity check failed")
            finally:
                con.close()
            if entry.get("audit"):
                store = Store(f)
                try:
                    ok, bad = store.verify_audit()
                finally:
                    store.db.close()
                if not ok:
                    problems.append(f"{rel}: audit chain broken at entry {bad}")
                if _audit_head(f) != entry["audit"]:
                    problems.append(f"{rel}: audit log differs from the manifest")
    extra = {p.relative_to(backup_dir).as_posix() for p in backup_dir.rglob("*") if p.is_file()} - set(manifest["files"]) - {MANIFEST}
    problems += [f"{rel}: not in the manifest" for rel in sorted(extra)]
    return problems


def restore(backup_dir, target):
    backup_dir, target = Path(backup_dir), Path(target)
    problems = verify(backup_dir)
    if problems:
        raise ValueError("backup failed verification: " + "; ".join(problems[:5]))
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"{target} isn't empty; restore into a new folder, check it, then switch over")
    manifest = json.loads((backup_dir / MANIFEST).read_text(encoding="utf-8"))
    for rel in manifest["files"]:
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_dir / rel, out)
    for rel, entry in manifest["files"].items():
        if _sha256(target / rel) != entry["sha256"]:
            raise ValueError(f"restored {rel} doesn't match the backup")
    return target


def prune(dest, keep=14):
    backups = sorted((p for p in Path(dest).iterdir() if (p / MANIFEST).exists()), key=lambda p: p.name)
    removed = backups[:-keep] if keep and len(backups) > keep else []
    for p in removed:
        shutil.rmtree(p)
    return removed


def latest(dest):
    backups = sorted((p for p in Path(dest).iterdir() if (p / MANIFEST).exists()), key=lambda p: p.name) if Path(dest).exists() else []
    return backups[-1] if backups else None
