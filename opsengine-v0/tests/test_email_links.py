"""Real email (sending with retries, reply routing), inbound email filing, and approve-by-link."""
import json
import os
import shutil
import smtplib
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from email.message import EmailMessage
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (offline, mock off by default)

from opsengine import connectors, inbound, links, web
from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
LIFFEY = ROOT / "data" / "sample" / "liffey_interiors"
C = "bremore_groundworks_sample"
SECRET = {"OPSENGINE_SECRET": "x" * 40, "PUBLIC_URL": "https://app.example.ie"}


class SendingTests(unittest.TestCase):
    def setUp(self):
        connectors.RETRY_WAITS = (0, 0)

    def test_reply_address_routes_back_to_customer_and_issue(self):
        with mock.patch.dict(os.environ, {"EMAIL_REPLY_TO": "inbox@ops.example.ie"}):
            self.assertEqual(connectors.reply_address((C, "ISS-0005")), f"inbox+{C}.ISS-0005@ops.example.ie")
            msg = connectors.build_message("o@x.ie", "Hi", "Body", ref=(C, "ISS-0005"))
            self.assertEqual(msg["Reply-To"], f"inbox+{C}.ISS-0005@ops.example.ie")

    def test_retries_temporary_failures(self):
        calls = []

        def flaky(msg):
            calls.append(msg)
            if len(calls) < 3:
                raise smtplib.SMTPServerDisconnected("try again")
        self.assertEqual(connectors.send("email", "o@x.ie", "S", "B", transport=flaky), "sent (after 3 tries)")

    def test_refused_address_fails_at_once(self):
        calls = []

        def refuse(msg):
            calls.append(msg)
            raise smtplib.SMTPRecipientsRefused({"o@x.ie": (550, b"no such user")})
        self.assertEqual(connectors.send("email", "o@x.ie", "S", "B", transport=refuse), "failed: SMTPRecipientsRefused")
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_three_tries(self):
        def down(msg):
            raise OSError("network down")
        self.assertTrue(connectors.send("email", "o@x.ie", "S", "B", transport=down).startswith("failed: OSError after 3"))

    def test_resend_payload_and_errors(self):
        sent = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"

        def fake_open(req, timeout=0):
            sent.append((req.full_url, req.headers, json.loads(req.data)))
            return Resp()
        with mock.patch.dict(os.environ, {"EMAIL_MODE": "resend", "RESEND_API_KEY": "re_test", "EMAIL_FROM": "OpsEngine <onboarding@resend.dev>",
                                          "OPSENGINE_ALLOW_SEND_IN_TESTS": "1", "EMAIL_REPLY_TO": "inbox@ops.example.ie"}), \
                mock.patch("urllib.request.urlopen", fake_open):
            self.assertEqual(connectors.send("email", "o@x.ie", "Subject", "Body", ref=(C, "ISS-0001")), "sent")
        url, headers, body = sent[0]
        self.assertEqual(url, "https://api.resend.com/emails")
        self.assertEqual(headers["Authorization"], "Bearer re_test")
        self.assertEqual((body["to"], body["subject"], body["text"].strip()), (["o@x.ie"], "Subject", "Body"))
        self.assertEqual(body["reply_to"], f"inbox+{C}.ISS-0001@ops.example.ie")

        def refused(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 422, "bad", {}, __import__("io").BytesIO(b"invalid to"))
        with mock.patch.dict(os.environ, {"EMAIL_MODE": "resend", "RESEND_API_KEY": "re_test", "OPSENGINE_ALLOW_SEND_IN_TESTS": "1"}), \
                mock.patch("urllib.request.urlopen", refused):
            self.assertTrue(connectors.send("email", "o@x.ie", "S", "B").startswith("failed: resend 422"))

    def test_still_outbox_only_by_default(self):
        self.assertTrue(connectors.send("email", "o@x.ie", "S", "B").startswith("queued_in_outbox"))


class InboundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.customers = {C: BREMORE, "liffey_interiors": LIFFEY}
        self.eng = Engine(BREMORE, state_dir=self.tmp, today=date(2026, 11, 11))
        self.eng.scan()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mail(self, to, sender="someone@example.ie", subject="Re: update", photo=True):
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = sender, to, subject
        m.set_content("Here you go")
        if photo:
            m.add_attachment((ROOT / "tests" / "fixtures" / "photos" / "safe_pass_blurry.png").read_bytes(),
                             maintype="image", subtype="png", filename="card.png")
        return m.as_bytes()

    def test_reply_address_files_against_customer_and_issue(self):
        issue = self.eng.store.issues()[0]["id"]
        r = inbound.process(self.mail(f"inbox+{C}.{issue}@ops.example.ie"), self.customers, state_dir=self.tmp)
        self.assertEqual((r["status"], r["customer"], r["issue"]), ("filed", C, issue))
        self.assertEqual(len(r["photos"]), 1)
        self.assertIn(r["photos"][0]["status"], ("needs_review", "ingested"))   # never guessed: offline goes to a person
        comms = Engine(BREMORE, state_dir=self.tmp).store.comms(issue)
        self.assertTrue(any(c["direction"] == "in" for c in comms))

    def test_owner_email_is_recognised(self):
        owner = json.loads((BREMORE / "company.json").read_text())["owner"]["email"]
        r = inbound.process(self.mail("inbox@ops.example.ie", sender=owner, photo=False), self.customers, state_dir=self.tmp)
        self.assertEqual((r["status"], r["customer"]), ("filed", C))

    def test_unknown_sender_is_kept_for_ops_not_guessed(self):
        r = inbound.process(self.mail("inbox@ops.example.ie", sender="stranger@spam.example"), self.customers, state_dir=self.tmp)
        self.assertEqual(r["status"], "unrouted")
        self.assertTrue(Path(r["saved"]).exists())


@mock.patch.dict(os.environ, SECRET)
class LinkTests(unittest.TestCase):
    def test_token_round_trip_tamper_and_expiry(self):
        t = links.make_token(C, "ISS-0001.2")
        self.assertEqual(links.read_token(t), (C, "ISS-0001.2"))
        self.assertIsNone(links.read_token(t[:-2] + ("aa" if not t.endswith("aa") else "bb")))
        self.assertIsNone(links.read_token(links.make_token(C, "x", now=0)))
        self.assertIsNone(links.read_token("garbage"))

    def test_needs_a_real_secret(self):
        with mock.patch.dict(os.environ, {"OPSENGINE_SECRET": "short"}):
            with self.assertRaises(RuntimeError):
                links.make_token(C, "x")


@mock.patch.dict(os.environ, SECRET)
class LinkPortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.portal = web.Portal(web.SAMPLES, cls.tmp / "web")
        cls.portal.links_dir = cls.tmp / "links"
        web.Handler.portal = cls.portal
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def open(self, path, data=None):
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode() if data else None,
                                     method="POST" if data else "GET")
        try:
            r = urllib.request.urlopen(req)
            return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def waiting_step(self):
        eng = self.portal.engine(C)
        return next(s for s in eng.store.steps(state="awaiting_approval") if s["approval_role"] == "customer")

    def test_link_opens_page_then_approves_once(self):
        st = self.waiting_step()
        tok = links.make_token(C, st["id"])
        status, body = self.open(f"/a/{tok}")
        self.assertEqual(status, 200)
        self.assertIn("Approve", body)
        self.assertEqual(self.portal.engine(C).store.step(st["id"])["state"], "awaiting_approval")   # GET never approves
        status, body = self.open(f"/a/{tok}", {"decision": "approve"})
        self.assertIn("Approved", body)
        self.assertNotEqual(self.portal.engine(C).store.step(st["id"])["state"], "awaiting_approval")
        self.assertEqual(self.open(f"/a/{tok}", {"decision": "approve"})[0], 410)                     # single use
        self.assertIn("via email link", json.dumps(self.portal.engine(C).store.audit_rows(), default=str))

    def test_bad_link(self):
        self.assertEqual(self.open("/a/not-a-token")[0], 404)

    def test_health(self):
        self.assertEqual(self.open("/health"), (200, "ok"))


if __name__ == "__main__":
    unittest.main()
