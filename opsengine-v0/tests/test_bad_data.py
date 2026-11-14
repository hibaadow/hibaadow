"""Phase 0 of AUDIT.md: every probe from the audit, so bad data can never crash the engine or pass silently."""
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import SAMPLE

from opsengine import scheduler
from opsengine.detect import detect
from opsengine.engine import Engine
from opsengine.knowledge import ROOT
from opsengine.validation import parse_any_date, parse_number

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
TODAY = date(2026, 11, 11)


class Parsing(unittest.TestCase):
    def test_irish_dates(self):
        for text in ("2027-12-31", "31/12/2027", "31-12-2027", "31.12.2027", "31 Dec 2027", "31st December 2027"):
            self.assertEqual(parse_any_date(text), date(2027, 12, 31), text)
        for text in ("12/31/2027", "31/12/27", "next year", "", "2027-13-01"):
            self.assertIsNone(parse_any_date(text), text)

    def test_money(self):
        for text, n in (("EUR 6,500,000", 6500000), ("€6.5m", 6500000), ("6.5 million", 6500000), ("13m", 13000000),
                        (6500000, 6500000), ("6500000", 6500000)):
            self.assertEqual(parse_number(text), n, text)
        for text in ("lots", "six million", "", True):
            self.assertIsNone(parse_number(text), text)


class BadDocuments(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(BREMORE, state_dir=self.tmp, today=TODAY)
        self.e.scan()
        self.e.advance()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def held(self, events):
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0][1].startswith("held for review"), events)
        return events[0][0]

    def test_d1_day_first_date_is_normalised_not_crashing(self):
        self.e.ingest({"id": "sp-new", "type": "safe_pass", "holder": "w16", "number": "SP-1", "expires": "31/12/2029"})
        doc = next(d for d in self.e.store.documents() if d["id"] == "sp-new")
        self.assertEqual(doc["expires"], "2029-12-31")
        self.e.scan()  # must not raise

    def test_d1_unreadable_date_is_held_not_stored(self):
        rid = self.held(self.e.ingest({"id": "sp-bad", "type": "safe_pass", "holder": "w16", "number": "SP-1", "expires": "next year"}))
        self.assertFalse(any(d["id"] == "sp-bad" for d in self.e.store.documents()))
        self.assertIn("not a date we can read", self.e.store.review(rid)["reasons"][0])
        self.e.scan()

    def test_d1_bad_date_already_in_the_database_becomes_a_finding(self):
        self.e.store.add_document({"id": "legacy", "type": "safe_pass", "holder": "w16", "number": "X", "expires": "31/12/27"}, source="legacy")
        findings = detect(self.e.kb, self.e.customer, self.e.store.documents(), TODAY)  # must not raise
        self.assertTrue(any("can't be read" in f["detail"] for f in findings if f["holder"] == "w16"))
        self.e.scan()
        self.assertEqual(scheduler.daily_run([BREMORE], state_dir=self.tmp, today=TODAY)[0]["status"], "ok")

    def test_d2_text_limit_is_parsed_and_checked(self):
        self.e.ingest({"id": "pl-txt", "type": "public_liability", "holder": "company", "insurer": "X", "policy_number": "P",
                       "limit_eur": "6.5m", "expires": "2027-06-30"})
        doc = next(d for d in self.e.store.documents() if d["id"] == "pl-txt")
        self.assertEqual(doc["limit_eur"], 6500000)
        details = [f["detail"] for f in detect(self.e.kb, self.e.customer, self.e.store.documents(), TODAY)
                   if f["requirement"] == "public_liability"]
        self.assertTrue(any("below 13,000,000" in d for d in details))

    def test_d2_unreadable_limit_is_held(self):
        self.held(self.e.ingest({"id": "pl-bad", "type": "public_liability", "holder": "company", "insurer": "X",
                                 "policy_number": "P", "limit_eur": "lots", "expires": "2027-06-30"}))

    def test_d2_non_number_already_on_file_fails_the_minimum(self):
        self.e.store.add_document({"id": "pl-legacy", "type": "public_liability", "holder": "company", "insurer": "X",
                                   "policy_number": "P", "limit_eur": "6.5m", "expires": "2027-12-31"}, source="legacy")
        details = [f["detail"] for f in detect(self.e.kb, self.e.customer, self.e.store.documents(), TODAY)
                   if f["requirement"] == "public_liability"]
        self.assertTrue(any("not a number" in d for d in details))

    def test_d3_missing_keys_unknown_type_and_unknown_holder_are_held(self):
        self.held(self.e.ingest({"id": "x1", "type": "safe_pass"}))
        self.held(self.e.ingest({"id": "x2", "type": "not_a_rule", "holder": "w01"}))
        self.held(self.e.ingest({"id": "x3", "type": "safe_pass", "holder": "w99", "number": "1", "expires": "2029-01-01"}))
        self.assertFalse({"x1", "x2", "x3"} & {d["id"] for d in self.e.store.documents()})

    def test_d4_implausible_expiry_is_held(self):
        iss = next(i for i in self.e.store.issues() if i["requirement"] == "safe_pass" and i["holder"] == "w16")
        self.held(self.e.ingest({"id": "sp-2099", "type": "safe_pass", "holder": "w16", "number": "SP-9", "expires": "2099-01-01"}))
        self.assertNotEqual(self.e.store.issue(iss["id"])["status"], "resolved")

    def test_d4_future_issue_date_is_held(self):
        self.held(self.e.ingest({"id": "ss-future", "type": "safety_statement", "holder": "company", "issued": "2027-06-01",
                                 "signed_by": "Gráinne Murphy"}))

    def test_held_document_can_be_corrected_by_a_person(self):
        rid = self.held(self.e.ingest({"id": "sp-fix", "type": "safe_pass", "holder": "w16", "number": "SP-1", "expires": "next year"}))
        with self.assertRaises(ValueError):
            self.e.accept_review(rid, "Ops")  # still invalid without a correction
        self.e.accept_review(rid, "Ops", corrections={"expires": "2029-11-30"})
        self.assertEqual(next(d for d in self.e.store.documents() if d["id"] == "sp-fix")["expires"], "2029-11-30")
        iss = next(i for i in self.e.store.issues() if i["requirement"] == "safe_pass" and i["holder"] == "w16")
        self.assertEqual(self.e.store.issue(iss["id"])["status"], "resolved")

    def test_invalid_onboarding_documents_are_held_not_seeded(self):
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(SAMPLE, tmp / "c")
        docs = json.loads((tmp / "c" / "documents.json").read_text())
        docs.append({"id": "seed-bad", "type": "safe_pass", "holder": "w06", "number": "1", "expires": "soon"})
        (tmp / "c" / "documents.json").write_text(json.dumps(docs))
        e = Engine(tmp / "c", state_dir=tmp / "s", today=TODAY)
        self.assertFalse(any(d["id"] == "seed-bad" for d in e.store.documents()))
        self.assertTrue(any("not a date" in r["reasons"][0] for r in e.review_queue()))
        e.scan()
        shutil.rmtree(tmp)

    def test_d5_one_failing_step_does_not_stop_the_others(self):
        tmp = Path(tempfile.mkdtemp())
        e = Engine(BREMORE, state_dir=tmp, today=TODAY)
        e.scan()
        e.kb.templates.pop("training_renewal")  # break one template
        e.advance()  # must not raise
        broken = [s for s in e.store.steps(state="blocked") if s["action"] == "message_worker"]
        self.assertTrue(broken)
        self.assertEqual(e.store.issue(broken[0]["issue_id"])["status"], "escalated")
        self.assertTrue(any(s["action"] == "request_document" and s["state"] == "waiting" for s in e.store.steps()))
        self.assertIn("step_failed", [a["event"] for a in e.store.audit_rows()])
        shutil.rmtree(tmp)

    def test_d7_status_messages_and_quotes_are_audited_and_logs_are_append_only(self):
        events = {a["event"] for a in self.e.store.audit_rows()}
        self.assertTrue({"issue_in_progress", "message_logged", "quote_requested"} <= events)
        for table in ("audit", "comms", "quotes"):
            with self.assertRaises(Exception, msg=table):
                self.e.store.db.execute(f"UPDATE {table} SET ts='x'")
            with self.assertRaises(Exception, msg=table):
                self.e.store.db.execute(f"DELETE FROM {table}")
        self.assertTrue(self.e.store.verify_audit()[0])

    def test_same_document_twice_changes_nothing(self):
        doc = {"id": "dup", "type": "safe_pass", "holder": "w16", "number": "SP1", "expires": "2029-01-01"}
        self.assertTrue(self.e.ingest(doc))
        self.assertEqual(self.e.ingest(doc), [])


if __name__ == "__main__":
    unittest.main()
