"""The portal drives the real engine; sign-in, access control and approval boundaries hold through the web."""
import shutil
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

from helpers import DEMO, Client, start_portal

from opsengine.knowledge import ROOT

C = "bremore_groundworks_sample"


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.base, cls.portal, cls.httpd = start_portal(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp)

    def client(self, who):
        c = Client(self.base)
        status, loc = c.login(DEMO[who])
        self.assertEqual((status, loc), (303, "/"))
        return c

    def engine(self):
        return self.portal.engine(C)

    def test_every_page_renders_for_every_role(self):
        tabs = {"customer": ("home", "issues", "people", "subcontractors", "equipment", "documents", "actions", "bookings",
                             "messages", "report", "issue/ISS-0001"),
                "ops": ("ops", "issues", "bookings", "providers", "documents", "actions", "messages", "insights", "issue/ISS-0001"),
                "reviewer": ("reviewer", "actions", "documents", "issue/ISS-0001")}
        for who, pages in tabs.items():
            c = self.client(who)
            for tab in pages:
                html = c.get(f"/c/{C}/{tab}")
                self.assertNotIn("Something went wrong", html, (who, tab))
        self.assertIn("Can your team work on site?", self.client("customer").get(f"/c/{C}/home"))

    def test_customer_approves_booking_and_it_is_booked_with_their_identity(self):
        c = self.client("customer")
        c.get(f"/c/{C}/home")
        step = next(s for s in self.engine().store.steps(state="awaiting_approval") if s["action"] == "book_service")
        status, loc = c.post(f"/c/{C}/approve", {"step": step["id"]})
        self.assertIn("Approved by Gráinne Murphy (SAMPLE)", c.flash(loc))
        self.assertTrue(self.engine().store.appointments(issue_id=step["issue_id"]))
        audit = [a for a in self.engine().store.audit_rows() if a["event"] == "approved" and a["ref"] == step["id"]]
        self.assertEqual(audit[0]["actor"], "human:Gráinne Murphy (SAMPLE) <grainne@bremore-groundworks.example.ie>")

    def test_wrong_role_cannot_approve(self):
        e = self.engine()
        money = next(s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "customer")
        safety = next(s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "safety_reviewer")
        ops, cust = self.client("ops"), self.client("customer")
        ops.get(f"/c/{C}/ops")
        cust.get(f"/c/{C}/home")
        self.assertIn("Only the right person", ops.flash(ops.post(f"/c/{C}/approve", {"step": money["id"]})[1]))
        self.assertIn("Only the right person", cust.flash(cust.post(f"/c/{C}/approve", {"step": safety["id"]})[1]))
        self.assertEqual(self.engine().store.step(safety["id"])["state"], "awaiting_approval")

    def test_photo_upload_goes_through_the_engine(self):
        c = self.client("customer")
        c.get(f"/c/{C}/documents")
        blurry = ROOT / "tests" / "fixtures" / "photos" / "safe_pass_blurry.png"
        status, loc = c.post(f"/c/{C}/upload", {"sample": str(blurry), "holder": "w16"})
        self.assertIn("sent to a person", c.flash(loc))
        self.assertIn("REV-", self.client("ops").get(f"/c/{C}/ops"))

    def test_raise_corrective_action_from_the_portal(self):
        c = self.client("customer")
        c.get(f"/c/{C}/actions")
        status, loc = c.post(f"/c/{C}/raise", {"title": "Edge protection missing", "owner": "w01", "site": "s1",
                                              "severity": "high", "due": "2026-11-14", "evidence": "photo"})
        self.assertIn("The owner has been told", c.flash(loc))
        self.assertTrue(any(a["title"] == "Edge protection missing" for a in self.engine().corrective_actions("open")))

    def test_files_outside_the_portal_are_not_served(self):
        c = self.client("ops")
        for path in (str(ROOT / "opsengine" / "web.py"), "/etc/passwd", str(self.tmp / "accounts.db")):
            with self.assertRaises(urllib.error.HTTPError):
                c.get("/file?path=" + urllib.parse.quote(path))
