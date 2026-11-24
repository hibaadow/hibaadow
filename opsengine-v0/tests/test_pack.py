"""Main contractor pack: covers the contractor's sites and people, never shows a gap as fine."""
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import helpers  # noqa: F401  (offline)

from opsengine.engine import Engine
from opsengine.knowledge import ROOT
from opsengine.pack import build_pack, pack_rows

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eng = Engine(BREMORE, state_dir=self.tmp / "state", today=date(2026, 11, 11))
        self.eng.scan()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_people_on_that_contractors_sites(self):
        sites, rows = pack_rows(self.eng, "harbour_construction")
        allowed = {w for s in sites for w in s["workers"]}
        self.assertTrue(all(r["holder"] in allowed for r in rows if r["holder_kind"] == "worker"))
        self.assertTrue(any(r["holder_kind"] == "company" for r in rows))

    def test_pack_is_honest_about_gaps(self):
        out = build_pack(self.eng, "glenmara_construction_sample", self.tmp / "packs")
        meta = json.loads((out / "pack.json").read_text())
        page = (out / "pack.html").read_text()
        self.assertFalse(meta["ready"])                       # the sample firm has designed gaps
        self.assertIn("Not ready yet", page)
        self.assertEqual(len(meta["outstanding"]), page.count("<li><b>"))
        self.assertIn("does not certify compliance", page)
        self.assertTrue(any(r["event"] == "contractor_pack_built" for r in self.eng.store.audit_rows()))

    def test_unknown_contractor(self):
        with self.assertRaises(ValueError):
            build_pack(self.eng, "nobody", self.tmp / "packs")


if __name__ == "__main__":
    unittest.main()
