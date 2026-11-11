"""Optional Claude integration for drafting and translation.

With ANTHROPIC_API_KEY set, the engine calls the Claude Messages API (stdlib only, no SDK).
Without it, the engine falls back to templates and flags work for a human - it never
pretends a translation or draft was done."""
import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("OPSENGINE_MODEL", "claude-sonnet-5-5")


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("OPSENGINE_OFFLINE") != "1"


def call(body, betas=None):
    """POST one Messages API request; return the parsed response dict, or None if unavailable or failed."""
    if not available():
        return None
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if betas:
        headers["anthropic-beta"] = ",".join(betas)
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        return None


def text_of(response):
    """The reply text, or None if there is no usable reply (including a safety refusal)."""
    if not response or response.get("stop_reason") == "refusal":
        return None
    return "".join(b.get("text", "") for b in response.get("content", []) if b.get("type") == "text") or None


def complete(system, prompt, max_tokens=1500):
    """Return Claude's text reply, or None if unavailable or the call fails."""
    return text_of(call({
        "model": DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }))


TRANSLATE_SYSTEM = ("You translate short construction-site compliance messages for Irish subcontractors. "
                    "Use plain, friendly language a site worker understands. Keep names, dates, card names "
                    "(Safe Pass, CSCS) and numbers unchanged. Reply with the translation only.")

DRAFT_SYSTEM = ("You draft construction compliance documents for small Irish subcontractors, for review by a "
                "competent safety person before use. Be specific to the facts given, mark every assumption "
                "with [CHECK], and never claim legal sign-off. Use plain English and markdown headings.")


def translate(text, language_name):
    out = complete(TRANSLATE_SYSTEM, f"Translate into {language_name}:\n\n{text}", max_tokens=800)
    return out.strip() if out else None


def draft(doc_type, facts):
    prompt = f"Draft a {doc_type.replace('_', ' ')} using these facts (JSON):\n{json.dumps(facts, indent=2, default=str)}"
    return complete(DRAFT_SYSTEM, prompt, max_tokens=3000)
