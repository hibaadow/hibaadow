"""Document reading: Claude vision turns a photo or scan of a card or certificate into
document JSON with a confidence score.

The engine only accepts a read on its own when it is confident (>= 90%) AND the read is
consistent: the right document type, the right person's name, every required field present
and well formed. Anything else goes to the human review queue. Without an API key nothing
is read and every photo goes to a human - the engine never guesses."""
import base64
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

from . import llm
from .detect import parse_date

CONFIDENCE_THRESHOLD = 0.90
VISION_MODEL = os.environ.get("OPSENGINE_VISION_MODEL", "claude-opus-5-5")

# Document types the reader knows how to extract. Fields come from rules/requirements.json.
READABLE_TYPES = ("safe_pass", "cscs_scaffolding", "public_liability", "employers_liability")
EXTRA_FIELDS = {"safe_pass": ["issued"], "cscs_scaffolding": ["issued", "category"],
                "public_liability": ["issued"], "employers_liability": ["issued"]}
DATE_FIELDS = ("expires", "issued")
NUMBER_FIELDS = ("limit_eur",)

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
               ".gif": "image/gif", ".pdf": "application/pdf"}

SYSTEM = ("You read Irish construction compliance documents (SOLAS Safe Pass cards, CSCS cards, insurance "
          "certificates) from photos and scans. Report only what is printed and legible. Never guess or fill in "
          "a value you cannot read: use null and give it a low confidence. Confidence is your probability (0 to 1) "
          "that the value is exactly right. Reply with one JSON object and nothing else.")


def _fields_for(kb, doc_type):
    return list(kb.requirements[doc_type].get("required_fields", [])) + EXTRA_FIELDS.get(doc_type, [])


def _prompt(kb, expected_type):
    spec = {t: {"name": kb.requirements[t]["name"], "fields": _fields_for(kb, t)} for t in READABLE_TYPES}
    hint = f"The sender says this is a {kb.requirements[expected_type]['name']}. Check that it really is.\n" \
        if expected_type in spec else ""
    return (f"{hint}Identify the document type and extract its fields.\n"
            f"Known types and their fields: {json.dumps(spec)}\n"
            "Dates as YYYY-MM-DD. limit_eur as a whole number of euro. Reply with exactly this JSON shape:\n"
            '{"document_type": "<known type id or unknown>", "name_on_document": "<holder or company name, or null>", '
            '"fields": {"<field>": {"value": <value or null>, "confidence": <0-1>}}, '
            '"overall_confidence": <0-1>, "notes": "<anything unclear: glare, blur, cropped, back side only>"}')


def _parse_json(text):
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def read_photo(path, kb, expected_type=None, call=None):
    """Ask Claude to read one photo/scan. Returns an extraction dict; never raises on a bad read.

    `call` is the transport (defaults to llm.call); tests pass a fake so they stay offline."""
    path = Path(path)
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    base = {"file": str(path), "model": VISION_MODEL, "document_type": None, "name_on_document": None,
            "fields": {}, "overall_confidence": 0.0, "notes": ""}
    if not media_type:
        return {**base, "source": "unsupported", "notes": f"unsupported file type {path.suffix}"}
    data = base64.standard_b64encode(path.read_bytes()).decode()
    block_type = "document" if media_type == "application/pdf" else "image"
    body = {
        "model": VISION_MODEL,
        "max_tokens": 2000,
        "system": SYSTEM,
        "fallbacks": "default",  # if a safety classifier declines, the API retries on a fallback model
        "messages": [{"role": "user", "content": [
            {"type": block_type, "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": _prompt(kb, expected_type)},
        ]}],
    }
    response = (call or llm.call)(body, betas=["server-side-fallback-2026-07-01"])
    parsed = _parse_json(llm.text_of(response))
    if response is None:
        return {**base, "source": "unavailable", "notes": "Claude not available (no API key, offline or call failed)"}
    if not isinstance(parsed, dict):
        return {**base, "source": "unparseable", "notes": "Claude's reply was not usable JSON"}
    fields = {}
    for name, cell in (parsed.get("fields") or {}).items():
        if isinstance(cell, dict):
            fields[name] = {"value": cell.get("value"), "confidence": _num(cell.get("confidence"))}
    return {**base, "source": "claude", "model": response.get("model", VISION_MODEL),
            "document_type": parsed.get("document_type"), "name_on_document": parsed.get("name_on_document"),
            "fields": fields, "overall_confidence": _num(parsed.get("overall_confidence")),
            "notes": parsed.get("notes") or ""}


def _num(v):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _norm_tokens(name):
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    drop = {"ltd", "limited", "dac", "plc", "teoranta", "t/a", "the"}
    return {t for t in re.findall(r"[a-z0-9]+", s) if t not in drop}


def names_match(expected, found):
    a, b = _norm_tokens(expected), _norm_tokens(found)
    return bool(a and b) and (a <= b or b <= a)


def _clean(field, value):
    """Normalise a value; return (value, problem or None)."""
    if value in (None, ""):
        return None, None
    if field in DATE_FIELDS:
        try:
            return parse_date(value).isoformat(), None
        except ValueError:
            return value, f"{field} is not a valid date: {value!r}"
    if field in NUMBER_FIELDS:
        try:
            return int(float(str(value).replace(",", "").replace("EUR", "").replace("€", "").strip())), None
        except ValueError:
            return value, f"{field} is not a number: {value!r}"
    return str(value).strip(), None


def assess(extraction, kb, customer, holder, expected_type=None):
    """Score a read. Returns (confidence 0-1, reasons it needs a human, cleaned field values)."""
    reasons = []
    doc_type = extraction.get("document_type")
    if extraction.get("source") != "claude":
        return 0.0, [extraction.get("notes") or "document was not read"], {}
    if doc_type not in READABLE_TYPES:
        reasons.append(f"document type not recognised ({doc_type})")
        return 0.0, reasons, {}
    if expected_type and doc_type != expected_type:
        reasons.append(f"expected {expected_type} but this looks like {doc_type}")
    required = kb.requirements[doc_type].get("required_fields", [])
    cells = extraction.get("fields", {})
    values, confidences = {}, [extraction.get("overall_confidence", 0.0)]
    for f in _fields_for(kb, doc_type):
        cell = cells.get(f) or {}
        value, problem = _clean(f, cell.get("value"))
        if problem:
            reasons.append(problem)
        if value is not None:
            values[f] = value
        if f in required:
            confidences.append(cell.get("confidence", 0.0) if value is not None else 0.0)
            if value is None:
                reasons.append(f"could not read {f}")
    expected_name = customer.holder_name(holder)
    if not names_match(expected_name, extraction.get("name_on_document")):
        reasons.append(f"name on document ({extraction.get('name_on_document')}) does not match {expected_name}")
    confidence = round(min(confidences), 3)
    if confidence < CONFIDENCE_THRESHOLD:
        reasons.append(f"confidence {confidence:.0%} is below {CONFIDENCE_THRESHOLD:.0%}")
    return confidence, reasons, values


def to_document(extraction, values, holder, context=None, received_via="whatsapp", confidence=None, reviewed_by=None):
    path = Path(extraction["file"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8] if path.exists() else "nofile"
    doc_type = extraction.get("document_type")
    doc = {"id": f"d-{doc_type}-{holder}-{digest}", "type": doc_type, "holder": holder, **values,
           "file": path.name, "received_via": received_via,
           "extraction": {"model": extraction.get("model"), "confidence": confidence,
                          "name_on_document": extraction.get("name_on_document"), "reviewed_by": reviewed_by}}
    if context:
        doc["context"] = context
    return doc
