"""Approve by link (AUDIT.md Phase 3): one-tap approvals from an email, without weakening the rules.

- Only customer approvals (money and commitments) can be given by link. Safety reviewer and ops
  approvals stay in the portal, behind sign-in and an authenticator code.
- Each link is for one item and one named person (the customer's owner), is secret (256 random
  bits, only its SHA-256 is stored), expires after LINK_HOURS and works once.
- Opening the link never approves anything (mail scanners open links): it shows the item and an
  Approve / Decline form. Only pressing a button does it, recorded as "Name <email> (email link)".
- A link stops working as soon as the item is approved, declined or changed another way.
Links look like <OPSENGINE_PUBLIC_URL>/a/<64 hex characters>."""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from .store import now_iso

LINK_HOURS = 72
ROLE = "customer"


def _hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def public_url():
    return (os.environ.get("OPSENGINE_PUBLIC_URL") or "").rstrip("/")


def approver(engine):
    o = engine.customer.company["owner"]
    return o["name"], o["email"]


def issue_link(engine, step_id, hours=LINK_HOURS):
    step = engine.store.step(step_id)
    if not step or step["state"] != "awaiting_approval":
        raise ValueError(f"{step_id} is not awaiting approval")
    if step["approval_role"] != ROLE:
        raise PermissionError("only customer approvals can be given by link; safety and ops sign-off stay in the portal")
    name, email = approver(engine)
    secret = secrets.token_hex(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
    engine.store.db.execute("INSERT INTO approval_links (token_hash, step_id, approver, address, issued_at, expires_at)"
                            " VALUES (?,?,?,?,?,?)", (_hash(secret), step_id, name, email, now_iso(), expires))
    engine.store.db.commit()
    engine.store.audit("engine", "approval_link_issued", step_id, {"to": f"{name} <{email}>", "expires": expires})
    return f"{public_url()}/a/{secret}"


LINK = re.compile(r"/a/[0-9a-f]{64}")


def redact(text):
    return LINK.sub("/a/[one-time link, in the email only]", text or "")


def can_email_links():
    """Links are only issued when email really goes out. A message waiting in the outbox for a person
    to send has its link removed, so a link there would be useless (and a secret lying around)."""
    from . import connectors
    return connectors.email_mode() == "smtp" and not connectors.offline() and bool(public_url())


LINK_FOOTER = "The link works once and expires in 3 days. Nothing happens until you choose. You can also do this in the portal."
PORTAL_FOOTER = "Approve or decline in the portal. Nothing happens until you choose."


def owns(engine, secret):
    """Does this customer's database hold this link? (Used to find the customer from a link.)"""
    return bool(engine.store.db.execute("SELECT 1 FROM approval_links WHERE token_hash=?", (_hash(secret),)).fetchone())


def check(engine, secret):
    """Returns (link, step) or raises ValueError with a plain-English reason. Never changes anything."""
    row = engine.store.db.execute("SELECT * FROM approval_links WHERE token_hash=?", (_hash(secret),)).fetchone()
    if not row:
        raise ValueError("This link isn't valid. Use the portal, or ask the ops team for a new link.")
    link = dict(row)
    if link["used_at"]:
        raise ValueError(f"This link has already been used ({link['outcome']}). Each link works once.")
    if link["expires_at"] < now_iso():
        raise ValueError("This link has expired. Use the portal, or wait for tomorrow's reminder with a new link.")
    step = engine.store.step(link["step_id"])
    if not step or step["state"] != "awaiting_approval" or step["approval_role"] != ROLE:
        raise ValueError("This item no longer needs your approval. It may have been dealt with in the portal.")
    return link, step


def use(engine, secret, decision, reason="", ip=""):
    """Approve or decline through a link. Returns the engine events."""
    try:
        link, step = check(engine, secret)
    except ValueError as exc:
        engine.store.audit("link", "approval_link_refused", "", {"reason": str(exc), "ip": ip})
        raise
    by = f"{link['approver']} <{link['address']}> (email link)"
    engine.store.db.execute("UPDATE approval_links SET used_at=?, outcome=? WHERE token_hash=?",
                            (now_iso(), decision, link["token_hash"]))
    engine.store.db.commit()
    engine.store.audit("link", "approval_link_used", step["id"], {"decision": decision, "by": by, "ip": ip})
    if decision == "approved":
        return engine.approve(step["id"], by)
    if decision == "declined":
        engine.reject(step["id"], by, reason or "declined by email link")
        return [(step["id"], "rejected")]
    raise ValueError("decision must be approved or declined")
