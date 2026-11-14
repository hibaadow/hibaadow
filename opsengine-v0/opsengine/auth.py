"""Accounts, sessions and sign-in security for the portal (AUDIT.md Phase 2, defect D6). Stdlib only.

- Passwords: PBKDF2-SHA256, 600,000 iterations, per-user salt; never stored or logged in clear.
- Sessions: random 256-bit tokens; only a SHA-256 of the token is stored; 12-hour lifetime.
- Staff (ops, reviewer, admin) need a second step: a 6-digit code from an authenticator app (TOTP,
  RFC 6238), set up at first sign-in.
- 5 failed sign-ins lock the account for 15 minutes.
- Every account event (sign-in, failure, lockout, user created or disabled, password or code reset) is
  written to the accounts database's own append-only, hash-chained audit log.
- Customer users are tied to exactly one customer and can only ever see that customer.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import Store, now_iso

ROLES = ("customer", "ops", "reviewer", "admin")
STAFF = ("ops", "reviewer", "admin")
PBKDF2_ITERATIONS = 600_000
SESSION_HOURS = 12
PENDING_MFA_MINUTES = 5
MAX_FAILURES = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 12
COMMON = {"password1234", "123456789012", "qwertyuiop12", "opsengine123", "letmein12345", "passwordpassword"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE, name TEXT, role TEXT, customer_id TEXT,
    password_hash TEXT, mfa_secret TEXT, failures INTEGER DEFAULT 0, locked_until TEXT,
    disabled INTEGER DEFAULT 0, demo INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT, stage TEXT, csrf TEXT, created_at TEXT, expires_at TEXT
);
"""


class AuthError(Exception):
    """A sign-in problem safe to show the person (never says whether the email exists)."""


# ---------------- primitives ----------------

def hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password, stored):
    try:
        algo, iterations, salt, digest = stored.split("$")
    except (AttributeError, ValueError):
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
    return hmac.compare_digest(candidate, base64.b64decode(digest))


def password_problems(password, email=""):
    out = []
    if len(password) < MIN_PASSWORD:
        out.append(f"use at least {MIN_PASSWORD} characters")
    local = email.split("@")[0].lower() if email else ""
    if password.lower() in COMMON or (len(local) >= 3 and local in password.lower()):
        out.append("choose something less guessable")
    return out


def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret, at=None, step=30, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((at if at is not None else time.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def check_totp(secret, code, at=None, window=1):
    code = re.sub(r"\s", "", str(code or ""))
    now = at if at is not None else time.time()
    return any(hmac.compare_digest(totp(secret, now + 30 * w), code) for w in range(-window, window + 1))


def totp_uri(secret, email, issuer="OpsEngine"):
    return f"otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}&digits=6&period=30"


def _now():
    return datetime.now(timezone.utc)


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------- accounts ----------------

class Accounts:
    def __init__(self, path):
        self.store = Store(path)  # gives us the append-only, hash-chained audit log
        self.db = self.store.db
        self.db.executescript(SCHEMA)

    def audit(self, actor, event, ref="", payload=None):
        self.store.audit(actor, event, ref, payload or {})

    # users
    def users(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM users ORDER BY role, email")]

    def user(self, user_id=None, email=None):
        if email is not None:
            row = self.db.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        else:
            row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def add_user(self, email, name, role, password, customer_id=None, by="admin", demo=False, check_strength=True):
        email = email.strip().lower()
        if role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        if role == "customer" and not customer_id:
            raise ValueError("a customer user must belong to a customer (--customer)")
        if role != "customer" and customer_id:
            raise ValueError("staff users are not tied to one customer")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("enter a valid email address")
        if self.user(email=email):
            raise ValueError("a user with that email already exists")
        if check_strength and password_problems(password, email):
            raise ValueError("password: " + "; ".join(password_problems(password, email)))
        uid = "u-" + secrets.token_hex(4)
        self.db.execute("INSERT INTO users (id, email, name, role, customer_id, password_hash, demo, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (uid, email, name, role, customer_id, hash_password(password), int(demo), now_iso()))
        self.db.commit()
        self.audit(f"admin:{by}", "user_created", uid, {"email": email, "name": name, "role": role,
                                                         "customer": customer_id, "demo": demo})
        return uid

    def set_disabled(self, user_id, disabled, by="admin"):
        self.db.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user_id))
        self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        self.db.commit()
        self.audit(f"admin:{by}", "user_disabled" if disabled else "user_enabled", user_id, {})

    def set_password(self, user_id, password, by="admin"):
        u = self.user(user_id)
        if password_problems(password, u["email"]):
            raise ValueError("password: " + "; ".join(password_problems(password, u["email"])))
        self.db.execute("UPDATE users SET password_hash=?, failures=0, locked_until=NULL WHERE id=?",
                        (hash_password(password), user_id))
        self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        self.db.commit()
        self.audit(f"admin:{by}", "password_reset", user_id, {})

    def reset_mfa(self, user_id, by="admin"):
        self.db.execute("UPDATE users SET mfa_secret=NULL WHERE id=?", (user_id,))
        self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        self.db.commit()
        self.audit(f"admin:{by}", "mfa_reset", user_id, {})

    def mfa_required(self, user):
        return user["role"] in STAFF and not user["demo"]

    # sign-in
    def sign_in(self, email, password, ip=""):
        """Step 1. Returns (token, stage) where stage is 'active' or 'mfa' / 'mfa_setup' for staff."""
        u = self.user(email=email or "")
        if not u or u["disabled"]:
            hash_password(password or "x")  # same work either way, so timing doesn't reveal accounts
            self.audit("anonymous", "sign_in_failed", "", {"email": (email or "")[:120], "ip": ip, "reason": "unknown or disabled"})
            raise AuthError("Email or password is wrong.")
        if u["locked_until"] and datetime.fromisoformat(u["locked_until"]) > _now():
            self.audit(f"user:{u['id']}", "sign_in_blocked", u["id"], {"ip": ip, "locked_until": u["locked_until"]})
            raise AuthError(f"Too many failed attempts. Try again after {LOCK_MINUTES} minutes.")
        if not check_password(password or "", u["password_hash"]):
            failures = u["failures"] + 1
            locked = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat() if failures >= MAX_FAILURES else None
            self.db.execute("UPDATE users SET failures=?, locked_until=? WHERE id=?",
                            (0 if locked else failures, locked, u["id"]))
            self.db.commit()
            self.audit(f"user:{u['id']}", "sign_in_failed", u["id"], {"ip": ip, "failures": failures, "locked": bool(locked)})
            raise AuthError("Email or password is wrong." if not locked
                            else f"Too many failed attempts. Try again after {LOCK_MINUTES} minutes.")
        self.db.execute("UPDATE users SET failures=0, locked_until=NULL WHERE id=?", (u["id"],))
        self.db.commit()
        if self.mfa_required(u):
            stage = "mfa" if u["mfa_secret"] else "mfa_setup"
            token = self._new_session(u["id"], stage, minutes=PENDING_MFA_MINUTES)
            self.audit(f"user:{u['id']}", "password_ok_awaiting_code", u["id"], {"ip": ip, "stage": stage})
            return token, stage
        token = self._new_session(u["id"], "active")
        self.audit(f"user:{u['id']}", "signed_in", u["id"], {"ip": ip, "role": u["role"], "customer": u["customer_id"]})
        return token, "active"

    def verify_code(self, token, code, ip="", new_secret=None):
        """Step 2 for staff. With new_secret, this also confirms first-time authenticator setup."""
        s = self.session(token, stages=("mfa", "mfa_setup"))
        if not s:
            raise AuthError("Your sign-in expired. Start again.")
        u = self.user(s["user_id"])
        secret = new_secret if s["stage"] == "mfa_setup" else u["mfa_secret"]
        if not secret or not check_totp(secret, code):
            self.audit(f"user:{u['id']}", "code_failed", u["id"], {"ip": ip})
            raise AuthError("That code didn't work. Check the time on your phone and try again.")
        if s["stage"] == "mfa_setup":
            self.db.execute("UPDATE users SET mfa_secret=? WHERE id=?", (secret, u["id"]))
            self.audit(f"user:{u['id']}", "mfa_enabled", u["id"], {"ip": ip})
        self.db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
        self.db.commit()
        new = self._new_session(u["id"], "active")
        self.audit(f"user:{u['id']}", "signed_in", u["id"], {"ip": ip, "role": u["role"], "with_code": True})
        return new

    def _new_session(self, user_id, stage, minutes=None):
        token = secrets.token_urlsafe(32)
        expires = _now() + (timedelta(minutes=minutes) if minutes else timedelta(hours=SESSION_HOURS))
        self.db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                        (_token_hash(token), user_id, stage, secrets.token_urlsafe(24), now_iso(), expires.isoformat()))
        self.db.commit()
        return token

    def session(self, token, stages=("active",)):
        if not token:
            return None
        row = self.db.execute("SELECT * FROM sessions WHERE token_hash=?", (_token_hash(token),)).fetchone()
        if not row or row["stage"] not in stages or datetime.fromisoformat(row["expires_at"]) < _now():
            return None
        u = self.user(row["user_id"])
        if not u or u["disabled"]:
            return None
        return {**dict(row), "user": u}

    def sign_out(self, token):
        s = self.session(token, stages=("active", "mfa", "mfa_setup"))
        self.db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token or ""),))
        self.db.commit()
        if s:
            self.audit(f"user:{s['user_id']}", "signed_out", s["user_id"], {})


def identity(user):
    """How an authenticated person is recorded on approvals and in customer audit logs."""
    return f"{user['name']} <{user['email']}>"


DEMO_PASSWORD = "sample-demo-only"
DEMO_USERS = [  # created only for SAMPLE customers, only with `web --demo`
    ("grainne@bremore-groundworks.example.ie", "Gráinne Murphy (SAMPLE)", "customer", "bremore_groundworks_sample"),
    ("ciara@liffey-interiors.example.ie", "Ciara Byrne (SAMPLE)", "customer", "liffey_interiors"),
    ("ops@opsengine.example.ie", "Ops team (SAMPLE)", "ops", None),
    ("reviewer@opsengine.example.ie", "Safety reviewer (SAMPLE)", "reviewer", None),
]


def ensure_demo_users(accounts, sample_customer_ids):
    for email, name, role, cid in DEMO_USERS:
        if cid and cid not in sample_customer_ids:
            continue
        if not accounts.user(email=email):
            accounts.add_user(email, name, role, DEMO_PASSWORD, customer_id=cid, by="demo-setup", demo=True,
                              check_strength=False)
