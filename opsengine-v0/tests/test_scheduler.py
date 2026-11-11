import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from helpers import SAMPLE

from opsengine import scheduler
from opsengine.engine import Engine

DAY0 = date(2026, 11, 11)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_on(self, days):
        return scheduler.run_customer(SAMPLE, state_dir=self.tmp, today=DAY0 + timedelta(days=days))

    def engine(self, days=0):
        return Engine(SAMPLE, state_dir=self.tmp, today=DAY0 + timedelta(days=days))

    def test_first_run_scans_and_advances_without_chasing(self):
        r = self.run_on(0)
        self.assertEqual(len(r["opened"]), 10)
        self.assertGreater(r["actions"], 0)
        self.assertEqual((r["chased"], r["escalated"]), ([], []))

    def test_nothing_chased_after_one_day(self):
        self.run_on(0)
        r = self.run_on(1)
        self.assertEqual((r["chased"], r["escalated"]), ([], []))

    def test_chase_after_two_days_once_only(self):
        self.run_on(0)
        r = self.run_on(2)
        self.assertTrue(r["chased"])
        self.assertEqual(r["escalated"], [])
        again = self.run_on(2)  # a second run the same day must not resend
        self.assertEqual(again["chased"], [])
        third = self.run_on(3)
        self.assertEqual(third["chased"], [])

    def test_waiting_document_reminder_goes_to_the_right_person(self):
        self.run_on(0)
        self.run_on(2)
        e = self.engine(2)
        broker_wait = next(i for i in e.store.issues() if i["requirement"] == "public_liability" and i["kind"] == "expiring")
        step = next(s for s in e.store.steps(broker_wait["id"]) if s["state"] == "waiting")
        self.assertEqual(step["result"]["chased_on"], "2026-11-13")
        text = (e.outbox / f"{step['id']}-reminder-2026-11-13.md").read_text()
        self.assertIn("Sample Insurance Brokers", text)
        self.assertIn("still waiting", text)

    def test_approval_reminder_never_approves(self):
        self.run_on(0)
        self.run_on(2)
        e = self.engine(2)
        waiting = e.store.steps(state="awaiting_approval")
        self.assertTrue(waiting)
        for s in waiting:
            self.assertIsNone(s["approved_by"])
            self.assertEqual(s["result"]["chased_on"], "2026-11-13")
        booking = next(s for s in waiting if s["action"] == "book_service")
        text = (e.outbox / f"{booking['id']}-reminder-2026-11-13.md").read_text()
        self.assertIn("approval", text)
        self.assertIn("Ciara Byrne", text)

    def test_escalate_after_five_days(self):
        self.run_on(0)
        self.run_on(2)
        r = self.run_on(5)
        self.assertTrue(r["escalated"])
        self.assertEqual(r["chased"], [])  # already chased on day 2
        e = self.engine(5)
        for step_id in r["escalated"]:
            issue = e.store.issue(step_id.rsplit(".", 1)[0])
            self.assertEqual(issue["status"], "escalated")
            self.assertTrue((e.outbox / f"{step_id}-escalation-2026-11-16.md").exists())
        self.assertEqual(self.run_on(6)["escalated"], [])  # once only

    def test_missed_days_chase_and_escalate_together(self):
        self.run_on(0)
        r = self.run_on(7)  # scheduler was down for a week
        self.assertEqual(sorted(r["chased"]), sorted(r["escalated"]))
        self.assertTrue(r["escalated"])

    def test_proof_after_escalation_still_resolves(self):
        self.run_on(0)
        self.run_on(6)
        e = self.engine(6)
        iss = next(i for i in e.store.issues() if i["requirement"] == "safe_pass" and i["holder"] == "w02")
        e.ingest(json.loads((SAMPLE / "incoming" / "new_safe_pass_w02.json").read_text()))
        self.assertEqual(e.store.issue(iss["id"])["status"], "resolved")

    def test_retry_resets_the_clock(self):
        self.run_on(0)
        e = self.engine(3)
        iss = next(i for i in e.store.issues() if i["requirement"] == "safe_pass" and i["holder"] == "w03")
        e.approve(f"{iss['id']}.3", by="Owner")  # request goes out on day 3
        e.ingest(json.loads((SAMPLE / "incoming" / "wrong_card_w03.json").read_text()))  # rejected, asked again
        step = e.store.step(f"{iss['id']}.4")
        self.assertEqual(step["result"]["waiting_since"], "2026-11-14")
        self.assertNotIn(f"{iss['id']}.4", self.run_on(4)["chased"])
        self.assertIn(f"{iss['id']}.4", self.run_on(5)["chased"])

    def test_everything_is_audited(self):
        self.run_on(0)
        self.run_on(5)
        e = self.engine(5)
        events = [r["event"] for r in e.store.audit_rows()]
        for ev in ("daily_run_started", "daily_run_finished", "chased", "escalated"):
            self.assertIn(ev, events)
        self.assertTrue(e.store.verify_audit()[0])

    def test_daily_run_covers_every_customer_and_survives_a_broken_one(self):
        root = self.tmp / "customers"
        shutil.copytree(SAMPLE, root / "liffey_interiors", ignore=shutil.ignore_patterns("incoming"))
        shutil.copytree(SAMPLE, root / "_template")  # templates are skipped
        broken = root / "broken_co"
        broken.mkdir()
        (broken / "company.json").write_text("{not json")
        folders = scheduler.customer_folders(root)
        self.assertEqual([f.name for f in folders], ["broken_co", "liffey_interiors"])
        results = scheduler.daily_run(folders, state_dir=self.tmp / "state", today=DAY0)
        status = {r["customer"]: r["status"] for r in results}
        self.assertEqual(status, {"broken_co": "failed", "liffey_interiors": "ok"})


if __name__ == "__main__":
    unittest.main()
