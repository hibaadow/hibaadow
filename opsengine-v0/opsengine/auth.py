"""Logins for the portal (stdlib only).

Accounts and sessions live in SQLite under the state folder (git-ignored, never in the repo).
Passwords are hashed with scrypt. Sessions are random tokens stored server-side with an expiry;
the cookie is HttpOnly, SameSite=Strict, and Secure when the portal runs behind HTTPS.

Roles:
  customer  - one customer's owner or office manager; sees only their own company
  ops       - the internal ops team; sees every customer
  reviewer  - the competent safety reviewer; sees every customer's review queue

Add an account:  python -m opsengine add-user owner@firm.ie --name "Ciara Byrne" --role customer --customer <id>
"""
import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ROLES = ("customer", "ops", "reviewer")
SESSION_HOURS = 12
MIN_PASSWORD = 10
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def _hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


class Auth:
    def __init__(self, state_dir):
        self.path = Path(state_dir) / "auth.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, customer TEXT,
                salt BLOB NOT NULL, pw BLOB NOT NULL, created REAL NOT NULL, failed INTEGER DEFAULT 0, locked_until REAL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, email TEXT NOT NULL, expires REAL NOT NULL)""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:              # commit or roll back
                yield db
        finally:
            db.close()

    # ---- accounts ----
    def add_user(self, email, name, role, password, customer=None):
        email = email.strip().lower()
        if role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        if role == "customer" and not customer:
            raise ValueError("a customer account needs --customer")
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
        salt = secrets.token_bytes(16)
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO users (email, name, role, customer, salt, pw, created) VALUES (?,?,?,?,?,?,?)",
                       (email, name, role, customer if role == "customer" else None, salt, _hash(password, salt), time.time()))
        return email

    def user(self, email):
        with self._db() as db:
            row = db.execute("SELECT email, name, role, customer FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None

    def users(self):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT email, name, role, customer FROM users ORDER BY email")]

    def remove_user(self, email):
        email = email.strip().lower()
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE email = ?", (email,))
            return db.execute("DELETE FROM users WHERE email = ?", (email,)).rowcount

    # ---- login ----
    def login(self, email, password):
        """Return a session token, or None. Five wrong passwords lock the account for 15 minutes."""
        email = (email or "").strip().lower()
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not row:
                _hash(password or "", b"x" * 16)          # same work either way: don't reveal which emails exist
                return None
            if row["locked_until"] > time.time():
                return None
            if not hmac.compare_digest(_hash(password or "", row["salt"]), row["pw"]):
                failed = row["failed"] + 1
                db.execute("UPDATE users SET failed = ?, locked_until = ? WHERE email = ?",
                           (failed, time.time() + 900 if failed >= 5 else 0, email))
                return None
            db.execute("UPDATE users SET failed = 0, locked_until = 0 WHERE email = ?", (email,))
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token, email, time.time() + SESSION_HOURS * 3600))
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        return token

    def session(self, token):
        """The logged-in user for a session token, or None."""
        if not token:
            return None
        with self._db() as db:
            row = db.execute("""SELECT u.email, u.name, u.role, u.customer FROM sessions s JOIN users u ON u.email = s.email
                                WHERE s.token = ? AND s.expires > ?""", (token, time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token or "",))

    @staticmethod
    def can_see(user, cid):
        return user is not None and (user["role"] != "customer" or user["customer"] == cid)
