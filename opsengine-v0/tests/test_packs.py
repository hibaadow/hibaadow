"""Main contractor compliance packs, in each contractor's own format."""
import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

from helpers import DEMO, Client, start_portal

from opsengine import packs
from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
TODAY = date(2026, 11, 11)
B = "bremore_groundworks_sample"


class Packs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def engine(self, folder=BREMORE):
        e = Engine(folder, state_dir=self.tmp / "state", today=TODAY)
        e.scan()
        e.advance()
        with mock.patch.dict(os.environ, {"USE_MOCK_AI": "true"}):
            e.ingest_photo(BREMORE / "incoming" / "photos" / "safe_pass_andriy_kovalenko.png", "w16")  # w16 is on site s2
        return e

    def read(self, r):
        z = zipfile.ZipFile(r["zip"])
        root = z.namelist()[0].split("/")[0]
        get = lambda n: z.read(f"{root}/{n}").decode()
        return z, root, get

    def test_each_contractor_gets_its_own_format(self):
        e = self.engine()
        g = packs.build(e, "glenmara_construction_sample", self.tmp / "out")
        h = packs.build(e, "harbour_construction", self.tmp / "out")
        self.assertTrue(g["zip"].name.startswith("GLN-") and h["zip"].name.startswith("HBR-"))
        _, _, gget = self.read(g)
        _, _, hget = self.read(h)
        self.assertEqual(next(csv.reader(io.StringIO(gget("register.csv")))), ["Section", "Requirement", "Name", "Status", "Expiry", "Reference"])
        self.assertEqual(next(csv.reader(io.StringIO(hget("register.csv")))), ["Requirement", "Name", "Status", "Expiry"])
        z, root, _ = self.read(h)
        self.assertTrue(any(n.endswith("Andriy-Kovalenko_safe-pass.png") for n in z.namelist()))  # Harbour's naming

    def test_only_that_contractors_sites_and_people(self):
        e = self.engine()
        g = {r["holder"] for r in packs.rows_for(e, "glenmara_construction_sample", ["s1"])}
        h = {r["holder"] for r in packs.rows_for(e, "harbour_construction", ["s2"])}
        self.assertIn("w16", h)
        self.assertNotIn("w16", g)  # Andriy works on Harbour's site only
        with self.assertRaises(ValueError):
            packs.build(e, "northgate_build", self.tmp / "out")  # no sites with them
        with self.assertRaises(ValueError):
            packs.build(e, "harbour_construction", self.tmp / "out", site_id="s1")

    def test_gaps_are_listed_terms_confirmed_not_attached_and_manifest_checks(self):
        e = self.engine()
        r = packs.build(e, "harbour_construction", self.tmp / "out")
        z, root, get = self.read(r)
        cover = get("cover.md")
        self.assertIn("INCOMPLETE", cover)
        self.assertIn("SAMPLE DATA", cover)
        self.assertIn("## Outstanding", cover)
        self.assertGreater(r["gaps"], 0)
        self.assertFalse(any("written-terms" in n for n in z.namelist()))
        manifest = json.loads(get("MANIFEST.json"))
        for rel, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256(z.read(f"{root}/{rel}")).hexdigest(), digest)
        self.assertIn("pack_exported", [a["event"] for a in e.store.audit_rows()])

    def test_contractor_that_wants_no_photos(self):
        folder = self.tmp / "c"
        shutil.copytree(BREMORE, folder)
        company = json.loads((folder / "company.json").read_text())
        for s in company["sites"]:
            if s["id"] == "s2":
                s["main_contractor"] = "northgate_build"
        (folder / "company.json").write_text(json.dumps(company))
        e = self.engine(folder)
        r = packs.build(e, "northgate_build", self.tmp / "out")
        self.assertEqual(r["files"], 0)
        z, _, get = self.read(r)
        self.assertFalse(any(n.endswith(".png") for n in z.namelist()))
        self.assertIn("this contractor asked for none", get("cover.md"))


class Portal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base, self.portal, self.httpd = start_portal(self.tmp, demo=True)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp)

    def test_customer_downloads_their_own_pack_only(self):
        c = Client(self.base)
        c.login(DEMO["customer"])
        self.assertIn("Main contractor packs", c.get(f"/c/{B}/documents"))
        with c.follow.open(f"{self.base}/c/{B}/pack?mc=harbour_construction") as r:
            self.assertEqual(r.headers["Content-Type"], "application/zip")
            self.assertTrue(zipfile.is_zipfile(io.BytesIO(r.read())))
        other = Client(self.base)
        other.login(DEMO["liffey"])
        self.assertIn("don&#x27;t have access", other.get(f"/c/{B}/pack?mc=harbour_construction"))


if __name__ == "__main__":
    unittest.main()
