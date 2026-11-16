"""Outgoing connectors. Every message is always written to the outbox and logged in the
communication history; sending is an extra step on top (see delivery.py for retries and WhatsApp rules).

EMAIL_MODE=outbox (default): nothing leaves the machine; a person sends from the outbox.
EMAIL_MODE=smtp: email is also sent through SMTP_HOST (settings in .env). Each email gets a
Message-ID (so delivery reports can be matched) and the issue reference in the subject (so replies
with attachments can be matched to the issue).
WHATSAPP_MODE=cloud: WhatsApp through the Meta Cloud API (whatsapp.py)."""
import os
import secrets
import smtplib
from email.message import EmailMessage

from . import config, whatsapp


def email_mode():
    return (os.environ.get("EMAIL_MODE") or "outbox").strip().lower()


def offline():
    return os.environ.get("OPSENGINE_OFFLINE") == "1" and not config.flag("OPSENGINE_ALLOW_SEND_IN_TESTS")


def message_id(customer_id="", step_id=""):
    domain = (os.environ.get("EMAIL_FROM", "").rpartition("@")[2] or "opsengine.invalid").strip("> ")
    return f"<{customer_id or 'x'}.{step_id or 'x'}.{secrets.token_hex(6)}@{domain}>"


def deliver(channel, address, subject, body, ref="", customer_id="", step_id="", smtp=None):
    """One delivery attempt. Returns {"status": sent | queued_in_outbox (...) | failed: ..., "message_id",
    "permanent": True when retrying can't help}."""
    if offline():
        return {"status": "queued_in_outbox (offline)"}
    if channel == "whatsapp":
        if whatsapp.mode() != "cloud":
            return {"status": "queued_in_outbox (WHATSAPP_MODE=queue)"}
        return whatsapp.send_text(address, body)
    if channel != "email":
        return {"status": f"queued_in_outbox (no {channel} connector yet)"}
    if email_mode() != "smtp":
        return {"status": "queued_in_outbox (EMAIL_MODE=outbox)"}
    if not address or "@" not in address:
        return {"status": "failed: no email address", "permanent": True}
    msg = EmailMessage()
    msg["From"] = os.environ.get("EMAIL_FROM", "")
    msg["To"] = address
    msg["Subject"] = f"{subject} [{ref}]" if ref and ref not in subject else subject
    msg["Message-ID"] = mid = message_id(customer_id, step_id)
    msg.set_content(body)
    try:
        with (smtp or smtplib.SMTP)(os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return {"status": "sent", "message_id": mid}
    except smtplib.SMTPRecipientsRefused:
        return {"status": "failed: address refused", "permanent": True}
    except (OSError, smtplib.SMTPException) as exc:
        return {"status": f"failed: {type(exc).__name__}", "permanent": False}


def send(channel, address, subject, body):
    """Return the delivery status: sent, failed: <reason>, or queued_in_outbox (<why>)."""
    if channel == "whatsapp" and whatsapp.mode() != "cloud" and not offline():
        return "queued_in_outbox (no whatsapp connector set up: WHATSAPP_MODE=queue)"
    return deliver(channel, address, subject, body)["status"]
