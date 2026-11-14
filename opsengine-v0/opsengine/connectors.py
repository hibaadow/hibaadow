"""Outgoing connectors. Every message is always written to the outbox and logged in the
communication history; sending is an extra step on top.

EMAIL_MODE=outbox (default): nothing leaves the machine; a person sends from the outbox.
EMAIL_MODE=smtp: email is also sent through SMTP_HOST (settings in .env).
WhatsApp has no connector yet, so WhatsApp messages stay queued in the outbox."""
import os
import smtplib
from email.message import EmailMessage

from . import config


def email_mode():
    return (os.environ.get("EMAIL_MODE") or "outbox").strip().lower()


def send(channel, address, subject, body):
    """Return the delivery status: sent, failed: <reason>, or queued_in_outbox (<why>)."""
    if os.environ.get("OPSENGINE_OFFLINE") == "1" and not config.flag("OPSENGINE_ALLOW_SEND_IN_TESTS"):
        return "queued_in_outbox (offline)"
    if channel != "email":
        return f"queued_in_outbox (no {channel} connector yet)"
    if email_mode() != "smtp":
        return "queued_in_outbox (EMAIL_MODE=outbox)"
    if not address or "@" not in address:
        return "failed: no email address"
    msg = EmailMessage()
    msg["From"] = os.environ.get("EMAIL_FROM", "")
    msg["To"] = address
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return "sent"
    except (OSError, smtplib.SMTPException) as exc:
        return f"failed: {type(exc).__name__}"
