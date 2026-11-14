import os
import shutil
import tempfile
import unittest
import urllib.request
from datetime import date
from pathlib import Path
from unittest import mock

from helpers import PHOTOS, SAMPLE

from opsengine import config, llm
from opsengine.engine import Engine

TODAY = date(2026, 11, 11)


def _no_network(*a, **k):
    raise AssertionError("mock mode must never call the network")


class MockModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = {"USE_MOCK_AI": "true", "ANTHROPIC_API_KEY": "would-be-real", "OPSENGINE_OFFLINE": "0"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.net = mock.patch.object(urllib.request, "urlopen", _no_network)
        self.net.start()
        self.e = Engine(SAMPLE, state_dir=self.tmp, today=TODAY)
        self.e.scan()
        self.e.advance()

    def tearDown(self):
        self.net.stop()
        self.env.stop()
        shutil.rmtree(self.tmp)

    def test_mock_wins_over_a_key(self):
        self.assertTrue(config.mock_ai())
        self.assertFalse(llm.available())
        self.assertIsNone(llm.complete("system", "prompt"))

    def test_sample_photo_gets_recorded_read_and_is_labelled_mock(self):
        r = self.e.ingest_photo(PHOTOS / "safe_pass_clear.png", "w06", expected_type="safe_pass")
        self.assertEqual((r["status"], r["source"]), ("ingested", "mock"))
        doc = next(d for d in self.e.store.documents() if d["id"] == r["document"])
        self.assertEqual(doc["extraction"]["model"], "mock")
        audit = [row for row in self.e.store.audit_rows() if row["event"] == "photo_read"]
        self.assertIn('"source": "mock"', audit[-1]["payload"])

    def test_blurry_sample_still_goes_to_review_in_mock_mode(self):
        r = self.e.ingest_photo(PHOTOS / "safe_pass_blurry.png", "w06", expected_type="safe_pass")
        self.assertEqual(r["status"], "needs_review")

    def test_unknown_photo_is_never_faked(self):
        other = self.tmp / "real_customer_photo.png"
        other.write_bytes((PHOTOS / "safe_pass_clear.png").read_bytes() + b"\x00")  # different hash
        r = self.e.ingest_photo(other, "w06", expected_type="safe_pass")
        self.assertEqual((r["status"], r["confidence"]), ("needs_review", 0.0))
        self.assertIn("no recorded read", r["reasons"][0])

    def test_translations_are_still_flagged_not_faked(self):
        iss = next(i for i in self.e.store.issues() if i["requirement"] == "safe_pass" and i["holder"] == "w02")
        text = (self.e.outbox / f"{iss['id']}.1-message.md").read_text()
        self.assertIn("TRANSLATION NEEDED: Portuguese", text)


class DotenvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_parses_and_never_overrides(self):
        f = self.tmp / ".env"
        f.write_text("# comment\nexport OPS_T_A=1\nOPS_T_B=\"quoted value\"\nOPS_T_C=x # note\nOPS_T_D=keep\nbad line\n")
        with mock.patch.dict(os.environ, {"OPS_T_D": "already"}):
            loaded = config.load_dotenv(f)
            self.assertEqual(os.environ["OPS_T_A"], "1")
            self.assertEqual(os.environ["OPS_T_B"], "quoted value")
            self.assertEqual(os.environ["OPS_T_C"], "x")
            self.assertEqual(os.environ["OPS_T_D"], "already")
            self.assertNotIn("OPS_T_D", loaded)
        for k in ("OPS_T_A", "OPS_T_B", "OPS_T_C"):
            os.environ.pop(k, None)

    def test_missing_file_is_fine(self):
        self.assertEqual(config.load_dotenv(self.tmp / "nope.env"), {})

    def test_example_has_empty_key_placeholder(self):
        text = (config.ROOT / ".env.example").read_text()
        self.assertIn("\nANTHROPIC_API_KEY=\n", text)
        self.assertIn("USE_MOCK_AI=true", text)


if __name__ == "__main__":
    unittest.main()
