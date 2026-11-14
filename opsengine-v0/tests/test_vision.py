import base64
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import PHOTOS, SAMPLE, fake_claude, fake_claude_for

from opsengine import vision
from opsengine.engine import Engine

TODAY = date(2026, 11, 11)


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(SAMPLE, state_dir=self.tmp, today=TODAY)
        self.e.scan()
        self.e.advance()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def issue_for(self, req, holder):
        return next(i for i in self.e.store.issues() if i["requirement"] == req and i["holder"] == holder)

    def test_request_sends_the_image_to_claude(self):
        calls = []
        self.e.ingest_photo(PHOTOS / "safe_pass_clear.png", "w06", expected_type="safe_pass",
                            call=fake_claude_for("safe_pass_clear.png", calls))
        content = calls[0]["body"]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[0]["source"]["media_type"], "image/png")
        self.assertEqual(base64.b64decode(content[0]["source"]["data"]), (PHOTOS / "safe_pass_clear.png").read_bytes())
        self.assertIn("Safe Pass", content[1]["text"])

    def test_confident_read_is_ingested_and_resolves_the_issue(self):
        iss = self.issue_for("safe_pass", "w06")
        r = self.e.ingest_photo(PHOTOS / "safe_pass_clear.png", "w06", expected_type="safe_pass",
                                call=fake_claude_for("safe_pass_clear.png"))
        self.assertEqual(r["status"], "ingested")
        self.assertGreaterEqual(r["confidence"], vision.CONFIDENCE_THRESHOLD)
        doc = next(d for d in self.e.store.documents() if d["id"] == r["document"])
        self.assertEqual((doc["type"], doc["number"], doc["expires"]), ("safe_pass", "SP-300006", "2030-11-20"))
        self.assertEqual(doc["extraction"]["confidence"], r["confidence"])
        self.assertEqual(self.e.store.issue(iss["id"])["status"], "resolved")
        self.assertEqual(self.e.review_queue(), [])

    def test_low_confidence_goes_to_human_review_not_ingest(self):
        before = len(self.e.store.documents())
        r = self.e.ingest_photo(PHOTOS / "safe_pass_blurry.png", "w06", expected_type="safe_pass",
                                call=fake_claude_for("safe_pass_blurry.png"))
        self.assertEqual(r["status"], "needs_review")
        self.assertLess(r["confidence"], 0.9)
        self.assertEqual(len(self.e.store.documents()), before)  # nothing guessed into the record
        self.assertEqual([q["id"] for q in self.e.review_queue()], [r["review"]])
        self.assertNotEqual(self.issue_for("safe_pass", "w06")["status"], "resolved")

    def test_just_below_threshold_needs_review(self):
        reply = vision_reply(number_conf=0.89)
        r = self.e.ingest_photo(PHOTOS / "safe_pass_clear.png", "w06", call=fake_claude(reply))
        self.assertEqual(r["status"], "needs_review")
        self.assertAlmostEqual(r["confidence"], 0.89)

    def test_human_accepts_review_with_corrections(self):
        r = self.e.ingest_photo(PHOTOS / "safe_pass_blurry.png", "w06", call=fake_claude_for("safe_pass_blurry.png"))
        self.e.accept_review(r["review"], "Ops reviewer", corrections={"number": "SP-300006"})
        doc = next(d for d in self.e.store.documents() if d["holder"] == "w06" and d["type"] == "safe_pass")
        self.assertEqual(doc["number"], "SP-300006")
        self.assertEqual(doc["extraction"]["reviewed_by"], "Ops reviewer")
        self.assertEqual(self.issue_for("safe_pass", "w06")["status"], "resolved")
        self.assertEqual(self.e.store.review(r["review"])["status"], "accepted")
        events = [row["event"] for row in self.e.store.audit_rows()]
        self.assertIn("review_queued", events)
        self.assertIn("review_accepted", events)

    def test_reject_review_ingests_nothing(self):
        r = self.e.ingest_photo(PHOTOS / "safe_pass_blurry.png", "w06", call=fake_claude_for("safe_pass_blurry.png"))
        before = len(self.e.store.documents())
        self.e.reject_review(r["review"], "Ops reviewer", "Unreadable; asked Lucas to resend")
        self.assertEqual(len(self.e.store.documents()), before)
        self.assertEqual(self.e.store.review(r["review"])["status"], "rejected")
        with self.assertRaises(ValueError):
            self.e.accept_review(r["review"], "Someone")

    def test_wrong_person_goes_to_review(self):
        # Andrei's CSCS card sent in for Lucas: confident read, but the name does not match.
        r = self.e.ingest_photo(PHOTOS / "cscs_scaffolding.png", "w06", call=fake_claude_for("cscs_scaffolding.png"))
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(any("does not match" in x for x in r["reasons"]))

    def test_wrong_document_type_goes_to_review(self):
        r = self.e.ingest_photo(PHOTOS / "cscs_scaffolding.png", "w03", expected_type="safe_pass",
                                call=fake_claude_for("cscs_scaffolding.png"))
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(any("expected safe_pass" in x for x in r["reasons"]))

    def test_cscs_card_in_code_fence_is_parsed(self):
        r = self.e.ingest_photo(PHOTOS / "cscs_scaffolding.png", "w03", call=fake_claude_for("cscs_scaffolding.png"))
        self.assertEqual(r["status"], "ingested")

    def test_insurance_certificate_clears_both_insurance_issues(self):
        # the sample certificate is dated 1 Dec 2026, so run this on 2 Dec (a future-dated certificate is held)
        self.e = Engine(SAMPLE, state_dir=self.tmp / "dec", today=date(2026, 12, 2))
        self.e.scan()
        self.e.advance()
        r = self.e.ingest_photo(PHOTOS / "insurance_certificate.png", "company", received_via="email",
                                call=fake_claude_for("insurance_certificate.png"))
        self.assertEqual(r["status"], "ingested")
        doc = next(d for d in self.e.store.documents() if d["id"] == r["document"])
        self.assertEqual(doc["limit_eur"], 13000000)
        open_pl = [i for i in self.e.store.issues("open") if i["requirement"] == "public_liability"]
        self.assertEqual(open_pl, [])

    def test_no_api_key_means_human_review(self):
        r = self.e.ingest_photo(PHOTOS / "safe_pass_clear.png", "w06")  # OPSENGINE_OFFLINE=1: real transport is off
        self.assertEqual(r["status"], "needs_review")
        self.assertEqual(r["confidence"], 0.0)

    def test_refusal_or_garbage_means_human_review(self):
        for call in (fake_claude("", stop_reason="refusal"), fake_claude("Sorry, I can't read that.")):
            r = self.e.ingest_photo(PHOTOS / "safe_pass_clear.png", "w06", call=call)
            self.assertEqual(r["status"], "needs_review")

    def test_bad_date_goes_to_review(self):
        r = self.e.ingest_photo(PHOTOS / "safe_pass_clear.png", "w06", call=fake_claude(vision_reply(expires="20/11/30")))
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(any("not a valid date" in x for x in r["reasons"]))

    def test_audit_chain_intact_after_photo_work(self):
        self.e.ingest_photo(PHOTOS / "safe_pass_blurry.png", "w06", call=fake_claude_for("safe_pass_blurry.png"))
        self.assertTrue(self.e.store.verify_audit()[0])


class NameMatchTests(unittest.TestCase):
    def test_names(self):
        self.assertTrue(vision.names_match("Joao Silva", "JOÃO SILVA"))
        self.assertTrue(vision.names_match("Liffey Interiors Ltd (fictional sample)", "Liffey Interiors Limited"))
        self.assertFalse(vision.names_match("Lucas Pereira", "Andrei Popescu"))
        self.assertFalse(vision.names_match("Lucas Pereira", None))


def vision_reply(number_conf=0.98, expires="2030-11-20"):
    import json
    return json.dumps({"document_type": "safe_pass", "name_on_document": "Lucas Pereira",
                       "fields": {"number": {"value": "SP-300006", "confidence": number_conf},
                                  "expires": {"value": expires, "confidence": 0.97}},
                       "overall_confidence": 0.97, "notes": ""})


if __name__ == "__main__":
    unittest.main()
