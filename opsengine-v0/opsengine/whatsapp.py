"""WhatsApp Business (Meta Cloud API) connector, stdlib only. AUDIT.md Phase 3.

WHATSAPP_MODE=queue (default): nothing is sent; messages wait in the outbox.
WHATSAPP_MODE=cloud: sent through the Cloud API with WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID.

WhatsApp rules this follows:
- Only people with a recorded opt-in ("whatsapp_opt_in": "YYYY-MM-DD" in workers.json) are messaged,
  and anyone who replies STOP is never messaged again on WhatsApp (they can reply START).
- A business may only send free text within 24 hours of the person's last message. Outside that
  window it sends the approved template WHATSAPP_TEMPLATE ("You have a message from {company} about
  {subject}. Reply to this message to see it.") and the full message goes as soon as they reply.
- Inbound webhooks are only accepted with a valid X-Hub-Signature-256 (WHATSAPP_APP_SECRET).

Nothing here has run against Meta yet: it needs a WhatsApp Business account. Tests use a fake transport."""
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

GRAPH = "https://graph.facebook.com/v20.0"


def mode():
    return (os.environ.get("WHATSAPP_MODE") or "queue").strip().lower()


def _urllib(method, url, headers, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _auth():
    return {"Authorization": f"Bearer {os.environ.get('WHATSAPP_TOKEN', '')}"}


def digits(phone):
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def _send(payload, transport=None):
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    if not phone_id or not os.environ.get("WHATSAPP_TOKEN"):
        return {"status": "failed: WhatsApp settings missing", "permanent": True}
    try:
        status, raw = (transport or _urllib)("POST", f"{GRAPH}/{phone_id}/messages",
                                             {**_auth(), "Content-Type": "application/json"},
                                             json.dumps({"messaging_product": "whatsapp", **payload}).encode())
    except OSError as exc:
        return {"status": f"failed: {type(exc).__name__}", "permanent": False}
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        body = {}
    if 200 <= status < 300 and body.get("messages"):
        return {"status": "sent", "message_id": body["messages"][0].get("id", "")}
    code = (body.get("error") or {}).get("code")
    # 4xx other than rate limits won't succeed on retry (bad number, template not approved, no permission)
    return {"status": f"failed: WhatsApp error {code or status}", "permanent": 400 <= status < 500 and status != 429}


def send_text(to, body, transport=None):
    return _send({"to": digits(to), "type": "text", "text": {"body": body[:4096]}}, transport)


def send_template(to, params, transport=None):
    name = os.environ.get("WHATSAPP_TEMPLATE", "opsengine_message")
    lang = os.environ.get("WHATSAPP_TEMPLATE_LANGUAGE", "en")
    return _send({"to": digits(to), "type": "template", "template": {
        "name": name, "language": {"code": lang},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)[:200]} for p in params]}]}},
        transport)


def verify_signature(raw, header):
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def parse_webhook(payload):
    """Returns (messages, statuses) from a Cloud API webhook body."""
    messages, statuses = [], []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for m in value.get("messages", []):
                kind = m.get("type")
                media = m.get(kind, {}) if kind in ("image", "document") else {}
                messages.append({"id": m.get("id"), "from": digits(m.get("from")), "type": kind,
                                 "text": (m.get("text") or {}).get("body", "") or media.get("caption", ""),
                                 "media_id": media.get("id"), "mime": media.get("mime_type", ""),
                                 "filename": media.get("filename", "")})
            for s in value.get("statuses", []):
                statuses.append({"id": s.get("id"), "status": s.get("status"),
                                 "error": ((s.get("errors") or [{}])[0]).get("title", "")})
    return messages, statuses


def download_media(media_id, transport=None):
    t = transport or _urllib
    status, raw = t("GET", f"{GRAPH}/{media_id}", _auth())
    if status != 200:
        raise OSError(f"media lookup failed ({status})")
    info = json.loads(raw)
    status, data = t("GET", info["url"], _auth())
    if status != 200:
        raise OSError(f"media download failed ({status})")
    return data, info.get("mime_type", "")
