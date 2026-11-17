"""SQLite state store: documents, issues, steps and the hash-chained audit log."""
import hashlib
import json
import re
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
CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY, issue_id TEXT, step_id TEXT, provider_id TEXT, provider_name TEXT,
    holder TEXT, kind TEXT, date TEXT, status TEXT, price_eur REAL, notes TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS comms (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, direction TEXT, channel TEXT, to_name TEXT,
    address TEXT, subject TEXT, issue_id TEXT, step_id TEXT, status TEXT, outbox TEXT
);
CREATE TABLE IF NOT EXISTS quotes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, issue_id TEXT, provider_id TEXT, provider_name TEXT,
    price_eur REAL, lead_days INTEGER, status TEXT
);
CREATE TRIGGER IF NOT EXISTS comms_append_only_u BEFORE UPDATE ON comms BEGIN SELECT RAISE(ABORT, 'communication log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS comms_append_only_d BEFORE DELETE ON comms BEGIN SELECT RAISE(ABORT, 'communication log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS quotes_append_only_u BEFORE UPDATE ON quotes BEGIN SELECT RAISE(ABORT, 'quotes are append-only'); END;
CREATE TRIGGER IF NOT EXISTS quotes_append_only_d BEFORE DELETE ON quotes BEGIN SELECT RAISE(ABORT, 'quotes are append-only'); END;
CREATE TABLE IF NOT EXISTS approval_links (
    token_hash TEXT PRIMARY KEY, step_id TEXT, approver TEXT, address TEXT, issued_at TEXT, expires_at TEXT,
    used_at TEXT, outcome TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, to_name TEXT, address TEXT, subject TEXT, body TEXT,
    issue_id TEXT, step_id TEXT, outbox TEXT, message_id TEXT, status TEXT, attempts INTEGER DEFAULT 0,
    next_try TEXT, last_error TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS contact_prefs (
    address TEXT PRIMARY KEY, channel TEXT, opted_out_at TEXT, last_inbound_at TEXT
);
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY, issue_id TEXT, holder TEXT, raised_by TEXT, channel TEXT, reason TEXT, status TEXT,
    due_on TEXT, decided_by TEXT, decided_at TEXT, decision_note TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS people (
    pid TEXT PRIMARY KEY, kind TEXT, value TEXT UNIQUE COLLATE NOCASE, first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, event TEXT,
    ref TEXT, payload TEXT, prev_hash TEXT, hash TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_append_only_u BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_append_only_d BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

OPEN_STATUSES = ("open", "in_progress", "escalated")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
NAMED_EMAIL = re.compile(r"([^<>:\"]{2,80}?)\s*<([^<>\s]+@[^<>\s]+)>")
TOKEN = re.compile(r"⟪(P-\d{4,})⟫")
REMOVED = "[removed person]"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)  # wait for a concurrent writer instead of failing
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------- audit (append-only, hash chained) ----------
    # ---------- people in the audit log (pseudonymised: AUDIT.md, GDPR review Q4) ----------
    # The audit log never holds a name, email, phone number or IP address: each is replaced by a token
    # such as ⟪P-0007⟫, and the token-to-person table is kept apart. Deleting a person's rows from
    # `people` (forget) leaves the log tamper-evident but anonymous for them.
    _pattern = None

    def register_people(self, values, kind="name"):
        changed = False
        for v in values:
            v = (v or "").strip()
            if len(v) < 3:
                continue
            if not self.db.execute("SELECT 1 FROM people WHERE value=?", (v,)).fetchone():
                n = self.db.execute("SELECT COUNT(*) FROM people").fetchone()[0] + 1
                pid = f"P-{n:04d}"
                while self.db.execute("SELECT 1 FROM people WHERE pid=?", (pid,)).fetchone():
                    n += 1
                    pid = f"P-{n:04d}"
                self.db.execute("INSERT INTO people (pid, kind, value, first_seen, last_seen) VALUES (?,?,?,?,?)",
                                (pid, kind, v, now_iso(), now_iso()))
                changed = True
        if changed:
            self.db.commit()
            self._pattern = None

    def register_person(self, name="", email="", phone=""):
        """A person and the variants of their details that may appear in log text."""
        if name:
            self.register_people([name, name.replace(" ", "_"), name.replace(" ", "-")], "name")
        if email:
            self.register_people([email], "email")
        if phone:
            digits = "".join(ch for ch in phone if ch.isdigit())
            self.register_people([phone, digits, "+" + digits if digits else ""], "phone")

    def pseudonymise(self, text):
        if not text:
            return text
        for m in NAMED_EMAIL.finditer(text):  # "Name <email>" of someone not on file (e.g. staff)
            self.register_person(m.group(1).strip(), m.group(2))
        self.register_people(EMAIL.findall(text), "email")
        self.register_people(IPV4.findall(text), "ip")
        if self._pattern is None:
            rows = self.db.execute("SELECT pid, value FROM people").fetchall()
            self._lookup = {r["value"].lower(): r["pid"] for r in rows}
            values = sorted(self._lookup, key=len, reverse=True)
            self._pattern = re.compile("|".join(re.escape(v) for v in values), re.IGNORECASE) if values else False
        if not self._pattern:
            return text
        seen = set()

        def sub(m):
            pid = self._lookup[m.group(0).lower()]
            seen.add(pid)
            return f"⟪{pid}⟫"
        out = self._pattern.sub(sub, text)
        if seen:
            self.db.executemany("UPDATE people SET last_seen=? WHERE pid=?", [(now_iso(), pid) for pid in seen])
        return out

    def reidentify(self, text):
        if not text or "⟪" not in text:
            return text
        names = {}
        for r in self.db.execute("SELECT pid, value, kind FROM people ORDER BY LENGTH(value) DESC"):
            if r["pid"] not in names or (r["kind"] == "name" and " " in r["value"]):
                names[r["pid"]] = r["value"]
        return TOKEN.sub(lambda m: names.get(m.group(1), REMOVED), text)

    def forget(self, values=(), kinds=(), before=None):
        """Erase people from the token table. Returns how many entries were removed."""
        n = 0
        for v in values:
            if v:
                n += self.db.execute("DELETE FROM people WHERE value=?", (v,)).rowcount
        for kind in kinds:
            sql, args = "DELETE FROM people WHERE kind=?", [kind]
            if before:
                sql, args = sql + " AND last_seen < ?", args + [before]
            n += self.db.execute(sql, args).rowcount
        self.db.commit()
        self._pattern = None
        return n

    def audit(self, actor, event, ref="", payload=None):
        actor, ref = self.pseudonymise(actor), self.pseudonymise(ref)
        payload_json = self.pseudonymise(json.dumps(payload or {}, sort_keys=True, default=str, ensure_ascii=False))
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

    def audit_rows(self, limit=None, raw=False):
        """Audit entries with people's details put back for display (raw=True: as stored, tokens only)."""
        sql = "SELECT * FROM audit ORDER BY seq" + (f" DESC LIMIT {int(limit)}" if limit else "")
        rows = [dict(r) for r in self.db.execute(sql)]
        if not raw:
            for r in rows:
                for k in ("actor", "ref", "payload"):
                    r[k] = self.reidentify(r[k])
        return rows

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

    # ---------- appointments (training sessions, inspections, services) ----------
    def add_appointment(self, appt):
        n = self.db.execute("SELECT COUNT(*) c FROM appointments").fetchone()["c"] + 1
        appt = {**appt, "id": f"APT-{n:04d}", "created_at": now_iso(), "updated_at": now_iso()}
        self.db.execute(f"INSERT INTO appointments ({','.join(appt)}) VALUES ({','.join('?' for _ in appt)})",
                        list(appt.values()))
        self.db.commit()
        return appt["id"]

    def update_appointment(self, appt_id, **fields):
        fields["updated_at"] = now_iso()
        self.db.execute(f"UPDATE appointments SET {','.join(f'{k}=?' for k in fields)} WHERE id=?",
                        [*fields.values(), appt_id])
        self.db.commit()

    def appointments(self, status=None, issue_id=None):
        sql, args = "SELECT * FROM appointments WHERE 1=1", []
        if status:
            sql, args = sql + " AND status=?", args + [status]
        if issue_id:
            sql, args = sql + " AND issue_id=?", args + [issue_id]
        return [dict(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def appointment(self, appt_id):
        row = self.db.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
        return dict(row) if row else None

    # ---------- communication history ----------
    def log_comm(self, direction, channel, to_name, address, subject, issue_id, step_id, status, outbox=""):
        self.db.execute("INSERT INTO comms (ts, direction, channel, to_name, address, subject, issue_id, step_id, status, outbox)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (now_iso(), direction, channel, to_name, address, subject, issue_id, step_id, status, outbox))
        self.db.commit()
        self.audit("engine" if direction == "out" else f"inbound:{channel}", "message_logged", step_id or issue_id or "",
                   {"direction": direction, "channel": channel, "to": to_name, "subject": subject, "status": status})

    def comms(self, issue_id=None):
        sql, args = "SELECT * FROM comms", []
        if issue_id:
            sql, args = sql + " WHERE issue_id=?", [issue_id]
        return [dict(r) for r in self.db.execute(sql + " ORDER BY seq", args)]

    # ---------- quotes ----------
    def add_quote(self, issue_id, provider_id, provider_name, price_eur, lead_days, status):
        self.db.execute("INSERT INTO quotes (ts, issue_id, provider_id, provider_name, price_eur, lead_days, status)"
                        " VALUES (?,?,?,?,?,?,?)", (now_iso(), issue_id, provider_id, provider_name, price_eur, lead_days, status))
        self.db.commit()
        self.audit("engine", "quote_requested", issue_id, {"provider": provider_id, "listed_price_eur": price_eur, "status": status})

    def quotes(self, issue_id=None):
        sql, args = "SELECT * FROM quotes", []
        if issue_id:
            sql, args = sql + " WHERE issue_id=?", [issue_id]
        return [dict(r) for r in self.db.execute(sql + " ORDER BY seq", args)]

    def provider_stats(self):
        """Per provider: bookings, completed, no-shows, cancellations (spec 7 and 11)."""
        stats = {}
        for a in self.appointments():
            s = stats.setdefault(a["provider_id"], {"name": a["provider_name"], "booked": 0, "completed": 0,
                                                    "no_show": 0, "cancelled": 0})
            s["booked"] += 1
            if a["status"] in ("attended", "completed"):
                s["completed"] += 1
            elif a["status"] in ("no_show", "cancelled"):
                s[a["status"]] += 1
        for s in stats.values():
            closed = s["completed"] + s["no_show"] + s["cancelled"]
            s["reliability"] = round(s["completed"] / closed, 2) if closed else None
        return stats

    # ---------- settings (e.g. the customer's standing approval) ----------
    def setting(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value, by):
        self.db.execute("INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
                        "value=excluded.value, updated_at=excluded.updated_at", (key, json.dumps(value), now_iso()))
        self.db.commit()
        self.audit(by, "setting_changed", key, {"value": value})

    # ---------- deliveries (retries, delivery reports, WhatsApp messages waiting for a reply window) ----------
    def add_delivery(self, **d):
        d = {"created_at": now_iso(), "updated_at": now_iso(), **d}
        cur = self.db.execute(f"INSERT INTO deliveries ({', '.join(d)}) VALUES ({', '.join('?' * len(d))})", list(d.values()))
        self.db.commit()
        return cur.lastrowid

    def update_delivery(self, delivery_id, **fields):
        fields["updated_at"] = now_iso()
        self.db.execute(f"UPDATE deliveries SET {', '.join(k + '=?' for k in fields)} WHERE id=?", [*fields.values(), delivery_id])
        self.db.commit()

    def deliveries(self, status=None, message_id=None):
        sql, args = "SELECT * FROM deliveries WHERE 1=1", []
        if status:
            sql, args = sql + " AND status=?", args + [status]
        if message_id:
            sql, args = sql + " AND message_id=?", args + [message_id]
        return [dict(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    # ---------- contact preferences (WhatsApp opt-out, last message from them) ----------
    def contact_pref(self, address):
        row = self.db.execute("SELECT * FROM contact_prefs WHERE address=?", (address,)).fetchone()
        return dict(row) if row else {}

    def set_contact_pref(self, address, channel, **fields):
        self.db.execute("INSERT INTO contact_prefs (address, channel) VALUES (?, ?) ON CONFLICT(address) DO NOTHING", (address, channel))
        if fields:
            self.db.execute(f"UPDATE contact_prefs SET {', '.join(k + '=?' for k in fields)} WHERE address=?", [*fields.values(), address])
        self.db.commit()

    # ---------- GDPR: redaction (the audit log keeps the fact, not the personal data) ----------
    def redact_document(self, doc_id, keep, by, reason):
        row = self.db.execute("SELECT data FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return False
        doc = json.loads(row["data"])
        redacted = {k: (v if k in keep else "[deleted]") for k, v in doc.items()}
        self.db.execute("UPDATE documents SET data=? WHERE id=?", (json.dumps(redacted), doc_id))
        self.db.commit()
        self.audit(by, "document_redacted", doc_id, {"reason": reason, "kept": sorted(keep)})
        return True
