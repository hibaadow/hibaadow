"""Logins: every page needs an account, customers only see their own company, and the
demo-only routes (role switcher, clock, reset) are gone when logins are on."""
import http.cookiejar
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
from opsengine.auth import Auth

BREMORE = "bremore_groundworks_sample"
LIFFEY = "liffey_interiors"
PW = "correct horse battery"


class AuthUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.auth = Auth(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_password_rules_and_roles(self):
        with self.assertRaises(ValueError):
            self.auth.add_user("a@b.ie", "A", "customer", PW)            # customer needs a company
        with self.assertRaises(ValueError):
            self.auth.add_user("a@b.ie", "A", "ops", "short")             # too short
        with self.assertRaises(ValueError):
            self.auth.add_user("a@b.ie", "A", "boss", PW)                 # unknown role

    def test_login_session_logout(self):
        self.auth.add_user("Owner@Firm.ie", "Ciara", "customer", PW, customer=BREMORE)
        self.assertIsNone(self.auth.login("owner@firm.ie", "wrong password!"))
        token = self.auth.login("owner@firm.ie", PW)
        user = self.auth.session(token)
        self.assertEqual(user["customer"], BREMORE)
        self.assertTrue(Auth.can_see(user, BREMORE))
        self.assertFalse(Auth.can_see(user, LIFFEY))
        self.auth.logout(token)
        self.assertIsNone(self.auth.session(token))

    def test_password_is_not_stored(self):
        self.auth.add_user("ops@x.ie", "Ops", "ops", PW)
        self.assertNotIn(PW.encode(), (self.tmp / "auth.db").read_bytes())

    def test_lockout_after_five_wrong_passwords(self):
        self.auth.add_user("ops@x.ie", "Ops", "ops", PW)
        for _ in range(5):
            self.assertIsNone(self.auth.login("ops@x.ie", "nope nope nope"))
        self.assertIsNone(self.auth.login("ops@x.ie", PW))

    def test_unknown_email_and_removed_user(self):
        self.assertIsNone(self.auth.login("nobody@x.ie", PW))
        self.auth.add_user("ops@x.ie", "Ops", "ops", PW)
        token = self.auth.login("ops@x.ie", PW)
        self.auth.remove_user("ops@x.ie")
        self.assertIsNone(self.auth.session(token))


class PortalLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        web.Handler.portal = web.Portal(web.SAMPLES, cls.tmp / "web")
        web.Handler.auth = Auth(cls.tmp / "auth")
        web.Handler.auth.add_user("owner@bremore.ie", "Ciara Byrne", "customer", PW, customer=BREMORE)
        web.Handler.auth.add_user("ops@opsengine.ie", "Ops Person", "ops", PW)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        web.Handler.auth = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def client(self, email=None):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        if email:
            self.post(opener, "/login", {"email": email, "password": PW})
        return opener

    def get(self, opener, path):
        try:
            r = opener.open(self.base + path)
            return r.status, r.geturl(), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, path, e.read().decode()

    def post(self, opener, path, data, origin=True):
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode(), method="POST")
        if origin:
            req.add_header("Origin", self.base)
        try:
            r = opener.open(req)
            return r.status, r.geturl(), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, path, e.read().decode()

    def test_everything_needs_a_login(self):
        c = self.client()
        for path in ("/", f"/c/{BREMORE}/home", f"/c/{BREMORE}/ops", "/as/ops"):
            status, url, body = self.get(c, path)
            self.assertTrue(url.endswith("/login"), path)
            self.assertIn("Log in", body)

    def test_wrong_password(self):
        c = self.client()
        status, url, body = self.post(c, "/login", {"email": "owner@bremore.ie", "password": "wrong password"})
        self.assertIn("Wrong email or password", urllib.parse.unquote(url) + body)

    def test_customer_sees_only_their_company(self):
        c = self.client("owner@bremore.ie")
        status, url, body = self.get(c, "/")
        self.assertTrue(url.endswith(f"/c/{BREMORE}/home"))
        self.assertIn("Ciara Byrne", body)
        self.assertNotIn("Liffey", body)                                 # not even in the company picker
        self.assertEqual(self.get(c, f"/c/{LIFFEY}/home")[0], 404)
        for tab in ("ops", "reviewer", "providers", "insights"):
            self.assertEqual(self.get(c, f"/c/{BREMORE}/{tab}")[0], 404)
        self.assertEqual(self.post(c, f"/c/{LIFFEY}/approve", {"step": "x"})[0], 404)

    def test_ops_sees_every_customer_and_demo_routes_are_gone(self):
        c = self.client("ops@opsengine.ie")
        self.assertEqual(self.get(c, f"/c/{LIFFEY}/ops")[0], 200)
        self.assertEqual(self.get(c, f"/c/{BREMORE}/ops")[0], 200)
        self.assertEqual(self.get(c, "/as/customer")[0], 404)
        self.assertEqual(self.post(c, "/demo/reset", {})[0], 404)
        body = self.get(c, f"/c/{BREMORE}/ops")[2]
        self.assertNotIn("Run next day", body)
        self.assertIn("Log out", body)

    def test_cross_site_post_refused(self):
        c = self.client("ops@opsengine.ie")
        self.assertEqual(self.post(c, f"/c/{BREMORE}/approve", {"step": "x"}, origin=False)[0], 403)

    def test_logout(self):
        c = self.client("ops@opsengine.ie")
        self.get(c, "/logout")
        self.assertTrue(self.get(c, f"/c/{BREMORE}/ops")[1].endswith("/login"))


if __name__ == "__main__":
    unittest.main()
