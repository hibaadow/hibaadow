"""Approve by link: signed, single-use, expiring links in emails.

A link only opens a confirmation page (email scanners pre-open links, so a GET never approves).
The person then presses Approve or Decline, which is recorded in the audit trail as
"<name> (via email link)". A link works once, for one step, for LINK_DAYS days, and only while
that step is still waiting for the customer's approval.

Needs OPSENGINE_SECRET (a long random string, kept in .env) and PUBLIC_URL (e.g. https://app.example.ie).

    python -m opsengine approval-emails      # email each customer owner their pending approvals with links
"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .knowledge import ROOT

LINK_DAYS = 7


def _secret():
    s = os.environ.get("OPSENGINE_SECRET", "")
    if len(s) < 32:
        raise RuntimeError("OPSENGINE_SECRET must be set to a random string of 32+ characters")
    return s.encode()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(cid, step_id, now=None, days=LINK_DAYS):
    body = _b64(json.dumps({"c": cid, "s": step_id, "e": int((time.time() if now is None else now) + days * 86400)}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest()[:20])
    return f"{body}.{sig}"


def read_token(token, now=None):
    """(customer id, step id) for a valid, unexpired token, else None. Does not check single use."""
    try:
        body, sig = token.split(".", 1)
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest()[:20])
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(body))
        if data["e"] < (time.time() if now is None else now):
            return None
        return data["c"], data["s"]
    except (ValueError, KeyError, TypeError):
        return None


class UsedLinks:
    """Remembers which tokens were used (single use)."""
    def __init__(self, state_dir=None):
        self.path = Path(state_dir or ROOT / "state" / "auth") / "links.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS used (token_hash TEXT PRIMARY KEY, ts REAL, outcome TEXT)")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _h(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def used(self, token):
        with self._db() as db:
            return db.execute("SELECT 1 FROM used WHERE token_hash = ?", (self._h(token),)).fetchone() is not None

    def mark(self, token, outcome):
        """True if this call used the link; False if it was already used."""
        try:
            with self._db() as db:
                db.execute("INSERT INTO used VALUES (?,?,?)", (self._h(token), time.time(), outcome))
            return True
        except sqlite3.IntegrityError:
            return False


def link_for(cid, step_id):
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    return f"{base}/a/{make_token(cid, step_id)}"


def approval_email(eng, cid, steps, describe):
    """Plain-text email listing pending approvals, one link each. describe(step) -> one line."""
    owner = eng.customer.company["owner"]
    lines = [f"Hi {owner['name'].split()[0]},", "",
             f"{len(steps)} thing{'s' if len(steps) != 1 else ''} need{'s' if len(steps) == 1 else ''} your OK. "
             "Open a link to see the details, then approve or decline:", ""]
    for s in steps:
        lines += [f"- {describe(s)}", f"  {link_for(cid, s['id'])}", ""]
    lines += [f"Each link works once and expires in {LINK_DAYS} days. Nothing that costs money happens without your OK.",
              "", "OpsEngine"]
    return f"Your OK is needed: {len(steps)} item{'s' if len(steps) != 1 else ''}", "\n".join(lines)
