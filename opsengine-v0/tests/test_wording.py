"""Customer-facing text must never show internal keys or raw values (portal review fix 2)."""
import html
import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import helpers  # noqa: F401

from opsengine import scheduler, web
from opsengine.detect import detect
from opsengine.engine import Engine
from opsengine.knowledge import ROOT, Customer, Knowledge
from opsengine.report import weekly_summary

SAMPLES = [ROOT / "data" / "sample" / "bremore_groundworks", ROOT / "data" / "sample" / "liffey_interiors"]
TODAY = date(2026, 11, 11)
SNAKE = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")
BANNED = ("limit_eur", "required_value", "current_value", "pass_with_defects", "queued_in_outbox", "EMAIL_MODE",
          "None", "{", "}", "awaiting_approval", "request_document", "(SAMPLE main contractor)s")


def problems(text):
    found = SNAKE.findall(text)
    found += [b for b in BANNED if b in text]
    return found


class Wording(unittest.TestCase):
    def assertPlain(self, text, where):
        bad = problems(text)
        self.assertFalse(bad, f"{where}: {bad} in {text[:300]!r}")

    def test_findings_are_plain(self):
        kb = Knowledge.load()
        for folder in SAMPLES:
            c = Customer.load(folder)
            docs = list(c.seed_documents) + [  # the awkward cases too
                {"id": "a", "type": "safety_certification", "holder": "company", "scheme": "ISO 45001", "number": "1", "expires": "2028-01-01"},
                {"id": "b", "type": "public_liability", "holder": "company", "insurer": "X", "policy_number": "P", "limit_eur": "lots", "expires": "2028-01-01"},
                {"id": "c", "type": "safe_pass", "holder": "w01", "number": "1", "expires": "31/12/27"}]
            for f in detect(kb, c, docs, TODAY):
                self.assertPlain(f["detail"], f["key"])

    def test_examples_from_the_review(self):
        kb = Knowledge.load()
        c = Customer.load(SAMPLES[0])
        details = {f["key"]: f["detail"] for f in detect(kb, c, c.seed_documents, TODAY)}
        self.assertEqual(details["written_terms|w16|-|completeness"], "Signed copy missing")
        self.assertEqual(details["trade_references|company|-|completeness"], "Second reference missing")
        self.assertEqual(details["plant_service|a07|-|completeness"], "Last service failed. It needs a new service before it can be used")
        self.assertTrue(details["public_liability|company|-|completeness"].startswith("Your public liability cover is €6.5m, but"))

    def test_messages_summaries_and_report_are_plain(self):
        tmp = Path(tempfile.mkdtemp())
        for folder in SAMPLES:
            e = Engine(folder, state_dir=tmp, today=TODAY)
            e.scan()
            e.advance()
            for q in e.approval_queue():
                self.assertPlain(q["summary"], q["step"])
            for q in e.approval_queue():
                if q["role"] == "customer":
                    e.approve(q["step"], "Owner")
            aid = e.raise_corrective_action("Edge protection missing at stair core", owner="company", severity="critical",
                                            detail="Seen on the site walk.", raised_by="ops")
            e._advance_issue(aid)
            for days in (2, 5, 8):
                scheduler.run_customer(folder, state_dir=tmp, today=TODAY + timedelta(days=days))
            for c in e.store.comms():
                if c["channel"] == "file" or not c["outbox"]:
                    continue  # internal notes for our team
                text = Path(c["outbox"]).read_text(encoding="utf-8")
                subject, _, rest = text.partition("\n\n")
                body = rest.split("\n\n", 1)[1] if rest.startswith("- ") else rest
                self.assertPlain(subject + "\n" + body, Path(c["outbox"]).name)
            self.assertPlain(weekly_summary(Engine(folder, state_dir=tmp, today=TODAY + timedelta(days=8))), "weekly report")
        shutil.rmtree(tmp)

    def test_no_message_repeats_a_sentence(self):
        tmp = Path(tempfile.mkdtemp())
        checked = 0
        for folder in SAMPLES:
            e = Engine(folder, state_dir=tmp, today=TODAY)
            e.scan()
            e.advance()
            for q in e.approval_queue():
                e.approve(q["step"], "Owner" if q["role"] == "customer" else "Reviewer") if q["role"] != "ops" else None
            aid = e.raise_corrective_action("Edge protection missing at stair core", owner="company", severity="high",
                                            detail="Seen on the site walk.", raised_by="ops")
            e._advance_issue(aid)
            for days in (2, 5, 8):
                scheduler.run_customer(folder, state_dir=tmp, today=TODAY + timedelta(days=days))
            for c in e.store.comms():
                if not c["outbox"] or "quote-comparison" in c["outbox"]:
                    continue
                text = Path(c["outbox"]).read_text(encoding="utf-8")
                body = text.split("\n\n", 2)[-1]
                sentences = [re.sub(r"\s+", " ", x).strip().lower() for x in re.split(r"(?<=[.!?])\s+|\n+", body)]
                sentences = [x.rstrip(".") for x in sentences if len(x) >= 15]
                for n, a in enumerate(sentences):
                    for m, b in enumerate(sentences):
                        if n != m:
                            self.assertFalse(a == b or (len(a) >= 25 and a in b),
                                             f"{Path(c['outbox']).name} repeats itself: {a!r} / {b!r}")
                checked += 1
        self.assertGreater(checked, 100)
        shutil.rmtree(tmp)

    def test_customer_pages_are_plain(self):
        from helpers import DEMO, Client, start_portal
        tmp = Path(tempfile.mkdtemp())
        base, portal, httpd = start_portal(tmp)
        try:
            for cid, who in (("bremore_groundworks_sample", "customer"), ("liffey_interiors", "liffey")):
                client = Client(base)
                client.login(DEMO[who])

                def visible(path):
                    raw = client.get(path)
                    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S)
                    links = re.findall(r'href="(/c/[^"]+)"', raw)
                    return html.unescape(re.sub(r"<[^>]+>", " ", raw)), links

                seen = set()
                pages = [f"/c/{cid}/{t}" for t in ("home", "issues", "issues?status=all", "people", "subcontractors",
                                                     "equipment", "documents", "actions", "bookings", "messages", "report")]
                while pages:
                    path = pages.pop()
                    if path in seen or len(seen) > 400:
                        continue
                    seen.add(path)
                    text, links = visible(path)
                    self.assertPlain(text, path)
                    pages += [html.unescape(l) for l in links if ("/issue/" in l or "/message?" in l) and l not in seen]
                self.assertGreater(len(seen), 30)
        finally:
            httpd.shutdown()
            httpd.server_close()
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
