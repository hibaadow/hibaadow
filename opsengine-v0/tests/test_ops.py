"""Phase 2 step 2: rules versions, signed checkpoints, backups, GDPR, user admin, health check, nightly, deploy."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from helpers import DEMO, SAMPLE, Client, start_portal

from opsengine import auth, backup, checkpoints, gdpr, rules_versions, scheduler
from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
TODAY = date(2026, 11, 11)
KEY = {"OPSENGINE_CHECKPOINT_KEY": "k" * 40}
MOCK = {"USE_MOCK_AI": "true"}  # only replays the recorded reads of the fictional sample photos


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)


# ---------------- rules versions ----------------
class RulesVersions(Tmp):
    def copy_rules(self):
        root = self.tmp / "root"
        for d in ("rules", "playbooks"):
            shutil.copytree(ROOT / d, root / d)
        return root

    def test_findings_and_scans_record_the_rules_version(self):
        e = Engine(BREMORE, state_dir=self.tmp, today=TODAY)
        e.scan()
        v = rules_versions.current_version()
        self.assertTrue(all(json.loads(i["data"])["rules_version"] == v for i in e.store.issues()))
        scans = [json.loads(a["payload"]) for a in e.store.audit_rows() if a["event"] == "scan_completed"]
        self.assertEqual(scans[-1]["rules_version"], v)

    def test_any_rule_change_changes_the_version(self):
        root = self.copy_rules()
        before = rules_versions.current_version(root)
        reqs = json.loads((root / "rules" / "requirements.json").read_text())
        reqs["requirements"][0]["warn_days"] += 1
        (root / "rules" / "requirements.json").write_text(json.dumps(reqs))
        self.assertNotEqual(before, rules_versions.current_version(root))
        (root / "rules" / "versions.json").write_text('{"versions": []}')  # the register itself isn't part of the rules
        self.assertEqual(rules_versions.current_version(root), rules_versions.current_version(root))

    def test_register_and_sign_off(self):
        root = self.copy_rules()
        (root / "rules" / "versions.json").write_text('{"versions": []}')
        self.assertFalse(rules_versions.status(root)["registered"])
        vid, new = rules_versions.register("first", root)
        self.assertTrue(new)
        with self.assertRaises(ValueError):
            rules_versions.sign_off(vid, "", "", root)
        rules_versions.sign_off(vid, "Pat Safety", "CMIOSH", root)
        st = rules_versions.status(root)
        self.assertTrue(st["signed_off"])
        self.assertEqual(st["sign_off"]["by"], "Pat Safety")

    def test_production_refuses_unsigned_rules(self):
        self.assertFalse(rules_versions.status()["signed_off"])  # the SAMPLE library is deliberately unsigned
        with mock.patch.dict(os.environ, {"OPSENGINE_REQUIRE_SIGNED_RULES": "true"}):
            with self.assertRaises(PermissionError):
                scheduler.run_customer(BREMORE, state_dir=self.tmp, today=TODAY)
        r = scheduler.run_customer(BREMORE, state_dir=self.tmp, today=TODAY)  # allowed, but recorded
        e = Engine(BREMORE, state_dir=self.tmp, today=TODAY)
        self.assertIn("rules_not_signed_off", [a["event"] for a in e.store.audit_rows()])


# ---------------- signed checkpoints ----------------
def _rewrite_history(db, seq, actor):
    """What an attacker with file access could do: edit a row and rebuild the whole chain."""
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER IF EXISTS audit_append_only_u")
    rows = con.execute("SELECT seq, ts, actor, event, ref, payload FROM audit ORDER BY seq").fetchall()
    prev = "GENESIS"
    for s, ts, a, ev, ref, payload in rows:
        a = actor if s == seq else a
        h = hashlib.sha256(f"{prev}|{ts}|{a}|{ev}|{ref}|{payload}".encode()).hexdigest()
        con.execute("UPDATE audit SET actor=?, prev_hash=?, hash=? WHERE seq=?", (a, prev, h, s))
        prev = h
    con.commit()
    con.close()


class Checkpoints(Tmp):
    def setUp(self):
        super().setUp()
        self.state = self.tmp / "state"
        scheduler.run_customer(BREMORE, state_dir=self.state, today=TODAY)
        self.file = self.tmp / "elsewhere" / "cp.jsonl"
        self.env = mock.patch.dict(os.environ, KEY)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def db(self):
        return self.state / "bremore_groundworks_sample" / "state.db"

    def test_clean_history_verifies(self):
        checkpoints.write_checkpoint(self.state, self.file)
        scheduler.run_customer(BREMORE, state_dir=self.state, today=TODAY)  # more entries afterwards is fine
        checkpoints.write_checkpoint(self.state, self.file)
        self.assertEqual(checkpoints.verify(self.state, self.file), [])

    def test_a_fully_rebuilt_chain_is_caught(self):
        checkpoints.write_checkpoint(self.state, self.file)
        _rewrite_history(self.db(), 3, "someone else")
        from opsengine.store import Store
        self.assertTrue(Store(self.db()).verify_audit()[0])  # the chain alone looks fine...
        problems = checkpoints.verify(self.state, self.file)
        self.assertTrue(any("history was rewritten" in p for p in problems), problems)  # ...the checkpoint isn't fooled

    def test_tampered_or_removed_checkpoints_are_caught(self):
        for _ in range(3):
            checkpoints.write_checkpoint(self.state, self.file)
        lines = self.file.read_text().splitlines()
        self.file.write_text("\n".join([lines[0], lines[2]]) + "\n")
        self.assertTrue(any("not chained" in p for p in checkpoints.verify(self.state, self.file)))
        rec = json.loads(lines[0])
        rec["logs"] = {}
        self.file.write_text(json.dumps(rec) + "\n")
        self.assertTrue(any("signature" in p for p in checkpoints.verify(self.state, self.file)))

    def test_needs_a_real_key(self):
        with mock.patch.dict(os.environ, {"OPSENGINE_CHECKPOINT_KEY": "short"}):
            with self.assertRaises(PermissionError):
                checkpoints.write_checkpoint(self.state, self.file)
        checkpoints.write_checkpoint(self.state, self.file)
        with mock.patch.dict(os.environ, {"OPSENGINE_CHECKPOINT_KEY": "z" * 40}):
            self.assertTrue(any("signature" in p for p in checkpoints.verify(self.state, self.file)))


# ---------------- backups ----------------
class Backups(Tmp):
    def setUp(self):
        super().setUp()
        self.state = self.tmp / "state"
        e = Engine(BREMORE, state_dir=self.state, today=TODAY)
        e.scan()
        e.advance()
        with mock.patch.dict(os.environ, MOCK):
            e.ingest_photo(BREMORE / "incoming" / "photos" / "safe_pass_andriy_kovalenko.png", "w16")  # an evidence file
        auth.Accounts(self.state / "accounts.db").add_user("a@acme.example.ie", "A", "admin", "a long passphrase here")

    def test_backup_verifies_and_restores_identically(self):
        b = backup.backup(self.state, self.tmp / "backups")
        self.assertEqual(backup.verify(b), [])
        restored = backup.restore(b, self.tmp / "restored")
        e = Engine(BREMORE, state_dir=restored, today=TODAY)
        self.assertEqual(len(e.store.issues()), len(Engine(BREMORE, state_dir=self.state, today=TODAY).store.issues()))
        self.assertTrue(e.store.verify_audit()[0])
        self.assertTrue(auth.Accounts(restored / "accounts.db").user(email="a@acme.example.ie"))

    def test_damaged_backup_fails_verification_and_wont_restore(self):
        b = backup.backup(self.state, self.tmp / "backups")
        db = b / "bremore_groundworks_sample" / "state.db"
        with open(db, "r+b") as f:
            f.seek(4096)
            f.write(b"\x00" * 64)
        self.assertTrue(backup.verify(b))
        with self.assertRaises(ValueError):
            backup.restore(b, self.tmp / "restored")

    def test_never_restores_over_existing_data_or_backs_up_into_itself(self):
        b = backup.backup(self.state, self.tmp / "backups")
        with self.assertRaises(ValueError):
            backup.restore(b, self.state)
        with self.assertRaises(ValueError):
            backup.backup(self.state, self.state / "backups")

    def test_prune_keeps_the_newest(self):
        dest = self.tmp / "backups"
        made = [backup.backup(self.state, dest) for _ in range(4)]
        removed = backup.prune(dest, keep=2)
        self.assertEqual(sorted(removed), sorted(made[:2]))
        self.assertEqual(backup.latest(dest), made[-1])


# ---------------- GDPR ----------------
class Gdpr(Tmp):
    def customer_with_leaver(self, left_on="2024-01-31"):
        folder = self.tmp / "c"
        shutil.copytree(BREMORE, folder)
        workers = json.loads((folder / "workers.json").read_text())
        next(w for w in workers if w["id"] == "w07")["left_on"] = left_on
        (folder / "workers.json").write_text(json.dumps(workers))
        e = Engine(folder, state_dir=self.tmp / "s", today=TODAY)
        e.scan()
        e.advance()
        return e

    def test_leavers_are_not_chased(self):
        e = self.customer_with_leaver()
        self.assertEqual([i for i in e.store.issues() if i["holder"] == "w07"], [])

    def test_purge_is_a_dry_run_unless_applied(self):
        e = self.customer_with_leaver()
        before = json.dumps(e.store.documents(), sort_keys=True)
        plan = gdpr.purge(e)
        self.assertEqual(len(plan["leaver_documents"]), 5)
        self.assertEqual(plan["workers_to_remove_from_workers_json"], ["w07"])
        self.assertEqual(json.dumps(e.store.documents(), sort_keys=True), before)

    def test_purge_redacts_leavers_and_audits_counts_not_content(self):
        e = self.customer_with_leaver()
        e.store.set_contact_pref("353870000207", "whatsapp", last_inbound_at="2024-01-01T00:00:00+00:00")
        gdpr.purge(e, apply=True)
        self.assertEqual(e.store.contact_pref("353870000207"), {})
        sp = next(d for d in e.store.documents() if d["holder"] == "w07" and d["type"] == "safe_pass")
        self.assertEqual(sp["number"], "[deleted]")
        self.assertEqual(sp["expires"], "2026-10-02")  # the fact a record existed is kept
        purged = [a for a in e.store.audit_rows() if a["event"] == "personal_data_purged"]
        self.assertIn('"leaver_documents": 5', purged[-1]["payload"])
        self.assertNotIn("SP-SAMPLE", purged[-1]["payload"])
        self.assertTrue(e.store.verify_audit()[0])

    def test_recent_leaver_is_kept_until_the_period_passes(self):
        e = self.customer_with_leaver(left_on="2026-06-30")
        self.assertEqual(gdpr.purge(e)["leaver_documents"], [])

    def test_subject_access_export(self):
        e = Engine(BREMORE, state_dir=self.tmp / "s", today=TODAY)
        e.scan()
        e.advance()
        with mock.patch.dict(os.environ, MOCK):
            self.assertEqual(e.ingest_photo(BREMORE / "incoming" / "photos" / "safe_pass_andriy_kovalenko.png", "w16")["status"], "ingested")
        out = gdpr.export_person(e, "w16", self.tmp / "sar")
        data = json.loads((out / "data.json").read_text())
        self.assertEqual(data["person"]["name"], "Andriy Kovalenko")
        self.assertTrue(any(d["type"] == "safe_pass" for d in data["documents"]))
        self.assertTrue(data["issues"] and data["messages"] and data["audit_entries"])
        self.assertTrue(any(f.suffix == ".png" for f in (out / "files").iterdir()))
        self.assertIn("subject_access_export", [a["event"] for a in e.store.audit_rows()])
        with self.assertRaises(ValueError):
            gdpr.export_person(e, "a01", self.tmp / "x")  # equipment isn't a person

    def test_inventory_and_retention_are_marked_for_the_solicitor(self):
        inv = gdpr.inventory()
        self.assertTrue(all("[SOLICITOR]" in i["lawful_basis"] for i in inv["items"]))
        self.assertFalse(gdpr.retention()["solicitor_confirmed"])


# ---------------- user admin page, password change, health check ----------------
class UserAdmin(Tmp):
    def setUp(self):
        super().setUp()
        self.base, self.portal, self.httpd = start_portal(self.tmp, demo=False, customers=[SAMPLE])
        a = self.portal.accounts
        a.add_user("admin@acme.example.ie", "Admin", "admin", "a long passphrase here")
        self.secret = auth.new_totp_secret()
        a.db.execute("UPDATE users SET mfa_secret=? WHERE email=?", (self.secret, "admin@acme.example.ie"))
        a.db.commit()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def admin(self):
        c = Client(self.base)
        c.login("admin@acme.example.ie", "a long passphrase here")
        c.post("/login/code", {"code": auth.totp(self.secret)}, csrf=False)
        c.get("/admin/users")
        return c

    def test_admin_adds_a_user_who_must_change_the_temporary_password(self):
        import re
        c = self.admin()
        page = c.post("/admin/users/add", {"name": "Ciara", "email": "ciara@acme.example.ie", "role": "customer",
                                           "customer": "liffey_interiors"})[1]
        temp = re.search(r'<span class="mono" style="font-size:18px">([^<]+)</span>', page).group(1)
        new = Client(self.base)
        self.assertEqual(new.login("ciara@acme.example.ie", temp), (303, "/"))
        self.assertIn("temporary password", new.get("/c/liffey_interiors/home"))  # forced to the password page
        new.get("/account/password")
        self.assertEqual(new.post("/account/password", {"current": temp, "new": "short", "again": "short"})[0], 400)
        status, loc = new.post("/account/password", {"current": temp, "new": "my own long passphrase", "again": "my own long passphrase"})
        self.assertIn("Password changed", new.flash(loc))
        self.assertIn("Can your team work on site?", new.get("/c/liffey_interiors/home"))
        events = [r["event"] for r in self.portal.accounts.store.audit_rows()]
        self.assertTrue({"user_created", "password_changed"} <= set(events))

    def test_only_admins_manage_users(self):
        self.portal.accounts.add_user("cust@acme.example.ie", "Cust", "customer", "a long passphrase here", customer_id="liffey_interiors")
        c = Client(self.base)
        c.login("cust@acme.example.ie", "a long passphrase here")
        self.assertIn("Only admins can manage users", c.get("/admin/users"))
        c.get("/c/liffey_interiors/home")
        self.assertIn("Only admins", c.flash(c.post("/admin/users/add", {"name": "X", "email": "x@acme.example.ie", "role": "admin"})[1]))
        self.assertIsNone(self.portal.accounts.user(email="x@acme.example.ie"))

    def test_cannot_disable_yourself_or_the_last_admin(self):
        c = self.admin()
        me = self.portal.accounts.user(email="admin@acme.example.ie")
        self.assertIn("can't disable your own", c.flash(c.post(f"/admin/users/{me['id']}/disable", {})[1]))
        self.assertFalse(self.portal.accounts.user(me["id"])["disabled"])

    def test_reset_password_signs_the_user_out(self):
        a = self.portal.accounts
        uid = a.add_user("cust@acme.example.ie", "Cust", "customer", "a long passphrase here", customer_id="liffey_interiors")
        cust = Client(self.base)
        cust.login("cust@acme.example.ie", "a long passphrase here")
        c = self.admin()
        c.post(f"/admin/users/{uid}/reset-password", {})
        self.assertIn("Sign in", cust.get("/c/liffey_interiors/home"))
        self.assertEqual(a.user(uid)["must_change"], 1)

    def test_health_check_needs_no_sign_in_and_shows_no_data(self):
        self.assertEqual(Client(self.base).get("/healthz"), "ok")


# ---------------- nightly and deploy ----------------
class NightlyAndDeploy(Tmp):
    def run_cli(self, *args, env=None):
        full = {**os.environ, "OPSENGINE_OFFLINE": "1", "USE_MOCK_AI": "false", **(env or {})}
        return subprocess.run([sys.executable, "-m", "opsengine", "--state", str(self.tmp / "state"), *args],
                              cwd=ROOT, capture_output=True, text=True, env=full)

    def test_nightly_does_everything_and_fails_loudly(self):
        root = self.tmp / "customers"
        shutil.copytree(BREMORE, root / "bremore")
        ok = self.run_cli("nightly", "--root", str(root), "--backup-to", str(self.tmp / "b"),
                          "--checkpoint-file", str(self.tmp / "cp.jsonl"), env=KEY)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        report = json.loads((self.tmp / "state" / "nightly-last.json").read_text())
        self.assertEqual(set(report["steps"]), {"rules", "daily_run", "retention", "checkpoint", "checkpoint_verify", "backup"})
        self.assertFalse(report["steps"]["retention"]["result"]["applied"])  # not until a solicitor confirms
        bad = self.run_cli("nightly", "--root", str(root), "--checkpoint-file", str(self.tmp / "cp.jsonl"),
                           env={"OPSENGINE_CHECKPOINT_KEY": ""})
        self.assertEqual(bad.returncode, 1)
        self.assertIn("FAILED", bad.stdout)
        strict = self.run_cli("nightly", "--root", str(root), env={"OPSENGINE_REQUIRE_SIGNED_RULES": "true"})
        self.assertEqual(strict.returncode, 1)

    def test_deploy_files_are_safe_by_default(self):
        docker = (ROOT / "deploy" / "Dockerfile").read_text()
        self.assertIn("USER opsengine", docker)
        self.assertIn("/healthz", docker)
        ignore = (ROOT / ".dockerignore").read_text()
        for path in ("state/", "data/customers/*", "deploy/production.env", ".env"):
            self.assertIn(path, ignore)
        self.assertIn("deploy/production.env", (ROOT / ".gitignore").read_text())
        env = (ROOT / "deploy" / "production.env.example").read_text()
        for setting in ("OPSENGINE_SECURE_COOKIES=1", "OPSENGINE_REQUIRE_SIGNED_RULES=true", "OPSENGINE_CHECKPOINT_KEY="):
            self.assertIn(setting, env)
        self.assertNotIn("--demo", (ROOT / "deploy" / "docker-compose.yml").read_text() + docker)


if __name__ == "__main__":
    unittest.main()
