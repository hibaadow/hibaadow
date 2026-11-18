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


class Safeguards(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(BREMORE, state_dir=self.tmp / "state", today=TODAY)
        self.e.scan()
        self.e.advance()
        with mock.patch.dict(os.environ, {"USE_MOCK_AI": "true"}):
            self.e.ingest_photo(BREMORE / "incoming" / "photos" / "safe_pass_andriy_kovalenko.png", "w16")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def prepare(self):
        return packs.prepare(self.e, "harbour_construction", self.tmp / "packs", by="Ops (SAMPLE)")

    def test_nothing_leaves_without_explicit_confirmation_of_the_verified_recipient(self):
        rec = self.prepare()
        self.assertEqual((rec["destination"], rec["verified"], rec["people"]), ("supplier-portal.harbour.example.ie", 1, 6))
        with self.assertRaises(ValueError):
            packs.download(self.e, rec["id"], "", "x")  # no link before confirming
        with self.assertRaises(ValueError):
            packs.confirm(self.e, rec["id"], "Ops", "harbour_construction", False)  # box not ticked
        with self.assertRaises(ValueError):
            packs.confirm(self.e, rec["id"], "Ops", "glenmara_construction_sample", True)  # wrong contractor
        secret = packs.confirm(self.e, rec["id"], "Ops", "harbour_construction", True)
        with self.assertRaises(ValueError):
            packs.confirm(self.e, rec["id"], "Ops", "harbour_construction", True)  # one link per pack
        events = [a["event"] for a in self.e.store.audit_rows()]
        self.assertTrue({"pack_prepared", "pack_confirmed"} <= set(events))
        self.assertTrue(secret)

    def test_links_are_secret_limited_and_tamper_checked(self):
        rec = self.prepare()
        secret = packs.confirm(self.e, rec["id"], "Ops", "harbour_construction", True)
        with self.assertRaises(ValueError):
            packs.download(self.e, rec["id"], "0" * 64, "intruder")
        self.assertIn("pack_download_refused", [a["event"] for a in self.e.store.audit_rows()])
        for _ in range(packs.MAX_DOWNLOADS):
            name, data = packs.download(self.e, rec["id"], secret, "Ops")
            self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
        with self.assertRaises(ValueError):
            packs.download(self.e, rec["id"], secret, "Ops")  # used up
        rec2 = self.prepare()
        secret2 = packs.confirm(self.e, rec2["id"], "Ops", "harbour_construction", True)
        Path(rec2["zip"]).write_bytes(b"swapped")
        with self.assertRaises(ValueError):
            packs.download(self.e, rec2["id"], secret2, "Ops")
        rec3 = self.prepare()
        secret3 = packs.confirm(self.e, rec3["id"], "Ops", "harbour_construction", True)
        self.e.store.db.execute("UPDATE packs SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (rec3["id"],))
        with self.assertRaises(ValueError):
            packs.download(self.e, rec3["id"], secret3, "Ops")

    def test_sent_only_to_the_verified_destination_and_recorded(self):
        rec = self.prepare()
        packs.confirm(self.e, rec["id"], "Ops", "harbour_construction", True)
        with self.assertRaises(ValueError):
            packs.mark_sent(self.e, rec["id"], "Ops", "someone@elsewhere.example.com")
        packs.mark_sent(self.e, rec["id"], "Ops", "supplier-portal.harbour.example.ie")
        sent = [a for a in self.e.store.audit_rows() if a["event"] == "pack_sent"][-1]
        self.assertIn("supplier-portal.harbour.example.ie", sent["payload"])

    def test_real_customers_need_a_really_verified_recipient(self):
        company = json.loads((BREMORE / "company.json").read_text())
        self.e.customer.company = {**company, "sample": False, "name": "Acme Groundworks Ltd"}
        self.assertFalse(packs.recipient(self.e, "harbour_construction")["verified"])  # SAMPLE verification doesn't count
        rec = self.prepare()
        with self.assertRaises(ValueError):
            packs.confirm(self.e, rec["id"], "Ops", "harbour_construction", True)

    def test_no_other_customers_files_and_copies_expire(self):
        rec = self.prepare()
        folder = Path(rec["folder"])
        (folder / "documents" / "stray.png").write_bytes(b"someone else's photo")
        with self.assertRaises(ValueError):
            packs._check_scope(self.e, folder)
        from datetime import timedelta
        from opsengine import gdpr
        later = Engine(BREMORE, state_dir=self.tmp / "state", today=TODAY + timedelta(days=40))
        plan = gdpr.purge(later)
        self.assertIn(rec["id"], plan["pack_copies"])
        self.assertTrue(Path(rec["zip"]).exists())  # dry run deletes nothing
        gdpr.purge(later, apply=True)
        self.assertFalse(Path(rec["zip"]).exists())
        kept = next(x for x in packs.listing(later) if x["id"] == rec["id"])
        self.assertTrue(kept["deleted_at"])  # the record of the pack stays


class Portal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base, self.portal, self.httpd = start_portal(self.tmp, demo=True)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp)

    def test_prepare_preview_confirm_download_and_isolation(self):
        import re
        c = Client(self.base)
        c.login(DEMO["customer"])
        self.assertIn("Prepare pack", c.get(f"/c/{B}/documents"))
        status, loc = c.post(f"/c/{B}/pack-prepare", {"mc": "harbour_construction"})
        pack_id = re.search(r"id=(PK-\d+)", loc).group(1)
        preview = c.get(f"/c/{B}/pack?id={pack_id}")
        for text in ("supplier-portal.harbour.example.ie", "verified", "personal data of 6 people", "I confirm this pack is for"):
            self.assertIn(text, preview)
        self.assertIn("tick the box", c.flash(c.post(f"/c/{B}/pack-confirm", {"id": pack_id, "contractor": "harbour_construction"})[1]))
        status, page = c.post(f"/c/{B}/pack-confirm", {"id": pack_id, "contractor": "harbour_construction", "confirm": "yes"})
        link = re.search(r'href="(/c/[^"]+pack-download[^"]+)"', page).group(1).replace("&amp;", "&")
        with c.follow.open(self.base + link) as r:
            self.assertEqual(r.headers["Content-Type"], "application/zip")
        other = Client(self.base)
        other.login(DEMO["liffey"])
        self.assertIn("don&#x27;t have access", other.get(link))  # another customer can't use the link
        rev = Client(self.base)
        rev.login(DEMO["reviewer"])
        self.assertIn("isn&#x27;t available", rev.get(link))
        self.assertEqual(self.portal.engine(B).store.db.execute("SELECT downloads FROM packs WHERE id=?", (pack_id,)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
