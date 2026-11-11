"""SQLite state store: documents, issues, steps and the hash-chained audit log."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, type TEXT, holder TEXT, context TEXT,
    data TEXT, source TEXT, added_at TEXT
);
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY, key TEXT, requirement TEXT, holder TEXT, context TEXT,
    category TEXT, kind TEXT, severity TEXT, status TEXT, detail TEXT,
    required_by TEXT, data TEXT, created_at TEXT, updated_at TEXT, resolved_at TEXT, proof TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY, issue_id TEXT, seq INTEGER, action TEXT, spec TEXT,
    state TEXT, approval_role TEXT, approved_by TEXT, approved_at TEXT,
    result TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY, file TEXT, holder TEXT, context TEXT, extraction TEXT,
    confidence REAL, reasons TEXT, status TEXT, created_at TEXT,
    decided_by TEXT, decided_at TEXT, decision TEXT, document_id TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, event TEXT,
    ref TEXT, payload TEXT, prev_hash TEXT, hash TEXT
);
"""

OPEN_STATUSES = ("open", "in_progress", "escalated")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------- audit (append-only, hash chained) ----------
    def audit(self, actor, event, ref="", payload=None):
        payload_json = json.dumps(payload or {}, sort_keys=True, default=str)
        last = self.db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else "GENESIS"
        ts = now_iso()
        digest = hashlib.sha256(f"{prev}|{ts}|{actor}|{event}|{ref}|{payload_json}".encode()).hexdigest()
        self.db.execute(
            "INSERT INTO audit (ts, actor, event, ref, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
            (ts, actor, event, ref, payload_json, prev, digest),
        )
        self.db.commit()

    def verify_audit(self):
        prev = "GENESIS"
        for row in self.db.execute("SELECT * FROM audit ORDER BY seq"):
            expected = hashlib.sha256(
                f"{prev}|{row['ts']}|{row['actor']}|{row['event']}|{row['ref']}|{row['payload']}".encode()
            ).hexdigest()
            if row["prev_hash"] != prev or row["hash"] != expected:
                return False, row["seq"]
            prev = row["hash"]
        return True, None

    def audit_rows(self, limit=None):
        sql = "SELECT * FROM audit ORDER BY seq" + (f" DESC LIMIT {int(limit)}" if limit else "")
        return [dict(r) for r in self.db.execute(sql)]

    # ---------- documents ----------
    def add_document(self, doc, source, actor="engine"):
        self.db.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?)",
            (doc["id"], doc["type"], doc["holder"], doc.get("context"), json.dumps(doc), source, now_iso()),
        )
        self.db.commit()
        self.audit(actor, "document_added", doc["id"], {"type": doc["type"], "holder": doc["holder"], "source": source})

    def documents(self):
        return [json.loads(r["data"]) for r in self.db.execute("SELECT data FROM documents")]

    def has_documents(self):
        return self.db.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] > 0

    # ---------- issues ----------
    def open_issue_by_key(self, key):
        row = self.db.execute(
            f"SELECT * FROM issues WHERE key=? AND status IN {OPEN_STATUSES}", (key,)
        ).fetchone()
        return dict(row) if row else None

    def next_issue_id(self):
        n = self.db.execute("SELECT COUNT(*) c FROM issues").fetchone()["c"] + 1
        return f"ISS-{n:04d}"

    def insert_issue(self, issue):
        cols = ",".join(issue.keys())
        marks = ",".join("?" for _ in issue)
        self.db.execute(f"INSERT INTO issues ({cols}) VALUES ({marks})", list(issue.values()))
        self.db.commit()

    def update_issue(self, issue_id, **fields):
        fields["updated_at"] = now_iso()
        sets = ",".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE issues SET {sets} WHERE id=?", [*fields.values(), issue_id])
        self.db.commit()

    def issue(self, issue_id):
        row = self.db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        return dict(row) if row else None

    def issues(self, status=None):
        if status == "open":
            rows = self.db.execute(f"SELECT * FROM issues WHERE status IN {OPEN_STATUSES} ORDER BY id")
        elif status:
            rows = self.db.execute("SELECT * FROM issues WHERE status=? ORDER BY id", (status,))
        else:
            rows = self.db.execute("SELECT * FROM issues ORDER BY id")
        return [dict(r) for r in rows]

    # ---------- steps ----------
    def insert_step(self, step):
        cols = ",".join(step.keys())
        marks = ",".join("?" for _ in step)
        self.db.execute(f"INSERT INTO steps ({cols}) VALUES ({marks})", list(step.values()))
        self.db.commit()

    def update_step(self, step_id, **fields):
        fields["updated_at"] = now_iso()
        sets = ",".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE steps SET {sets} WHERE id=?", [*fields.values(), step_id])
        self.db.commit()

    def steps(self, issue_id=None, state=None):
        sql, args = "SELECT * FROM steps WHERE 1=1", []
        if issue_id:
            sql += " AND issue_id=?"
            args.append(issue_id)
        if state:
            sql += " AND state=?"
            args.append(state)
        rows = self.db.execute(sql + " ORDER BY issue_id, seq", args)
        out = []
        for r in rows:
            d = dict(r)
            d["spec"] = json.loads(d["spec"] or "{}")
            d["result"] = json.loads(d["result"] or "null")
            out.append(d)
        return out

    def step(self, step_id):
        found = [s for s in self.steps() if s["id"] == step_id]
        return found[0] if found else None

    # ---------- human review queue (low-confidence document reads) ----------
    def add_review(self, review):
        n = self.db.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"] + 1
        review = {**review, "id": f"REV-{n:04d}", "status": "pending", "created_at": now_iso()}
        for k in ("extraction", "reasons"):
            review[k] = json.dumps(review[k], default=str)
        cols = ",".join(review.keys())
        self.db.execute(f"INSERT INTO reviews ({cols}) VALUES ({','.join('?' for _ in review)})", list(review.values()))
        self.db.commit()
        return review["id"]

    def update_review(self, review_id, **fields):
        if "decision" in fields:
            fields["decision"] = json.dumps(fields["decision"], default=str)
        sets = ",".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE reviews SET {sets} WHERE id=?", [*fields.values(), review_id])
        self.db.commit()

    def reviews(self, status=None):
        sql, args = "SELECT * FROM reviews", []
        if status:
            sql, args = sql + " WHERE status=?", [status]
        out = []
        for r in self.db.execute(sql + " ORDER BY id", args):
            d = dict(r)
            for k in ("extraction", "reasons", "decision"):
                d[k] = json.loads(d[k]) if d[k] else None
            out.append(d)
        return out

    def review(self, review_id):
        found = [r for r in self.reviews() if r["id"] == review_id]
        return found[0] if found else None
