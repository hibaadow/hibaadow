import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ["OPSENGINE_OFFLINE"] = "1"  # tests never call the Claude API

from opsengine.detect import detect
from opsengine.engine import Engine
from opsengine.knowledge import ROOT, Customer, Knowledge

SAMPLE = ROOT / "data" / "sample" / "liffey_interiors"
TODAY = date(2026, 11, 11)


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.kb = Knowledge.load()
        self.customer = Customer.load(SAMPLE)
        self.findings = {f["key"]: f for f in detect(self.kb, self.customer, self.customer.seed_documents, TODAY)}

    def test_expected_findings(self):
        kinds = {(f["requirement"], f["holder"], f["kind"]) for f in self.findings.values()}
        self.assertIn(("safe_pass", "w02", "expired"), kinds)
        self.assertIn(("safe_pass", "w03", "expiring"), kinds)
        self.assertIn(("safe_pass", "w06", "missing"), kinds)
        self.assertIn(("safety_statement", "company", "expired"), kinds)
        self.assertIn(("site_induction", "w06", "missing"), kinds)
        self.assertIn(("written_terms", "w05", "incomplete"), kinds)
        self.assertEqual(len(self.findings), 10)

    def test_main_contractor_minimum_applies_only_to_that_contractor(self):
        pl = [f for f in self.findings.values() if f["requirement"] == "public_liability" and f["kind"] == "incomplete"]
        self.assertEqual(len(pl), 1)
        self.assertEqual(pl[0]["context"], "harbour_construction")
        self.assertEqual(pl[0]["required_value"], 10000000)

    def test_main_contractor_extra_requirement(self):
        mh = [f for f in self.findings.values() if f["requirement"] == "manual_handling"]
        # Northgate requires manual handling; only Piotr (on its site) is missing it.
        self.assertEqual([f["holder"] for f in mh], ["w04"])

    def test_blocking_items_are_critical(self):
        self.assertEqual(self.findings["safe_pass|w02|-|validity"]["severity"], "critical")
        self.assertEqual(self.findings["written_terms|w05|-|completeness"]["severity"], "medium")


class EngineLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(SAMPLE, state_dir=self.tmp, today=TODAY)
        self.e.scan()
        self.e.advance()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def issue_for(self, req, holder):
        return next(i for i in self.e.store.issues() if i["requirement"] == req and i["holder"] == holder)

    def test_money_needs_approval(self):
        iss = self.issue_for("safe_pass", "w02")
        states = {s["action"]: s["state"] for s in self.e.store.steps(iss["id"])}
        self.assertEqual(states["message_worker"], "done")
        self.assertEqual(states["find_provider"], "done")
        self.assertEqual(states["book_service"], "awaiting_approval")

    def test_safety_documents_need_reviewer(self):
        iss = self.issue_for("safety_statement", "company")
        step = next(s for s in self.e.store.steps(iss["id"]) if s["action"] == "request_signature")
        self.assertEqual((step["state"], step["approval_role"]), ("awaiting_approval", "safety_reviewer"))

    def test_full_resolution_with_proof(self):
        iss = self.issue_for("safe_pass", "w02")
        self.e.approve(f"{iss['id']}.3", by="Owner")
        doc = json.loads((SAMPLE / "incoming" / "new_safe_pass_w02.json").read_text())
        self.e.ingest(doc)
        done = self.e.store.issue(iss["id"])
        self.assertEqual(done["status"], "resolved")
        self.assertEqual(done["proof"], doc["id"])
        # rescan must not reopen it
        self.e.scan()
        self.assertIsNone(self.e.store.open_issue_by_key(iss["key"]))

    def test_bad_proof_is_rejected_and_requested_again(self):
        iss = self.issue_for("safe_pass", "w03")
        self.e.approve(f"{iss['id']}.3", by="Owner")
        self.e.ingest(json.loads((SAMPLE / "incoming" / "wrong_card_w03.json").read_text()))
        self.assertNotEqual(self.e.store.issue(iss["id"])["status"], "resolved")
        request = self.e.store.step(f"{iss['id']}.4")
        self.assertEqual(request["state"], "waiting")
        resend = (self.e.outbox / f"{iss['id']}.4-message.md").read_text()
        self.assertIn("could not accept", resend)

    def test_early_proof_skips_remaining_steps(self):
        iss = self.issue_for("safe_pass", "w02")  # booking still awaiting approval
        self.e.ingest(json.loads((SAMPLE / "incoming" / "new_safe_pass_w02.json").read_text()))
        self.assertEqual(self.e.store.issue(iss["id"])["status"], "resolved")
        self.assertEqual(self.e.store.step(f"{iss['id']}.3")["state"], "skipped")

    def test_rejection_escalates(self):
        iss = self.issue_for("safe_pass", "w06")
        self.e.reject(f"{iss['id']}.3", by="Owner", reason="He is leaving the company")
        self.assertEqual(self.e.store.issue(iss["id"])["status"], "escalated")

    def test_audit_chain(self):
        ok, _ = self.e.store.verify_audit()
        self.assertTrue(ok)
        self.e.store.db.execute("UPDATE audit SET actor='tampered' WHERE seq=3")
        ok, bad = self.e.store.verify_audit()
        self.assertFalse(ok)
        self.assertEqual(bad, 3)

    def test_non_english_messages_flagged_for_translation(self):
        iss = self.issue_for("safe_pass", "w02")
        text = (self.e.outbox / f"{iss['id']}.1-message.md").read_text()
        self.assertIn("TRANSLATION NEEDED: Portuguese", text)


if __name__ == "__main__":
    unittest.main()
