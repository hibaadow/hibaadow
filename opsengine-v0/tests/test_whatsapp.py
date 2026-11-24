"""WhatsApp: sending inside / outside the 24-hour window, and photos arriving through the webhook."""
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (offline, mock off by default)

from opsengine import connectors, web, whatsapp
from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
C = "bremore_groundworks_sample"
PHOTO = ROOT / "tests" / "fixtures" / "photos" / "safe_pass_blurry.png"
ENV = {"WHATSAPP_MODE": "cloud", "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "111",
       "WHATSAPP_APP_SECRET": "s3cret", "WHATSAPP_VERIFY_TOKEN": "verify-me"}


def webhook(num, **msg):
    return {"entry": [{"changes": [{"value": {"messages": [{"from": num, "id": "wamid.1", **msg}]}}]}]}


@mock.patch.dict(os.environ, ENV)
class SendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.posts = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, path, payload):
        self.posts.append((path, payload))
        return {"messages": [{"id": "wamid.x"}]}

    def test_numbers_are_normalised(self):
        self.assertEqual(whatsapp.number("+353 87 000 0201"), "353870000201")
        self.assertEqual(whatsapp.number("087 000 0201"), "353870000201")
        self.assertEqual(whatsapp.number("00353870000201"), "353870000201")

    def test_outside_window_sends_template_and_holds_full_message(self):
        status = whatsapp.send("+353 87 000 0202", "Safe Pass renewal", "Full message", self.tmp, post=self.post)
        self.assertTrue(status.startswith("sent (template"))
        self.assertEqual(self.posts[0][0], "111/messages")
        self.assertEqual(self.posts[0][1]["type"], "template")
        self.assertEqual(self.posts[0][1]["template"]["components"][0]["parameters"][0]["text"], "Safe Pass renewal")
        self.assertEqual(whatsapp.Window(self.tmp).take("353870000202"), ["Full message"])

    def test_inside_window_sends_text(self):
        whatsapp.Window(self.tmp).seen("353870000202")
        self.assertEqual(whatsapp.send("+353 87 000 0202", "S", "Hello", self.tmp, post=self.post), "sent")
        self.assertEqual(self.posts[0][1]["text"]["body"], "Hello")

    def test_window_expires_after_24_hours(self):
        win = whatsapp.Window(self.tmp)
        win.seen("353870000202", datetime.now(timezone.utc) - timedelta(hours=25))
        self.assertFalse(win.is_open("353870000202"))

    def test_refused_message_is_a_failure_not_a_crash(self):
        def refuse(path, payload):
            raise whatsapp.PermanentFailure("whatsapp 400: bad number")
        self.assertTrue(whatsapp.send("+353 87 000 0202", "S", "B", self.tmp, post=refuse).startswith("failed"))

    def test_connectors_route_whatsapp(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_MODE": "off"}):
            self.assertIn("queued_in_outbox", connectors.send("whatsapp", "+353870000202", "S", "B"))
        self.assertTrue(connectors.send("whatsapp", "+353870000202", "S", "B", transport=self.post,
                                        state_dir=self.tmp).startswith("sent"))


@mock.patch.dict(os.environ, ENV)
class ReceiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.customers = {C: BREMORE}
        self.eng = Engine(BREMORE, state_dir=self.tmp, today=date(2026, 11, 11))
        self.eng.scan()
        self.posts = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fetch(self, media_id):
        return PHOTO.read_bytes(), "image/png"

    def post(self, path, payload):
        self.posts.append(payload)

    def test_photo_from_worker_goes_to_photo_reader(self):
        r = whatsapp.handle(webhook("353870000202", type="image", image={"id": "m1", "mime_type": "image/png"}),
                            self.customers, self.tmp, fetch=self.fetch, post=self.post)
        self.assertEqual((r[0]["status"], r[0]["customer"], r[0]["holder"]), ("filed", C, "w02"))
        self.assertIn(r[0]["photo"], ("needs_review", "ingested"))      # offline: never guessed
        comms = Engine(BREMORE, state_dir=self.tmp).store.comms()
        self.assertTrue(any(c["direction"] == "in" and c["channel"] == "whatsapp" for c in comms))

    def test_photo_gets_an_honest_thank_you(self):
        whatsapp.handle(webhook("353870000202", type="image", image={"id": "m1", "mime_type": "image/png"}),
                        self.customers, self.tmp, fetch=self.fetch, post=self.post)
        reply = self.posts[-1]["text"]["body"]
        self.assertIn("Thanks Tomasz, got it", reply)
        self.assertIn("We'll check it", reply)            # offline: not accepted yet, so it doesn't say it was

    def test_reply_releases_held_message(self):
        whatsapp.Window(self.tmp).hold("353870000202", "The full chase message")
        whatsapp.handle(webhook("353870000202", type="text", text={"body": "ok"}), self.customers, self.tmp,
                        post=self.post)
        self.assertEqual(self.posts[0]["text"]["body"], "The full chase message")
        self.assertEqual(whatsapp.Window(self.tmp).take("353870000202"), [])

    def test_unknown_number_kept_for_ops(self):
        r = whatsapp.handle(webhook("447700900000", type="text", text={"body": "hi"}), self.customers, self.tmp,
                            post=self.post)
        self.assertEqual(r[0]["status"], "unrouted")
        self.assertTrue(any((self.tmp / "whatsapp_unrouted").iterdir()))

    def test_failed_download_still_reaches_a_person(self):
        def broken(media_id):
            raise OSError("network")
        r = whatsapp.handle(webhook("353870000202", type="image", image={"id": "m2"}), self.customers, self.tmp,
                            fetch=broken, post=self.post)
        self.assertEqual(r[0]["photo"], "needs_review")


@mock.patch.dict(os.environ, ENV)
class WebhookPortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.portal = web.Portal(web.SAMPLES, cls.tmp / "web")
        web.Handler.portal = cls.portal
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, path, data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {},
                                     method="POST" if data is not None else "GET")
        try:
            r = urllib.request.urlopen(req)
            return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_verification_handshake(self):
        ok = self.call("/whatsapp?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=12345")
        self.assertEqual(ok, (200, "12345"))
        self.assertEqual(self.call("/whatsapp?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=1")[0], 403)

    def test_unsigned_post_is_refused(self):
        body = json.dumps(webhook("353870000202", type="text", text={"body": "hi"})).encode()
        self.assertEqual(self.call("/whatsapp", body, {"X-Hub-Signature-256": "sha256=bad"})[0], 403)

    def test_signed_post_is_filed(self):
        body = json.dumps(webhook("353870000202", type="text", text={"body": "hello from site"})).encode()
        sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        with mock.patch.object(whatsapp, "send", return_value="sent"):
            self.assertEqual(self.call("/whatsapp", body, {"X-Hub-Signature-256": sig})[0], 200)
        comms = self.portal.engine(C).store.comms()
        self.assertTrue(any(c["subject"] == "hello from site" for c in comms))


if __name__ == "__main__":
    unittest.main()
