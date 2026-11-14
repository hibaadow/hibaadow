"""The clickable portal drives the real engine; the same boundaries hold through the web."""
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import helpers  # noqa: F401  (offline, mock off by default)

from opsengine import web
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
C = "bremore_groundworks_sample"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        web.Handler.portal = web.Portal(web.SAMPLES, cls.tmp)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.opener = urllib.request.build_opener(NoRedirect)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp)

    def get(self, path, role="customer"):
        req = urllib.request.Request(self.base + path, headers={"Cookie": f"role={role}"})
        with urllib.request.urlopen(req) as r:
            return r.read().decode()

    def post(self, path, data, role="customer"):
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode(), method="POST",
                                     headers={"Cookie": f"role={role}", "Referer": self.base + f"/c/{C}/home"})
        try:
            self.opener.open(req)
        except urllib.error.HTTPError as e:  # 303 surfaces as an error with redirects disabled
            return urllib.parse.unquote(e.headers["Location"]).split("flash=")[-1]
        return ""

    def engine(self):
        return web.Handler.portal.engine(C)

    def test_every_page_renders_for_every_view(self):
        for role in web.ROLES:
            for tab in ("home", "issues", "people", "subcontractors", "equipment", "documents", "actions", "bookings",
                        "messages", "report", "ops", "reviewer", "providers", "insights", "issue/ISS-0001"):
                html = self.get(f"/c/{C}/{tab}", role)
                self.assertNotIn("Something went wrong", html, (role, tab))
        self.assertIn("Can your team work on site?", self.get(f"/c/{C}/home"))

    def test_customer_approves_booking_and_it_is_booked(self):
        e = self.engine()
        step = next(s for s in e.store.steps(state="awaiting_approval") if s["action"] == "book_service")
        self.assertIn("Approved by Gráinne Murphy", self.post(f"/c/{C}/approve", {"step": step["id"]}))
        self.assertTrue(self.engine().store.appointments(issue_id=step["issue_id"]))

    def test_wrong_role_cannot_approve(self):
        e = self.engine()
        money = next(s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "customer")
        safety = next(s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "safety_reviewer")
        self.assertIn("Only the right person", self.post(f"/c/{C}/approve", {"step": money["id"]}, role="ops"))
        self.assertIn("Only the right person", self.post(f"/c/{C}/approve", {"step": safety["id"]}, role="customer"))
        self.assertEqual(self.engine().store.step(safety["id"])["state"], "awaiting_approval")

    def test_photo_upload_goes_through_the_engine(self):
        blurry = ROOT / "tests" / "fixtures" / "photos" / "safe_pass_blurry.png"
        flash = self.post(f"/c/{C}/upload", {"sample": str(blurry), "holder": "w16"})
        self.assertIn("sent to a person", flash)
        self.assertIn("REV-", self.get(f"/c/{C}/ops", role="ops"))

    def test_raise_corrective_action_from_the_portal(self):
        flash = self.post(f"/c/{C}/raise", {"title": "Edge protection missing", "owner": "w01", "site": "s1",
                                            "severity": "high", "due": "2026-11-14", "evidence": "photo"})
        self.assertIn("The owner has been told", flash)
        self.assertTrue(any(a["title"] == "Edge protection missing" for a in self.engine().corrective_actions("open")))

    def test_files_outside_the_demo_are_not_served(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/file?path=" + urllib.parse.quote(str(ROOT / "opsengine" / "web.py")))
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/file?path=/etc/passwd")


if __name__ == "__main__":
    unittest.main()
