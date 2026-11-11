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


def complete(system, prompt, max_tokens=1500):
    """Return Claude's text reply, or None if unavailable or the call fails."""
    if not available():
        return None
    body = json.dumps({
        "model": DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        return "".join(b.get("text", "") for b in data.get("content", []))
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        return None


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
