"""WhatsApp through Meta's WhatsApp Business Cloud API: sending to workers, and photos coming back.

Settings (.env):
  WHATSAPP_MODE=cloud            off (default) = WhatsApp messages stay queued in the outbox
  WHATSAPP_TOKEN                 permanent access token (System User) from Meta Business settings
  WHATSAPP_PHONE_NUMBER_ID       the "Phone number ID" shown in the WhatsApp > API setup page
  WHATSAPP_APP_SECRET            the Meta app's secret: proves webhook calls really come from Meta
  WHATSAPP_VERIFY_TOKEN          any long random string; typed into Meta's webhook setup page too
  WHATSAPP_TEMPLATE              approved template name (default cleartowork_message)
  WHATSAPP_TEMPLATE_LANG         its language code (default en)

The 24-hour rule: WhatsApp only lets a business send free text to someone who messaged it in the
last 24 hours. Outside that window we send the approved template ("ClearToWork has a message about
<subject>. Reply to this chat to read it.") and keep the full message; it goes out the moment the
worker replies. Nothing is lost and nothing breaks WhatsApp's rules.

Incoming (Meta calls POST /whatsapp on the portal):
  - the signature is checked against WHATSAPP_APP_SECRET; anything unsigned is refused
  - the sender's number is matched to a worker (or owner / subcontractor contact) of a customer
  - photos and PDFs go through the normal photo reader (engine.ingest_photo), so unsure reads wait
    for a person; texts are logged in the communication history
  - unknown numbers are kept for the ops team; nothing is guessed."""
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GRAPH = "https://graph.facebook.com/v21.0"
WINDOW = timedelta(hours=24)
MEDIA_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}


def mode():
    return (os.environ.get("WHATSAPP_MODE") or "off").strip().lower()


def number(phone):
    """'+353 87 000 0201' / '087 000 0201' / '353870000201' -> '353870000201' (WhatsApp's format)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "353" + digits[1:]            # Irish local number
    return digits


class Window:
    """When each number last wrote to us, and full messages waiting for a reply."""

    def __init__(self, state_dir):
        self.dir = Path(state_dir) / "whatsapp"
        self.file = self.dir / "last_inbound.json"

    def _read(self):
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def seen(self, num, when=None):
        data = self._read()
        data[num] = (when or datetime.now(timezone.utc)).isoformat()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def is_open(self, num, now=None):
        ts = self._read().get(num)
        if not ts:
            return False
        return (now or datetime.now(timezone.utc)) - datetime.fromisoformat(ts) < WINDOW - timedelta(minutes=5)

    def hold(self, num, body):
        path = self.dir / "pending" / f"{num}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        waiting = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        waiting.append(body)
        path.write_text(json.dumps(waiting, indent=1), encoding="utf-8")

    def take(self, num):
        path = self.dir / "pending" / f"{num}.json"
        if not path.exists():
            return []
        waiting = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
        return waiting


# ---------------- sending ----------------

class PermanentFailure(Exception):
    pass


def _graph(path, payload=None, method="POST"):
    token = os.environ.get("WHATSAPP_TOKEN", "")
    if not token:
        raise PermanentFailure("no WHATSAPP_TOKEN")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{GRAPH}/{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 429 or exc.code >= 500:
            raise OSError(f"whatsapp {exc.code}: {detail}") from exc
        raise PermanentFailure(f"whatsapp {exc.code}: {detail}") from exc


def _text(num, body):
    return {"messaging_product": "whatsapp", "to": num, "type": "text",
            "text": {"preview_url": False, "body": body[:4096]}}


def _template(num, subject):
    subject = re.sub(r"\s+", " ", subject).strip()[:200] or "your site paperwork"
    return {"messaging_product": "whatsapp", "to": num, "type": "template",
            "template": {"name": os.environ.get("WHATSAPP_TEMPLATE", "cleartowork_message"),
                         "language": {"code": os.environ.get("WHATSAPP_TEMPLATE_LANG", "en")},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": subject}]}]}}


def send(address, subject, body, state_dir, post=None, now=None):
    """Send one message. Returns a delivery status string like connectors.send does.
    post(path, payload) replaces the Graph API call (tests)."""
    num = number(address)
    if len(num) < 8:
        return "failed: no WhatsApp number"
    post = post or _graph
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    win = Window(state_dir)
    try:
        if win.is_open(num, now):
            post(f"{phone_id}/messages", _text(num, body))
            return "sent"
        post(f"{phone_id}/messages", _template(num, subject))
        win.hold(num, body)
        return "sent (template; full message goes when they reply)"
    except PermanentFailure as exc:
        return f"failed: {exc}"
    except OSError as exc:
        return f"failed: {exc}"


# ---------------- receiving ----------------

def verify(params):
    """Meta's one-off webhook check: return the challenge if the verify token matches, else None."""
    want = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if want and params.get("hub.mode") == "subscribe" and hmac.compare_digest(params.get("hub.verify_token", ""), want):
        return params.get("hub.challenge", "")
    return None


def signed(raw, header):
    """True when X-Hub-Signature-256 matches the body, signed with the app secret."""
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False
    good = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, header[7:])


def _contacts(customers):
    """WhatsApp number -> (customer id, holder id or None, name)."""
    idx = {}
    for cid, folder in customers.items():
        folder = Path(folder)
        company = json.loads((folder / "company.json").read_text(encoding="utf-8"))
        workers = json.loads((folder / "workers.json").read_text(encoding="utf-8"))
        for w in workers:
            if w.get("phone"):
                idx[number(w["phone"])] = (cid, w["id"], w.get("name", w["id"]))
        owner = company.get("owner", {})
        if owner.get("phone"):
            idx.setdefault(number(owner["phone"]), (cid, "company", owner.get("name", "Owner")))
        for sc in company.get("subcontractors", []):
            ph = sc.get("contact", {}).get("phone")
            if ph:
                idx.setdefault(number(ph), (cid, "company", sc.get("contact", {}).get("name", sc["name"])))
    return idx


def download(media_id):
    """(bytes, mime type) for a media id from a webhook."""
    meta = _graph(media_id, method="GET")
    token = os.environ.get("WHATSAPP_TOKEN", "")
    req = urllib.request.Request(meta["url"], headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), meta.get("mime_type", "")


def messages(payload):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []) or []:
                yield m


def handle(payload, customers, state_dir, today=None, fetch=None, post=None, call=None):
    """File every message in one webhook call. Returns a list of summary dicts."""
    from .engine import Engine
    fetch = fetch or download
    state = Path(state_dir)
    idx = _contacts(customers)
    win = Window(state)
    out = []
    for m in messages(payload):
        num = number(m.get("from", ""))
        kind = m.get("type")
        win.seen(num)
        for body in win.take(num):              # full messages that waited for this reply
            send(num, "", body, state, post=post)
        who = idx.get(num)
        if not who:
            held = state / "whatsapp_unrouted"
            held.mkdir(parents=True, exist_ok=True)
            (held / f"{m.get('id', 'msg')}.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
            out.append({"status": "unrouted", "from": num})
            continue
        cid, holder, name = who
        eng = Engine(customers[cid], state_dir=state, today=today)
        open_issues = [i for i in eng.store.issues("open") if i["holder"] == holder]
        issue = open_issues[-1] if open_issues else None
        text = (m.get("text") or {}).get("body") or (m.get(kind) or {}).get("caption") or ""
        eng.store.log_comm("in", "whatsapp", name, num, text[:120] or f"({kind})",
                           issue["id"] if issue else None, None, "received", "")
        summary = {"status": "filed", "customer": cid, "holder": holder, "type": kind,
                   "issue": issue["id"] if issue else None}
        if kind in ("image", "document"):
            media = m[kind]
            folder = state / "uploads" / cid
            folder.mkdir(parents=True, exist_ok=True)
            try:
                data, mime = fetch(media["id"])
                ext = MEDIA_EXT.get(mime or media.get("mime_type", ""), ".jpg")
                path = folder / f"{date.today().isoformat()}-whatsapp-{media['id']}{ext}"
                path.write_bytes(data)
                from .vision import READABLE_TYPES
                expected = issue["requirement"] if issue and issue["requirement"] in READABLE_TYPES else None
                r = eng.ingest_photo(path, holder, context=issue.get("context") if issue else None,
                                     expected_type=expected, received_via="whatsapp", call=call)
            except Exception as exc:              # never lose a photo: a person looks at it
                review = eng._hold_for_review({"file": "", "holder": holder},
                                              [f"WhatsApp photo could not be read automatically: {exc}"], "whatsapp")
                r = {"status": "needs_review", "review": review}
            summary["photo"] = r["status"]
        out.append(summary)
    return out
