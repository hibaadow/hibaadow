"""Plain-English wording built from data. The words live in templates/labels.json."""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class Wording:
    def __init__(self, data):
        self.data = data

    @classmethod
    def load(cls, root=ROOT):
        return cls(json.loads((Path(root) / "templates" / "labels.json").read_text(encoding="utf-8")))

    def phrase(self, key, **kw):
        text = self.data["phrases"][key].format(**kw)
        return text[:1].upper() + text[1:]

    def field(self, name):
        return self.data["fields"].get(name, name.replace("_", " "))

    def cover(self, requirement_id, fallback):
        return self.data["cover_nouns"].get(requirement_id, fallback.lower())

    def event(self, requirement_id):
        return self.data["event_nouns"].get(requirement_id, "check")

    def fields(self, names):
        return join([self.field(n) for n in names])

    def issue_status(self, s):
        return self.data["issue_status"].get(s, s.replace("_", " "))

    def booking_status(self, s):
        return self.data["booking_status"].get(s, s.replace("_", " "))

    def booking_kind(self, s):
        return self.data["booking_kind"].get(s, s.title())

    def delivery(self, status):
        s = (status or "").split(" ")[0].split(":")[0]
        key = "queued" if s.startswith("queued") else s
        return self.data["delivery"].get(key, "not sent yet")

    def visible_fields(self, doc):
        hidden = set(self.data["hidden_document_fields"])
        out = []
        for k, v in doc.items():
            if k in hidden or v in (None, "", []):
                continue
            if isinstance(v, (list, dict)):
                v = f"{len(v)} listed"
            elif k in ("expires", "issued", "signed", "completed_on", "approved_by_main_contractor"):
                v = nice_date(v)
            elif k == "limit_eur":
                v = money(v)
            out.append((self.field(k)[:1].upper() + self.field(k)[1:], str(v)))
        return out


def join(items):
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def money(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1_000_000:
        m = n / 1_000_000
        return f"€{m:.1f}m".replace(".0m", "m")
    return f"€{int(n):,}"


def nice_date(value):
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
