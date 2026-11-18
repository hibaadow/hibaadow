"""Subscription limits: allowances, 80%/100% notices, review hold and amendment, admin configuration."""
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import DEMO, Client, start_portal

from opsengine import auth, limits, pricing
from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
LIFFEY = ROOT / "data" / "sample" / "liffey_interiors"
TODAY = date(2026, 11, 11)
REVIEWER = "Safety reviewer (SAMPLE) <reviewer@opsengine.example.ie>"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def engine(self, folder=LIFFEY, plan=None, **overrides):
        if plan:
            dest = self.tmp / f"c{len(list(self.tmp.iterdir()))}"
            shutil.copytree(folder, dest)
            company = json.loads((dest / "company.json").read_text())
            company["plan"] = {"id": plan}
            (dest / "company.json").write_text(json.dumps(company))
            folder = dest
        e = Engine(folder, state_dir=self.tmp / "state", today=TODAY)
        if overrides:
            limits.set_overrides(e, overrides, "Admin <admin@opsengine.example.ie>")
        e.scan()
        e.advance()
        return e

    def drafts(self, e, routine=True):
        """Reviewer drafts. routine=True turns them into routine revisions (not missing or expired, medium), which a
        plan limit can hold; the sample drafts are for missing documents, which are urgent and never held."""
        out = [s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "safety_reviewer"
               and s["action"] == "request_signature"]
        if routine:
            for s in out:
                e.store.update_issue(s["issue_id"], kind="content_gap", severity="medium")
        return out


class Limits(Base):
    def test_plan_limits_and_specialist_work(self):
        got = {p["id"]: p["limits"] for p in pricing.load()["plans"]}
        self.assertEqual(got["starter"], {"workers": 10, "sites": 1, "reviews_per_month": 5})
        self.assertEqual(got["growth"], {"workers": 30, "sites": 3, "reviews_per_month": 15})
        self.assertEqual(got["business"], {"workers": 75, "sites": 10, "reviews_per_month": 40})
        self.assertEqual(got["scale"], {"workers": 150, "sites": 25, "reviews_per_month": 100})
        self.assertIsNone(got["enterprise"])
        self.assertFalse(pricing.is_specialist("rams"))
        self.assertFalse(pricing.is_specialist("safety_statement"))
        self.assertEqual(len(pricing.load()["specialist_safety_work"]), 6)
        self.assertEqual(pricing.default_site_eur(), 40)

    def test_review_allowance_holds_never_approves_and_amendment_is_included(self):
        e = self.engine(reviews_per_month=1)
        a, b = self.drafts(e)[:2]
        e.reject(a["id"], REVIEWER, "missing method for working at height")  # uses the 1 review
        with self.assertRaises(limits.LimitReached):
            e.approve(b["id"], REVIEWER)
        self.assertEqual(e.store.step(b["id"])["state"], "awaiting_approval")  # still waiting, visibly
        self.assertIsNone(e.store.step(b["id"])["approved_by"])
        e.resubmit_draft(a["issue_id"], "Ops (SAMPLE) <ops@opsengine.example.ie>", "added working at height method")
        self.assertEqual(e.store.step(a["id"])["state"], "awaiting_approval")
        e.approve(a["id"], REVIEWER)  # the amended resubmission is included, even at the limit
        self.assertEqual(limits.usage(e)["reviews_per_month"]["used"], 1)
        limits.set_overrides(e, {"reviews_per_month": 1, "extra_reviews_this_month": 1}, "Admin <admin@opsengine.example.ie>")
        e.approve(b["id"], REVIEWER)  # capacity added
        self.assertEqual(limits.usage(e)["reviews_per_month"]["used"], 2)

    def test_urgent_safety_reviews_are_never_held(self):
        e = self.engine(reviews_per_month=0)
        d = self.drafts(e, routine=False)[0]  # a missing Safety Statement: could stop work
        self.assertTrue(limits.is_urgent(e, d))
        self.assertFalse(limits.is_held(e, d))
        e.approve(d["id"], REVIEWER)
        over = [a for a in e.store.audit_rows() if a["event"] == "review_over_allowance"]
        self.assertTrue(over and '"billable_only_with_customer_agreement": true' in over[0]["payload"])

    def test_held_review_is_announced_escalated_and_can_be_marked_urgent(self):
        from datetime import timedelta
        e = self.engine(reviews_per_month=0)
        d = self.drafts(e)[0]
        self.assertTrue(limits.is_held(e, d))
        self.assertEqual([what for _, what in limits.hold_notices(e)][0], "held: customer, ops and reviewer told")
        self.assertEqual(limits.hold_notices(e), [])  # once
        names = {f.name for f in e.outbox.iterdir()}
        self.assertIn(f"held-{d['id']}.md", names)
        self.assertIn(f"held-{d['id']}-ops.md", names)
        later = Engine(LIFFEY, state_dir=self.tmp / "state", today=TODAY + timedelta(days=limits.HOLD_ESCALATE_DAYS))
        self.assertTrue(any("escalated" in what for _, what in limits.hold_notices(later)))
        self.assertEqual(later.store.issue(d["issue_id"])["status"], "escalated")
        with self.assertRaises(ValueError):
            limits.mark_urgent(later, d["id"], "Gráinne", "")
        limits.mark_urgent(later, d["id"], "Ciara Byrne <ciara@liffey-interiors.example.ie>", "main contractor needs it before Monday")
        self.assertFalse(limits.is_held(later, later.store.step(d["id"])))
        later.approve(d["id"], REVIEWER)
        self.assertIn("urgent_review_requested", [a["event"] for a in later.store.audit_rows()])

    def test_notices_at_80_and_100_once_each(self):
        e = self.engine(reviews_per_month=2)
        d = self.drafts(e)
        e.approve(d[0]["id"], REVIEWER)
        self.assertEqual(limits.notify(e), [])  # 1 of 2 = 50%
        e.approve(d[1]["id"], REVIEWER)
        self.assertEqual(limits.notify(e), [("reviews_per_month", 100)])
        self.assertEqual(limits.notify(e), [])  # once a month
        note = next(f for f in e.outbox.iterdir() if f.name.startswith("usage-reviews"))
        text = note.read_text()
        self.assertIn("Nothing is approved automatically", text)
        self.assertIn("upgrade to Business", text)

    def test_over_the_worker_limit_everyone_is_still_monitored(self):
        e = self.engine(BREMORE, plan="starter")
        u = limits.usage(e)
        self.assertEqual((u["workers"]["used"], u["workers"]["allowance"], u["workers"]["level"]), (16, 10, "over"))
        held = {i["holder"] for i in e.store.issues()}
        self.assertTrue({"w12", "w16"} <= held)  # workers past the 10th still have their issues raised
        events = dict(limits.notify(e))
        self.assertEqual(events.get("workers"), 100)
        text = next(f for f in e.outbox.iterdir() if f.name.startswith("usage-workers")).read_text()
        self.assertIn("still fully monitored", text)
        self.assertIn("€100 a month", text)

    def test_80_percent_notice(self):
        e = self.engine(BREMORE, plan="growth", workers=20)  # 16 of 20 = 80%
        self.assertIn(("workers", 80), limits.notify(e))

    def test_extra_site_price_default_and_enterprise_override(self):
        e = self.engine(BREMORE, plan="starter", extra_sites=1)
        self.assertEqual(pricing.customer_plan(e.customer, extras=limits.extras(e))["monthly_total_eur"], 239)
        limits.set_overrides(e, {"extra_sites": 1, "extra_site_eur": 55}, "Admin <admin@opsengine.example.ie>")
        self.assertEqual(pricing.customer_plan(e.customer, extras=limits.extras(e))["monthly_total_eur"], 254)


class AdminPage(Base):
    def setUp(self):
        super().setUp()
        self.base, self.portal, self.httpd = start_portal(self.tmp / "p", demo=True)
        self.portal.accounts.add_user("admin@opsengine.example.ie", "Admin (SAMPLE)", "admin", auth.DEMO_PASSWORD,
                                      demo=True, check_strength=False)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def test_only_admins_change_limits_and_changes_are_audited(self):
        ops = Client(self.base)
        ops.login(DEMO["ops"])
        self.assertIn("Only admins", ops.get("/admin/plans"))
        admin = Client(self.base)
        admin.login("admin@opsengine.example.ie")
        self.assertIn("Plans and limits", admin.get("/admin/plans"))
        self.assertIn("Saved", admin.flash(admin.post("/admin/plans/starter", {"workers": "12", "sites": "1", "reviews_per_month": "6"})[1]))
        self.assertEqual(limits.plan_limit_overrides(self.portal.state)["starter"]["workers"], 12)
        admin.get("/admin/plans")
        cid = "bremore_groundworks_sample"
        admin.post(f"/admin/plans/customer/{cid}", {"extra_reviews_this_month": "3", "extra_site_eur": "45"})
        ex = limits.extras(self.portal.engine(cid))
        self.assertEqual((ex["extra_reviews"], ex["extra_site_eur"]), (3, 45))
        events = [r["event"] for r in self.portal.accounts.store.audit_rows()]
        self.assertTrue({"plan_limits_changed", "customer_limits_changed"} <= set(events))
        admin.get("/admin/plans")
        self.assertIn("Not saved", admin.flash(admin.post("/admin/plans/nonsense", {"workers": "5"})[1]))

    def test_reviewer_queue_shows_the_hold_and_the_urgent_route(self):
        cid = "liffey_interiors"
        e = self.portal.engine(cid)
        limits.set_overrides(e, {"reviews_per_month": 0}, "Admin <admin@opsengine.example.ie>")
        step = next(s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "safety_reviewer")
        e.store.update_issue(step["issue_id"], kind="content_gap", severity="medium")
        rev = Client(self.base)
        rev.login(DEMO["reviewer"])
        page = rev.get(f"/c/{cid}/reviewer").replace("&#x27;", "'")
        self.assertIn("Held: the customer has used this month's review allowance", page)
        self.assertIn("Mark urgent and review now", page)
        self.assertIn("Urgent safety review: never held", page)  # the other drafts are for missing documents
        rev.post(f"/c/{cid}/urgent-review", {"step": step["id"], "reason": "site start on Monday"})
        self.assertFalse(limits.is_held(e, self.portal.engine(cid).store.step(step["id"])))


if __name__ == "__main__":
    unittest.main()
