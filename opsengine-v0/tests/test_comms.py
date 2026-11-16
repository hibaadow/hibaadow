"""Phase 3: approve by link, delivery retries and reports, inbound email, WhatsApp. All offline."""
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from helpers import Client, start_portal

from opsengine import approval_links, delivery, inbound, scheduler, whatsapp
from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
PHOTO = BREMORE / "incoming" / "photos" / "safe_pass_andriy_kovalenko.png"
TODAY = date(2026, 11, 11)
OWNER = "grainne@bremore-groundworks.example.ie"
SEND = {"EMAIL_MODE": "smtp", "SMTP_HOST": "smtp.example.ie", "EMAIL_FROM": "ops@opsengine.example.ie",
        "OPSENGINE_ALLOW_SEND_IN_TESTS": "true", "OPSENGINE_PUBLIC_URL": "https://portal.example.ie"}
LATER = datetime.now(timezone.utc) + timedelta(days=2)


class FakeSMTP:
    sent, fail = [], 0

    def __init__(self, *a, **k):
        if FakeSMTP.fail:
            FakeSMTP.fail -= 1
            raise OSError("connection refused")

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self): pass
    def login(self, *a): pass
    def send_message(self, msg): FakeSMTP.sent.append(msg)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        FakeSMTP.sent, FakeSMTP.fail = [], 0
        self.patches = [mock.patch("smtplib.SMTP", FakeSMTP)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def engine(self, folder=BREMORE):
        e = Engine(folder, state_dir=self.tmp / "state", today=TODAY)
        e.scan()
        e.advance()
        return e

    def customer_step(self, e):
        return next(s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "customer")


# ---------------- approve by link ----------------
class ApproveByLink(Base):
    def test_only_customer_approvals_can_be_given_by_link(self):
        e = self.engine()
        with self.assertRaises(PermissionError):
            e.raise_corrective_action("Fix guard rail", severity="critical", raised_by="test")
            for issue in e.store.issues("open"):
                e._advance_issue(issue["id"])
            reviewer = next(s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] != "customer")
            approval_links.issue_link(e, reviewer["id"])

    def test_link_is_single_use_named_and_audited(self):
        e = self.engine()
        step = self.customer_step(e)
        with mock.patch.dict(os.environ, SEND):
            link = approval_links.issue_link(e, step["id"])
        self.assertTrue(link.startswith("https://portal.example.ie/a/"))
        secret = link.rsplit("/", 1)[1]
        approval_links.check(e, secret)  # looking changes nothing
        self.assertEqual(e.store.step(step["id"])["state"], "awaiting_approval")
        approval_links.use(e, secret, "approved")
        s = e.store.step(step["id"])
        self.assertEqual(s["approved_by"], f"Gráinne Murphy <{OWNER}> (email link)")
        with self.assertRaises(ValueError):
            approval_links.use(e, secret, "approved")
        events = [a["event"] for a in e.store.audit_rows()]
        self.assertTrue({"approval_link_issued", "approval_link_used", "approval_link_refused", "approved"} <= set(events))

    def test_expired_or_already_handled_links_do_nothing(self):
        e = self.engine()
        step = self.customer_step(e)
        old = approval_links.issue_link(e, step["id"], hours=-1).rsplit("/", 1)[1]
        with self.assertRaises(ValueError):
            approval_links.use(e, old, "approved")
        fresh = approval_links.issue_link(e, step["id"]).rsplit("/", 1)[1]
        e.approve(step["id"], "Someone in the portal")
        with self.assertRaises(ValueError):
            approval_links.use(e, fresh, "approved")
        with self.assertRaises(ValueError):
            approval_links.use(e, "0" * 64, "approved")

    def test_daily_email_lists_new_approvals_with_links_only_when_email_is_on(self):
        with mock.patch.dict(os.environ, {"OPSENGINE_OFFLINE": "1"}):
            scheduler.run_customer(BREMORE, state_dir=self.tmp / "a", today=TODAY)
        outbox = self.tmp / "a" / "bremore_groundworks_sample" / "outbox"
        first = [f for f in outbox.iterdir() if "approval-request" in f.name]
        self.assertEqual(len(first), 1)
        self.assertIn("Approve or decline in the portal", first[0].read_text())
        scheduler.run_customer(BREMORE, state_dir=self.tmp / "a", today=TODAY)
        self.assertEqual(len([f for f in outbox.iterdir() if "approval-request" in f.name]), 1)  # once, not every day

        with mock.patch.dict(os.environ, SEND):
            scheduler.run_customer(BREMORE, state_dir=self.tmp / "b", today=TODAY)
        sent = next(m for m in FakeSMTP.sent if "need your approval" in m["Subject"])
        self.assertEqual(sent["To"], OWNER)
        body = sent.get_content()
        self.assertGreater(body.count("https://portal.example.ie/a/"), 5)
        saved = next(f for f in (self.tmp / "b" / "bremore_groundworks_sample" / "outbox").iterdir() if "approval-request" in f.name)
        self.assertNotRegex(saved.read_text(), r"/a/[0-9a-f]{64}")  # staff can read the saved copy, so no live links in it

    def test_link_page_in_the_portal(self):
        base, portal, httpd = start_portal(self.tmp / "p", demo=True)
        try:
            e = portal.engine("bremore_groundworks_sample")
            step = self.customer_step(e)
            secret = approval_links.issue_link(e, step["id"]).rsplit("/", 1)[1]
            c = Client(base)  # not signed in
            page = c.get(f"/a/{secret}")
            self.assertIn("Your approval is needed", page)
            self.assertEqual(portal.engine("bremore_groundworks_sample").store.step(step["id"])["state"], "awaiting_approval")
            self.assertEqual(c.post(f"/a/{secret}", {"decision": "approved"}, csrf=False)[0], 200)
            self.assertEqual(portal.engine("bremore_groundworks_sample").store.step(step["id"])["approved_by"],
                             f"Gráinne Murphy <{OWNER}> (email link)")
            with self.assertRaises(urllib.error.HTTPError) as err:
                c.get(f"/a/{secret}")
            self.assertEqual(err.exception.code, 410)
        finally:
            httpd.shutdown()
            httpd.server_close()


# ---------------- delivery: retries and reports ----------------
class Delivery(Base):
    def test_failed_email_is_retried_then_sent(self):
        with mock.patch.dict(os.environ, SEND):
            FakeSMTP.fail = 100
            e = self.engine()
            retrying = e.store.deliveries("retrying")
            self.assertTrue(retrying)
            self.assertTrue(any("will retry" in c["status"] for c in e.store.comms()))
            FakeSMTP.fail = 0
            self.assertEqual(delivery.retry_due(e.store, e.customer), [])  # not due yet
            events = delivery.retry_due(e.store, e.customer, now=LATER)
        self.assertTrue(all("sent on attempt 2" in what for _, what in events))
        self.assertEqual(e.store.deliveries("retrying"), [])
        self.assertTrue(all(d["body"] == "" for d in e.store.deliveries("sent")))  # bodies aren't kept once sent

    def test_gives_up_after_five_attempts_and_escalates(self):
        with mock.patch.dict(os.environ, SEND):
            FakeSMTP.fail = 10_000
            e = self.engine()
            d = e.store.deliveries("retrying")[0]
            for n in range(delivery.MAX_ATTEMPTS):
                delivery.retry_due(e.store, e.customer, now=LATER + timedelta(days=n))
        self.assertEqual(e.store.deliveries()[d["id"] - 1]["status"], "failed")
        self.assertEqual(e.store.issue(d["issue_id"])["status"], "escalated")
        self.assertIn("delivery_failed", [a["event"] for a in e.store.audit_rows()])

    def test_missing_address_escalates_at_once(self):
        folder = self.tmp / "c"
        shutil.copytree(BREMORE, folder)
        company = json.loads((folder / "company.json").read_text())
        company["broker"]["email"] = ""
        (folder / "company.json").write_text(json.dumps(company))
        with mock.patch.dict(os.environ, SEND):
            e = self.engine(folder)
        failed = [d for d in e.store.deliveries("failed") if d["to_name"].startswith("Sample Insurance")]
        self.assertTrue(failed)
        self.assertEqual(e.store.issue(failed[0]["issue_id"])["status"], "escalated")

    def test_email_carries_issue_reference_and_message_id(self):
        with mock.patch.dict(os.environ, SEND):
            self.engine()
        m = FakeSMTP.sent[0]
        self.assertRegex(m["Subject"], r"\[ISS-\d{4}\]")
        self.assertTrue(m["Message-ID"].startswith("<bremore_groundworks_sample."))

    def test_signed_bounce_report_escalates(self):
        secret = "s" * 40
        base, portal, httpd = start_portal(self.tmp / "p", demo=True)
        try:
            with mock.patch.dict(os.environ, {**SEND, "OPSENGINE_WEBHOOK_SECRET": secret}):
                e = portal.engine("bremore_groundworks_sample")
                delivery.dispatch(e.store, e.customer, {"name": "Broker", "channel": "email", "address": "b@x.example.ie"},
                                  "Your quote", "Body", "ISS-0001", "ISS-0001.2")
                d = e.store.deliveries("sent")[-1]
                body = json.dumps([{"message_id": d["message_id"], "event": "bounced", "detail": "mailbox full"}]).encode()

                def post(sig):
                    req = urllib.request.Request(base + "/hooks/email", data=body, method="POST",
                                                 headers={"X-OpsEngine-Signature": sig, "Content-Type": "application/json"})
                    try:
                        with urllib.request.urlopen(req) as r:
                            return r.status, r.read().decode()
                    except urllib.error.HTTPError as err:
                        return err.code, ""
                self.assertEqual(post("wrong")[0], 403)
                self.assertEqual(post(hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()), (200, "ok 1"))
            e = portal.engine("bremore_groundworks_sample")
            self.assertEqual(e.store.issue(d["issue_id"])["status"], "escalated")
            self.assertEqual(e.store.deliveries(message_id=d["message_id"])[0]["status"], "bounced")
        finally:
            httpd.shutdown()
            httpd.server_close()


# ---------------- inbound email ----------------
def eml(sender, subject, to="docs@opsengine.example.ie", auth="mx.example.ie; dmarc=pass", attach=PHOTO):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, to, subject
    if auth:
        m["Authentication-Results"] = auth
    m.set_content("Here it is.")
    if attach:
        m.add_attachment(Path(attach).read_bytes(), maintype="image", subtype="png", filename=Path(attach).name)
    return m.as_bytes()


class InboundEmail(Base):
    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {"USE_MOCK_AI": "true"})  # replays the recorded read of the sample photo
        self.env.start()
        self.customers = {"bremore_groundworks_sample": BREMORE}
        self.engine()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def handle(self, raw):
        return inbound.handle_email(self.customers, self.tmp / "state", raw, today=TODAY)

    def test_reply_with_issue_reference_is_read_and_closes_the_issue(self):
        r = self.handle(eml(OWNER, "Re: Safe Pass for Andriy [ISS-0007]"))
        self.assertEqual((r["customer"], r["holder"], r["issue"]), ("bremore_groundworks_sample", "w16", "ISS-0007"))
        self.assertEqual(r["results"][0]["status"], "ingested")
        e = Engine(BREMORE, state_dir=self.tmp / "state", today=TODAY)
        self.assertEqual(e.store.issue("ISS-0007")["status"], "resolved")
        self.assertTrue(any(c["direction"] == "in" and c["channel"] == "email" for c in e.store.comms()))

    def test_unverified_sender_always_goes_to_a_person(self):
        r = self.handle(eml(OWNER, "Re: [ISS-0007]", auth=None))
        self.assertEqual(r["results"][0]["status"], "needs_review")
        rev = Engine(BREMORE, state_dir=self.tmp / "state", today=TODAY).review_queue()[-1]
        self.assertTrue(any("couldn't be verified" in r for r in rev["reasons"]))

    def test_strangers_and_unreferenced_mail_are_not_guessed(self):
        self.assertEqual(self.handle(eml("someone@elsewhere.example.com", "Safe Pass"))["status"], "unmatched")
        self.assertTrue(any((self.tmp / "state" / "inbound-unmatched").glob("*.eml")))
        r = self.handle(eml(OWNER, "A document for you"))  # owner, but whose is it?
        self.assertEqual(r["results"][0]["status"], "needs_review")
        r = self.handle(eml("stranger@elsewhere.example.com", "x [ISS-0007]", to="docs+bremore_groundworks_sample@opsengine.example.ie"))
        self.assertEqual(r["status"], "unmatched")  # the customer address alone doesn't make a sender trusted

    def test_maildrop_folder(self):
        drop = self.tmp / "drop"
        drop.mkdir()
        (drop / "1.eml").write_bytes(eml(OWNER, "Re: [ISS-0007]"))
        out = inbound.process_maildrop(self.customers, self.tmp / "state", drop, today=TODAY)
        self.assertEqual(out[0]["results"][0]["status"], "ingested")
        self.assertFalse(list(drop.glob("*.eml")))
        self.assertTrue((drop / "processed" / "1.eml").exists())


# ---------------- WhatsApp ----------------
W16 = "353870000216"
CLOUD = {"WHATSAPP_MODE": "cloud", "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "123",
         "WHATSAPP_APP_SECRET": "a" * 32, "OPSENGINE_ALLOW_SEND_IN_TESTS": "true", "USE_MOCK_AI": "true"}


class FakeGraph:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, data=None):
        self.calls.append((method, url, json.loads(data) if data else None))
        if url.endswith("/messages"):
            return 200, json.dumps({"messages": [{"id": f"wamid.{len(self.calls)}"}]}).encode()
        if url == "https://lookaside.example/media-1":
            return 200, PHOTO.read_bytes()
        if url.endswith("/media-1"):
            return 200, json.dumps({"url": "https://lookaside.example/media-1", "mime_type": "image/png"}).encode()
        return 404, b"{}"


def inbound_payload(kind="image", text=""):
    msg = {"from": W16, "id": "wamid.in", "type": kind}
    msg.update({"image": {"id": "media-1", "mime_type": "image/png"}} if kind == "image" else {"text": {"body": text}})
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


class WhatsApp(Base):
    def setUp(self):
        super().setUp()
        self.graph = FakeGraph()
        self.folder = self.tmp / "c"
        shutil.copytree(BREMORE, self.folder)
        workers = json.loads((self.folder / "workers.json").read_text())
        for w in workers:
            if w["name"] != "Thiago Almeida":
                w["whatsapp_opt_in"] = "2026-10-01"
        (self.folder / "workers.json").write_text(json.dumps(workers))
        self.env = mock.patch.dict(os.environ, CLOUD)
        self.env.start()
        self.patches.append(mock.patch.object(whatsapp, "_urllib", self.graph))
        self.patches[-1].start()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def test_template_first_then_full_message_when_they_reply(self):
        e = self.engine(self.folder)
        waiting = [d for d in e.store.deliveries("awaiting_reply") if whatsapp.digits(d["address"]) == W16]
        self.assertTrue(waiting)
        self.assertTrue(all(c[2]["type"] == "template" for c in self.graph.calls))
        inbound.handle_whatsapp({"bremore_groundworks_sample": self.folder}, self.tmp / "state", inbound_payload("text", "hi"),
                                today=TODAY, transport=self.graph)
        e = Engine(self.folder, state_dir=self.tmp / "state", today=TODAY)
        self.assertFalse([d for d in e.store.deliveries("awaiting_reply") if whatsapp.digits(d["address"]) == W16])
        self.assertEqual(self.graph.calls[-1][2]["type"], "text")
        self.assertTrue(delivery.in_window(e.store, W16))

    def test_no_opt_in_means_no_whatsapp(self):
        e = self.engine(self.folder)
        w15 = [c for c in e.store.comms() if c["to_name"] == "Thiago Almeida"]
        self.assertTrue(w15 and all(c["status"].startswith("not sent: no WhatsApp opt-in") for c in w15))
        self.assertEqual(e.store.issue(w15[0]["issue_id"])["status"], "escalated")

    def test_stop_is_respected(self):
        customers = {"bremore_groundworks_sample": self.folder}
        Engine(self.folder, state_dir=self.tmp / "state", today=TODAY)
        inbound.handle_whatsapp(customers, self.tmp / "state", inbound_payload("text", "STOP"), today=TODAY, transport=self.graph)
        before = len(self.graph.calls)
        e = self.engine(self.folder)
        to_w16 = [c for c in self.graph.calls[before:] if c[2] and c[2].get("to") == W16]
        self.assertEqual(to_w16, [])
        self.assertTrue(any(c["status"].startswith("not sent: opted out") for c in e.store.comms()))

    def test_photo_from_a_worker_is_read(self):
        self.engine(self.folder)
        out = inbound.handle_whatsapp({"bremore_groundworks_sample": self.folder}, self.tmp / "state", inbound_payload(),
                                      today=TODAY, transport=self.graph)
        self.assertEqual(out[0]["status"], "ingested")
        e = Engine(self.folder, state_dir=self.tmp / "state", today=TODAY)
        self.assertEqual(e.store.issue("ISS-0007")["status"], "resolved")

    def test_webhook_signature_and_subscription_check(self):
        raw = json.dumps(inbound_payload("text", "hi")).encode()
        self.assertFalse(whatsapp.verify_signature(raw, "sha256=bad"))
        self.assertTrue(whatsapp.verify_signature(raw, "sha256=" + hmac.new(b"a" * 32, raw, hashlib.sha256).hexdigest()))
        base, portal, httpd = start_portal(self.tmp / "p", demo=True)
        try:
            with mock.patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "v" * 20}):
                with urllib.request.urlopen(base + f"/hooks/whatsapp?hub.mode=subscribe&hub.verify_token={'v' * 20}&hub.challenge=42") as r:
                    self.assertEqual(r.read(), b"42")
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(base + "/hooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42")
            req = urllib.request.Request(base + "/hooks/whatsapp", data=raw, method="POST", headers={"X-Hub-Signature-256": "sha256=bad"})
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req)
            self.assertEqual(err.exception.code, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
