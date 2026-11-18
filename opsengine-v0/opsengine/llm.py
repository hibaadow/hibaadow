"""Claude for drafting, translation and reading photos, through a switchable provider (stdlib only).

AI_PROVIDER chooses the service (see config.ai_provider):
- anthropic: the Claude API, with ANTHROPIC_API_KEY.
- vertex: Claude on Google Cloud Vertex AI. VERTEX_PROJECT_ID, VERTEX_REGION (default "eu", the EU
  multi-region), and Google credentials: GOOGLE_APPLICATION_CREDENTIALS pointing at a service account key
  file, or the attached service account when running on Google Cloud (google_auth.py).
- mock: never calls anything; recorded reads for the SAMPLE photos only.
- off: no AI.
Models are settings, read at each call: OPSENGINE_MODEL (drafting and translation) and
OPSENGINE_VISION_MODEL (photos).

Whenever the AI is unavailable or a call fails, callers fall back to people: photos go to the human
review queue, translations are flagged [TRANSLATION NEEDED], drafts use the template. Nothing is faked.

Logging: every call is logged as metadata only (provider, model, purpose, outcome, time taken, token
counts). Prompts, replies, file names and people's names are never logged. Translation and drafting
replace people's names with placeholders before anything is sent (redact_names / restore_names)."""
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("opsengine.ai")
API_URL = "https://api.anthropic.com/v1/messages"
VERTEX_VERSION = "vertex-2023-10-16"
CLIENT_ONLY_BETAS = {"server-side-fallback-2026-07-01"}  # not offered on Vertex: a refusal goes to a person instead
last_call = {}


def text_model():
    return os.environ.get("OPSENGINE_MODEL") or "claude-sonnet-5-5"


def vision_model():
    return os.environ.get("OPSENGINE_VISION_MODEL") or "claude-opus-5-5"


DEFAULT_MODEL = text_model()  # kept for older callers; read text_model() for the live value


def provider():
    return config.ai_provider()


def vertex_region():
    return (os.environ.get("VERTEX_REGION") or "eu").strip().lower()


def vertex_url(model, region=None, project=None):
    region = region or vertex_region()
    project = project or os.environ.get("VERTEX_PROJECT_ID", "")
    host = ("aiplatform.googleapis.com" if region == "global" else
            f"aiplatform.{region}.rep.googleapis.com" if region in ("eu", "us") else
            f"{region}-aiplatform.googleapis.com")
    return f"https://{host}/v1/projects/{project}/locations/{region}/publishers/anthropic/models/{model}:rawPredict"


def unavailable_reason():
    """None when calls can be made; otherwise why not, in plain words (no secrets)."""
    p = provider()
    if os.environ.get("OPSENGINE_OFFLINE") == "1":
        return "offline (tests)"
    if p == "mock":
        return "mock mode"
    if p == "off":
        return "AI is switched off (AI_PROVIDER=off or no provider set)"
    if p == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is empty"
    if p == "vertex" and not os.environ.get("VERTEX_PROJECT_ID"):
        return "VERTEX_PROJECT_ID is empty"
    return None


def available():
    return unavailable_reason() is None


def _record(purpose, model, outcome, started, response=None, status=None):
    usage = (response or {}).get("usage") or {}
    entry = {"provider": provider(), "model": model, "purpose": purpose, "outcome": outcome, "status": status,
             "ms": int((time.monotonic() - started) * 1000), "input_tokens": usage.get("input_tokens"),
             "output_tokens": usage.get("output_tokens"), "stop_reason": (response or {}).get("stop_reason")}
    last_call.clear()
    last_call.update(entry)
    log.info("ai call %s", json.dumps(entry, sort_keys=True))  # metadata only: never prompts, replies or names
    return entry


def call(body, betas=None, purpose="general", transport=None, token=None):
    """POST one Messages request to the chosen provider. Returns the response dict, or None (then a person
    takes over). `transport(url, headers, data)` and `token()` are for tests."""
    body = dict(body)
    model = body.get("model") or text_model()
    started = time.monotonic()
    if not available():
        _record(purpose, model, f"unavailable: {unavailable_reason()}", started)
        return None
    headers = {"content-type": "application/json"}
    p = provider()
    if p == "vertex":
        from . import google_auth
        try:
            headers["authorization"] = f"Bearer {(token or google_auth.access_token)()}"
        except google_auth.AuthError as exc:
            _record(purpose, model, f"unavailable: {exc}", started)
            return None
        url = vertex_url(model)
        body.pop("model", None)
        body.pop("fallbacks", None)
        body["anthropic_version"] = VERTEX_VERSION
        betas = [b for b in (betas or []) if b not in CLIENT_ONLY_BETAS]
    else:
        url = API_URL
        body["model"] = model
        headers.update({"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    if betas:
        headers["anthropic-beta"] = ",".join(betas)
    data = json.dumps(body).encode()
    try:
        response = (transport or _post)(url, headers, data)
    except urllib.error.HTTPError as exc:
        _record(purpose, model, "failed", started, status=exc.code)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        _record(purpose, model, f"failed: {type(exc).__name__}", started)
        return None
    _record(purpose, model, "refused" if response.get("stop_reason") == "refusal" else "ok", started, response)
    return response


def _post(url, headers, data):
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def text_of(response):
    """The reply text, or None if there is no usable reply (including a safety refusal)."""
    if not response or response.get("stop_reason") == "refusal":
        return None
    return "".join(b.get("text", "") for b in response.get("content", []) if b.get("type") == "text") or None


def complete(system, prompt, max_tokens=1500, purpose="general", **kw):
    """Return Claude's text reply, or None if unavailable or the call fails."""
    return text_of(call({"model": text_model(), "max_tokens": max_tokens, "system": system,
                         "messages": [{"role": "user", "content": prompt}]}, purpose=purpose, **kw))


# ---------------- keeping people's names out of prompts ----------------
def redact_names(text, names):
    """Swap each name (and its first name) for a placeholder. Returns (text, mapping)."""
    mapping, n = {}, 0
    variants = []
    for name in names:
        name = (name or "").strip()
        if len(name) < 3:
            continue
        variants.append(name)
        first = name.split()[0]
        if len(first) >= 3 and first != name:
            variants.append(first)
    for v in sorted(set(variants), key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(v)}(?!\w)")
        if pattern.search(text):
            n += 1
            token = f"[[P{n}]]"
            mapping[token] = v
            text = pattern.sub(token, text)
    return text, mapping


def restore_names(text, mapping):
    """Put names back. None if the reply lost or invented a placeholder (then a person takes over)."""
    if text is None:
        return None
    if set(re.findall(r"\[\[P\d+\]\]", text)) != set(mapping) and mapping:
        return None
    for token, name in mapping.items():
        text = text.replace(token, name)
    return text


TRANSLATE_SYSTEM = ("You translate short construction-site compliance messages for Irish subcontractors. "
                    "Use plain, friendly language a site worker understands. Keep names, dates, card names "
                    "(Safe Pass, CSCS), numbers and placeholders like [[P1]] exactly as they are. "
                    "Reply with the translation only.")

DRAFT_SYSTEM = ("You draft construction compliance documents for small Irish subcontractors, for review by a "
                "competent safety person before use. Be specific to the facts given, mark every assumption "
                "with [CHECK], and never claim legal sign-off. People appear as placeholders like [[P1]]: keep "
                "them exactly as they are. Use plain English and markdown headings.")


def translate(text, language_name, names=(), **kw):
    safe, mapping = redact_names(text, names)
    out = complete(TRANSLATE_SYSTEM, f"Translate into {language_name}:\n\n{safe}", max_tokens=800, purpose="translate", **kw)
    return restore_names(out.strip(), mapping) if out else None


def draft(doc_type, facts, names=(), **kw):
    safe, mapping = redact_names(json.dumps(facts, indent=2, default=str, ensure_ascii=False), names)
    prompt = f"Draft a {doc_type.replace('_', ' ')} using these facts (JSON):\n{safe}"
    return restore_names(complete(DRAFT_SYSTEM, prompt, max_tokens=3000, purpose="draft", **kw), mapping)
