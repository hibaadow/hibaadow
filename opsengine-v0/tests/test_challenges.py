"""Workers and customers can challenge a compliance status; a person always decides (GDPR review Q7)."""
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from helpers import DEMO, Client, start_portal

from opsengine import challenges, inbound, scheduler, whatsapp
from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
TODAY = date(2026, 11, 11)
B = "bremore_groundworks_sample"
OPS = "Ops (SAMPLE) <ops@opsengine.example.ie>"


class Challenges(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(BREMORE, state_dir=self.tmp, today=TODAY)
        self.e.scan()
        self.e.advance()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_challenge_keeps_the_issue_visible_and_pauses_reminders(self):
        ch = challenges.raise_challenge(self.e, "ISS-0007", "Gráinne Murphy", "His Safe Pass was renewed last week")
        self.assertEqual(self.e.store.issue("ISS-0007")["status"] in ("open", "in_progress", "escalated"), True)
        self.assertEqual(challenges.get(self.e.store, ch)["status"], "open")
        with self.assertRaises(ValueError):
            challenges.raise_challenge(self.e, "ISS-0007", "x", "again please")  # one at a time
        later = Engine(BREMORE, state_dir=self.tmp, today=TODAY + timedelta(days=3))
        chased = scheduler.chase_stalled(later)
        self.assertFalse(any(ref.startswith("ISS-0007.") for ref, _ in chased))

    def test_not_upheld_is_explained_to_the_customer(self):
        ch = challenges.raise_challenge(self.e, "ISS-0007", "Gráinne Murphy", "His Safe Pass was renewed last week")
        with self.assertRaises(ValueError):
            challenges.decide(self.e, ch, OPS, False, "")  # a reason is required
        challenges.decide(self.e, ch, OPS, False, "SOLAS shows the renewal course is booked, not completed")
        self.assertEqual(challenges.get(self.e.store, ch)["status"], "not_upheld")
        msg = next(f for f in self.e.outbox.iterdir() if f.name == f"{ch}-outcome-customer.md").read_text()
        self.assertIn("SOLAS shows the renewal course is booked", msg)
        self.assertNotEqual(self.e.store.issue("ISS-0007")["status"], "resolved")
        self.assertTrue({"challenge_raised", "challenge_decided"} <= {a["event"] for a in self.e.store.audit_rows()})

    def test_upheld_needs_a_record_that_passes_the_checks(self):
        ch = challenges.raise_challenge(self.e, "ISS-0007", "Gráinne Murphy", "His Safe Pass was renewed last week")
        with self.assertRaises(ValueError):
            challenges.decide(self.e, ch, OPS, True, "checked the card")  # no record
        bad = {"id": "d-sp-w16-ch", "type": "safe_pass", "holder": "w16", "number": "SP-1", "expires": "not a date"}
        with self.assertRaises(ValueError):
            challenges.decide(self.e, ch, OPS, True, "checked the card", bad)
        self.assertEqual(challenges.get(self.e.store, ch)["status"], "open")
        good = {"id": "d-sp-w16-ch2", "type": "safe_pass", "holder": "w16", "number": "SP-SAMPLE-70016", "expires": "2030-11-09"}
        challenges.decide(self.e, ch, OPS, True, "saw the new card on video call", good)
        self.assertEqual(self.e.store.issue("ISS-0007")["status"], "resolved")

    def test_overdue_challenges_go_to_ops_once(self):
        ch = challenges.raise_challenge(self.e, "ISS-0007", "Gráinne Murphy", "His Safe Pass was renewed last week")
        late = Engine(BREMORE, state_dir=self.tmp, today=TODAY + timedelta(days=6))
        self.assertEqual(challenges.overdue(late), [ch])
        self.assertEqual(challenges.overdue(late), [])

    def test_worker_can_challenge_on_whatsapp(self):
        env = {"WHATSAPP_MODE": "cloud", "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1", "OPSENGINE_ALLOW_SEND_IN_TESTS": "true"}
        sent = []
        with mock.patch.dict(os.environ, env), mock.patch.object(whatsapp, "_urllib", lambda *a, **k: sent.append(a) or (200, b'{"messages":[{"id":"x"}]}')):
            payload = {"entry": [{"changes": [{"value": {"messages": [
                {"from": "353870000201", "id": "m1", "type": "text", "text": {"body": "WRONG I finished the course on Monday"}}]}}]}]}
            out = inbound.handle_whatsapp({B: BREMORE}, self.tmp, payload, today=TODAY)
        self.assertEqual(out[0]["status"], "challenge_raised")
        ch = challenges.get(Engine(BREMORE, state_dir=self.tmp, today=TODAY).store, out[0]["challenge"])
        self.assertEqual((ch["holder"], ch["channel"]), ("w01", "whatsapp"))


class Portal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base, self.portal, self.httpd = start_portal(self.tmp, demo=True)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp)

    def test_customer_challenges_and_only_ops_decides(self):
        cust = Client(self.base)
        cust.login(DEMO["customer"])
        page = cust.get(f"/c/{B}/issue/ISS-0007")
        self.assertIn("Challenge it", page)
        status, loc = cust.post(f"/c/{B}/challenge", {"issue": "ISS-0007", "reason": "Renewed last week, card attached by email"})
        self.assertIn("A person will check it", cust.flash(loc))
        self.assertIn("Challenged", cust.get(f"/c/{B}/issues"))
        ch = challenges.listing(self.portal.engine(B).store, "open")[0]["id"]
        self.assertIn("isn't available", cust.flash(cust.post(f"/c/{B}/decide-challenge", {"id": ch, "decision": "not_upheld", "note": "no"})[1]))
        ops = Client(self.base)
        ops.login(DEMO["ops"])
        self.assertIn("Challenges to decide", ops.get(f"/c/{B}/ops"))
        ops.post(f"/c/{B}/decide-challenge", {"id": ch, "decision": "not_upheld", "note": "No renewal on the SOLAS register yet"})
        self.assertEqual(challenges.get(self.portal.engine(B).store, ch)["status"], "not_upheld")
        self.assertIn("not upheld", cust.get(f"/c/{B}/issue/ISS-0007"))


if __name__ == "__main__":
    unittest.main()
