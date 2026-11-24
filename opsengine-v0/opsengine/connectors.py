"""Outgoing connectors. Every message is always written to the outbox and logged in the
communication history; sending is an extra step on top.

EMAIL_MODE=outbox (default): nothing leaves the machine; a person sends from the outbox.
EMAIL_MODE=smtp: email is also sent through SMTP_HOST (settings in .env). Works with any
transactional email provider that offers SMTP (Postmark, Amazon SES, Resend, Brevo...).
  - Port 465 uses SSL; any other port uses STARTTLS.
  - Temporary failures are retried (3 tries); a refused address fails at once.
  - With EMAIL_REPLY_TO=inbox@yourdomain, replies go to inbox+<customer>.<issue>@yourdomain so
    `python -m opsengine inbox` can file the reply (and any photos) against the right issue.
EMAIL_MODE=resend: email is sent through Resend's HTTPS API (RESEND_API_KEY). Useful where mail
ports are blocked. Without a verified domain, Resend only delivers to your own account address,
from onboarding@resend.dev - fine for a first test.
WHATSAPP_MODE=cloud: WhatsApp messages are sent through Meta's Cloud API (see whatsapp.py);
otherwise they stay queued in the outbox."""
import json
import os
import smtplib
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import make_msgid

from . import config

RETRY_WAITS = (2, 6)          # seconds between tries; tests set this to (0, 0)


def email_mode():
    return (os.environ.get("EMAIL_MODE") or "outbox").strip().lower()


def reply_address(ref):
    """inbox@domain + (customer, issue) -> inbox+customer.issue@domain (plus addressing)."""
    base = os.environ.get("EMAIL_REPLY_TO", "").strip()
    if not base or "@" not in base or not ref:
        return base
    local, _, domain = base.partition("@")
    cid, issue = ref
    return f"{local}+{cid}.{issue}@{domain}" if issue else f"{local}+{cid}@{domain}"


def build_message(address, subject, body, ref=None, html=None):
    msg = EmailMessage()
    msg["From"] = os.environ.get("EMAIL_FROM", "")
    msg["To"] = address
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=(os.environ.get("EMAIL_FROM", "x@opsengine").split("@")[-1].strip(">") or "opsengine"))
    reply = reply_address(ref)
    if reply:
        msg["Reply-To"] = reply
    if ref:
        msg["X-OpsEngine-Ref"] = ".".join(x for x in ref if x)
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _smtp_send(msg):
    host, port = os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "587"))
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with cls(host, port, timeout=30) as s:
        if port != 465:
            s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)


class PermanentFailure(Exception):
    """The provider refused the message for good (bad address, bad key...): don't retry."""


def _resend_send(msg):
    """Send an EmailMessage through Resend's API."""
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        raise PermanentFailure("no RESEND_API_KEY")
    plain = msg.get_body(("plain",))
    html = msg.get_body(("html",))
    payload = {"from": msg["From"] or f"{config.brand()} <onboarding@resend.dev>", "to": [msg["To"]], "subject": msg["Subject"],
               "text": plain.get_content() if plain else ""}
    if html:
        payload["html"] = html.get_content()
    if msg["Reply-To"]:
        payload["reply_to"] = msg["Reply-To"]
    if msg["X-OpsEngine-Ref"]:
        payload["headers"] = {"X-OpsEngine-Ref": msg["X-OpsEngine-Ref"]}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "opsengine/0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429 or exc.code >= 500:
            raise OSError(f"resend {exc.code}") from exc            # temporary: retried
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise PermanentFailure(f"resend {exc.code}: {detail}") from exc


def send(channel, address, subject, body, ref=None, html=None, transport=None, state_dir=None):
    """Return the delivery status: sent, failed: <reason>, or queued_in_outbox (<why>).
    transport(msg) replaces SMTP (tests)."""
    if transport is None and os.environ.get("OPSENGINE_OFFLINE") == "1" and not config.flag("OPSENGINE_ALLOW_SEND_IN_TESTS"):
        return "queued_in_outbox (offline)"
    if channel == "whatsapp":
        from . import whatsapp
        from .knowledge import ROOT
        if transport is None and whatsapp.mode() != "cloud":
            return "queued_in_outbox (WHATSAPP_MODE=off)"
        return whatsapp.send(address, subject, body, state_dir or ROOT / "state", post=transport)
    if channel != "email":
        return f"queued_in_outbox (no {channel} connector yet)"
    if transport is None and email_mode() not in ("smtp", "resend"):
        return "queued_in_outbox (EMAIL_MODE=outbox)"
    if not address or "@" not in address:
        return "failed: no email address"
    msg = build_message(address, subject, body, ref, html)
    transport = transport or (_resend_send if email_mode() == "resend" else _smtp_send)
    last = None
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            transport(msg)
            return "sent" if attempt == 0 else f"sent (after {attempt + 1} tries)"
        except PermanentFailure as exc:
            return f"failed: {exc}"
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPAuthenticationError) as exc:
            return f"failed: {type(exc).__name__}"          # permanent: retrying won't help
        except (OSError, smtplib.SMTPException) as exc:
            last = exc
            if attempt < len(RETRY_WAITS):
                time.sleep(RETRY_WAITS[attempt])
    return f"failed: {type(last).__name__} after {len(RETRY_WAITS) + 1} tries"
