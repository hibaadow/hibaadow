"""Phase 2: sign-in, sessions, staff codes, lockout, CSRF and per-customer access (AUDIT.md defect D6)."""
import shutil
import sqlite3
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from helpers import DEMO, SAMPLE, Client, start_portal

from opsengine import auth, web
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
B, L = "bremore_groundworks_sample", "liffey_interiors"


class Primitives(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.a = auth.Accounts(self.tmp / "accounts.db")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_passwords_are_hashed_never_stored(self):
        self.a.add_user("owner@acme.example.ie", "Owner", "customer", "a long passphrase here", customer_id=B)
        raw = (self.tmp / "accounts.db").read_bytes()
        self.assertNotIn(b"a long passphrase here", raw)
        self.assertTrue(self.a.user(email="owner@acme.example.ie")["password_hash"].startswith("pbkdf2_sha256$600000$"))

    def test_password_containing_the_email_name_is_refused(self):
        with self.assertRaises(ValueError):
            self.a.add_user("gerry@acme.example.ie", "Gerry", "ops", "gerry-is-the-best-2026")

    def test_weak_passwords_and_bad_users_are_refused(self):
        for args in (("x@acme.example.ie", "X", "customer", "short", B),
                     ("x@acme.example.ie", "X", "customer", "password1234", B),
                     ("x@acme.example.ie", "X", "customer", "a long passphrase here", None),
                     ("x@acme.example.ie", "X", "ops", "a long passphrase here", B),
                     ("not-an-email", "X", "ops", "a long passphrase here", None),
                     ("x@acme.example.ie", "X", "superuser", "a long passphrase here", None)):
            with self.assertRaises(ValueError, msg=args):
                self.a.add_user(*args[:4], customer_id=args[4])

    def test_rfc6238_codes(self):
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(auth.totp(secret, at=59, digits=8), "94287082")
        self.assertTrue(auth.check_totp(secret, auth.totp(secret, at=1000), at=1010))
        self.assertFalse(auth.check_totp(secret, auth.totp(secret, at=1000), at=1200))

    def test_lockout_after_five_failures(self):
        self.a.add_user("ops@acme.example.ie", "Ops", "ops", "a long passphrase here")
        for _ in range(4):
            with self.assertRaises(auth.AuthError):
                self.a.sign_in("ops@acme.example.ie", "wrong")
        with self.assertRaisesRegex(auth.AuthError, "Too many"):
            self.a.sign_in("ops@acme.example.ie", "wrong")
        with self.assertRaisesRegex(auth.AuthError, "Too many"):
            self.a.sign_in("ops@acme.example.ie", "a long passphrase here")  # even the right password, until it unlocks
        events = [r["event"] for r in self.a.store.audit_rows()]
        self.assertEqual(events.count("sign_in_failed"), 5)
        self.assertIn("sign_in_blocked", events)
        self.assertTrue(self.a.store.verify_audit()[0])

    def test_unknown_email_gives_the_same_answer(self):
        with self.assertRaisesRegex(auth.AuthError, "Email or password is wrong"):
            self.a.sign_in("nobody@acme.example.ie", "whatever")

    def test_sign_out_and_disable_end_sessions(self):
        uid = self.a.add_user("o@acme.example.ie", "O", "customer", "a long passphrase here", customer_id=B)
        token, stage = self.a.sign_in("o@acme.example.ie", "a long passphrase here")
        self.assertEqual(stage, "active")
        self.a.sign_out(token)
        self.assertIsNone(self.a.session(token))
        token, _ = self.a.sign_in("o@acme.example.ie", "a long passphrase here")
        self.a.set_disabled(uid, True)
        self.assertIsNone(self.a.session(token))

    def test_session_tokens_are_stored_hashed(self):
        self.a.add_user("o@acme.example.ie", "O", "customer", "a long passphrase here", customer_id=B)
        token, _ = self.a.sign_in("o@acme.example.ie", "a long passphrase here")
        rows = sqlite3.connect(self.tmp / "accounts.db").execute("SELECT token_hash FROM sessions").fetchall()
        self.assertNotIn(token, [r[0] for r in rows])


class PortalSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.base, cls.portal, cls.httpd = start_portal(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp)

    def signed_in(self, who):
        c = Client(self.base)
        self.assertEqual(c.login(DEMO[who]), (303, "/"))
        return c

    def test_nothing_without_signing_in(self):
        anon = Client(self.base)
        for path in ("/", f"/c/{B}/home", f"/c/{B}/ops", "/file?path=x"):
            self.assertIn("Sign in", anon.get(path), path)
        status, loc = anon.post(f"/c/{B}/approve", {"step": "ISS-0001.2"}, csrf=False)
        self.assertEqual((status, loc), (303, "/login"))

    def test_customer_sees_only_their_own_company(self):
        ciara = self.signed_in("liffey")
        page = ciara.get(f"/c/{B}/home")
        self.assertNotIn("Bremore", page.split("<main>")[1].split("</main>")[0].replace("SAMPLE DEMO", ""))
        self.assertIn("You don&#x27;t have access to that company", page)
        self.assertNotIn("Bremore Groundworks", ciara.get(f"/c/{L}/home"))  # no customer switcher for customers
        step = next(s for s in self.portal.engine(B).store.steps(state="awaiting_approval") if s["approval_role"] == "customer")
        status, loc = ciara.post(f"/c/{B}/approve", {"step": step["id"]})
        self.assertIn("don't have access", ciara.flash(loc))
        self.assertEqual(self.portal.engine(B).store.step(step["id"])["state"], "awaiting_approval")
        self.assertIn("access_denied", [r["event"] for r in self.portal.accounts.store.audit_rows()])

    def test_customer_cannot_open_staff_pages_or_actions(self):
        g = self.signed_in("customer")
        for tab in ("ops", "reviewer", "providers", "insights"):
            self.assertIn("That page isn&#x27;t available to you", g.get(f"/c/{B}/{tab}"), tab)
        g.get(f"/c/{B}/home")
        for act in ("review", "appointment", "simulate"):
            self.assertIn("isn't available to you", g.flash(g.post(f"/c/{B}/{act}", {"id": "x"})[1]), act)

    def test_forms_need_the_session_token(self):
        g = self.signed_in("customer")
        g.get(f"/c/{B}/home")
        step = next(s for s in self.portal.engine(B).store.steps(state="awaiting_approval") if s["approval_role"] == "customer")
        for token in ("", "forged"):
            status, body = g.post(f"/c/{B}/approve", {"step": step["id"], "csrf": token})
            self.assertEqual(status, 403)
        self.assertEqual(self.portal.engine(B).store.step(step["id"])["state"], "awaiting_approval")
        self.assertIn("csrf_rejected", [r["event"] for r in self.portal.accounts.store.audit_rows()])

    def test_customer_cannot_read_another_companys_files(self):
        other = next(c["outbox"] for c in self.portal.engine(L).store.comms() if c["outbox"])
        ciara, g = self.signed_in("liffey"), self.signed_in("customer")
        with self.assertRaises(urllib.error.HTTPError):
            g.get("/file?path=" + urllib.parse.quote(other))
        self.assertTrue(ciara.get("/file?path=" + urllib.parse.quote(other)))
        self.assertIn("Message not found", g.get(f"/c/{B}/message?path=" + urllib.parse.quote(other)))

    def test_sign_out(self):
        g = self.signed_in("customer")
        g.get(f"/c/{B}/home")
        self.assertEqual(g.post("/logout", {})[1], "/login")
        self.assertIn("Sign in", g.get(f"/c/{B}/home"))

    def test_security_headers_and_no_open_redirect(self):
        g = self.signed_in("customer")
        with g.follow.open(self.base + f"/c/{B}/home") as r:
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        g.get(f"/c/{B}/home")
        status, loc = g.post("/demo/next-day", {"next": "https://evil.example.com/"})
        self.assertTrue(loc.startswith("/c/"), loc)

    def test_session_cookie_flags(self):
        req = urllib.request.Request(self.base + "/login", method="POST",
                                     data=urllib.parse.urlencode({"email": DEMO["customer"], "password": auth.DEMO_PASSWORD}).encode())
        try:
            urllib.request.build_opener(_NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            cookie = e.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class RealMode(unittest.TestCase):
    """Without --demo: no demo accounts, staff must use a code, no demo clock, framing denied."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base, self.portal, self.httpd = start_portal(self.tmp, demo=False, customers=[SAMPLE])
        a = self.portal.accounts
        a.add_user("ops@acme.example.ie", "Ops Person", "ops", "a long passphrase here")
        a.add_user("ciara@acme.example.ie", "Ciara", "customer", "a long passphrase here", customer_id=L)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp)

    def test_demo_accounts_do_not_exist(self):
        c = Client(self.base)
        self.assertEqual(c.login(DEMO["ops"])[0], 401)
        self.assertNotIn("Demo accounts", c.get("/login"))

    def test_staff_set_up_and_use_a_code(self):
        import re
        c = Client(self.base)
        self.assertEqual(c.login("ops@acme.example.ie", "a long passphrase here"), (303, "/login/code"))
        page = c.get("/login/code")
        secret = re.search(r'name="secret" value="([A-Z2-7]+)"', page).group(1)
        self.assertEqual(c.post("/login/code", {"code": "000000", "secret": secret}, csrf=False)[0], 401)
        self.assertEqual(c.post("/login/code", {"code": auth.totp(secret), "secret": secret}, csrf=False), (303, "/"))
        self.assertIn("Ops queue", c.get("/"))
        c2 = Client(self.base)  # next time: code only, no setup
        self.assertEqual(c2.login("ops@acme.example.ie", "a long passphrase here"), (303, "/login/code"))
        self.assertNotIn('name="secret"', c2.get("/login/code"))
        self.assertEqual(c2.post("/login/code", {"code": auth.totp(secret)}, csrf=False), (303, "/"))
        events = [r["event"] for r in self.portal.accounts.store.audit_rows()]
        self.assertIn("mfa_enabled", events)
        self.assertIn("code_failed", events)

    def test_password_alone_does_not_get_staff_in(self):
        c = Client(self.base)
        c.login("ops@acme.example.ie", "a long passphrase here")
        self.assertIn("Sign in", c.get(f"/c/{L}/ops"))

    def test_no_demo_clock_and_no_framing(self):
        c = Client(self.base)
        c.login("ciara@acme.example.ie", "a long passphrase here")
        page = c.get(f"/c/{L}/home")
        self.assertNotIn("Run next day", page)
        self.assertIn("only available in the demo", c.flash(c.post("/demo/reset", {})[1]))
        with c.follow.open(self.base + f"/c/{L}/home") as r:
            self.assertEqual(r.headers["X-Frame-Options"], "DENY")

    def test_demo_mode_refuses_real_customers(self):
        real = self.tmp / "real"
        shutil.copytree(SAMPLE, real)
        company = (real / "company.json").read_text().replace('"sample": true', '"sample": false')
        (real / "company.json").write_text(company)
        with self.assertRaises(ValueError):
            web.Portal([real], self.tmp / "demo", demo=True)


if __name__ == "__main__":
    unittest.main()
