"""Customer feedback: who is responsible, price clarity, setup, fewer approvals (standing approval), worker data."""
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import DEMO, Client, start_portal

from opsengine.engine import Engine
from opsengine.knowledge import ROOT

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
TODAY = date(2026, 11, 11)
B = "bremore_groundworks_sample"


class StandingApproval(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(BREMORE, state_dir=self.tmp, today=TODAY)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def bookings(self):
        return [s for s in self.e.store.steps() if s["action"] == "book_service"]

    def test_small_bookings_go_ahead_and_everything_else_still_waits(self):
        self.e.set_standing_approval(200, None, "Gráinne Murphy <grainne@bremore-groundworks.example.ie>")
        self.e.scan()
        self.e.advance()
        auto = [s for s in self.bookings() if (s["approved_by"] or "").startswith("Standing approval")]
        self.assertTrue(auto)
        waiting = [s for s in self.e.store.steps(state="awaiting_approval")]
        for s in waiting:
            if s["action"] == "book_service":
                prior = {p["action"]: p["result"] for p in self.e.store.steps(s["issue_id"]) if p["result"]}
                self.assertGreater(prior["find_provider"]["recommended"]["price_eur"], 200)
        self.assertTrue(any(s["action"] != "book_service" and s["approval_role"] == "customer" for s in waiting))  # insurance etc.
        events = [a for a in self.e.store.audit_rows() if a["event"] == "auto_approved"]
        self.assertEqual(len(events), len(auto))
        self.assertIn("Gráinne Murphy", auto[0]["approved_by"])

    def test_monthly_cap_and_limits(self):
        self.e.set_standing_approval(200, 300, "Gráinne Murphy <grainne@bremore-groundworks.example.ie>")
        self.e.scan()
        self.e.advance()
        self.assertLessEqual(self.e.auto_spent_this_month(), 300)
        with self.assertRaises(ValueError):
            self.e.set_standing_approval(9999, None, "x")
        self.e.set_standing_approval(0, None, "x")
        self.assertIsNone(self.e.standing_approval())

    def test_off_by_default(self):
        self.e.scan()
        self.e.advance()
        self.assertFalse(any((s["approved_by"] or "").startswith("Standing approval") for s in self.bookings()))


class Pricing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def customer(self, plan, workers=None, **plan_extra):
        import json
        n = len(list(self.tmp.iterdir()))
        folder = self.tmp / f"c{n}"
        shutil.copytree(BREMORE, folder)
        company = json.loads((folder / "company.json").read_text())
        company["plan"] = {"id": plan, **plan_extra}
        (folder / "company.json").write_text(json.dumps(company))
        if workers:
            ws = json.loads((folder / "workers.json").read_text())
            base = ws[0]
            ws += [{**base, "id": f"x{n:03d}", "name": f"Extra Worker {n}", "phone": f"+353 87 111 {n:04d}"} for n in range(workers - len(ws))]
            (folder / "workers.json").write_text(json.dumps(ws))
        e = Engine(folder, state_dir=self.tmp / f"s{n}", today=TODAY)
        e.scan()
        e.advance()
        return e

    def test_bill_and_plan_fit(self):
        from opsengine import pricing
        e = self.customer("growth")
        self.assertEqual(pricing.customer_plan(e.customer)["monthly_total_eur"], 399)
        self.assertEqual(pricing.fit_problems(e), [])
        big = self.customer("growth", workers=40)
        self.assertTrue(any("40 of 30 workers" in n and "Business" in n for n in pricing.fit_problems(big)))
        extra = self.customer("growth", workers=40, extra_worker_blocks=1)
        self.assertEqual(pricing.customer_plan(extra.customer)["monthly_total_eur"], 499)
        self.assertEqual(pricing.fit_problems(extra), [])

    def test_starter_flags_growth_features_in_use(self):
        from opsengine import pricing
        e = self.customer("starter")
        self.assertEqual(pricing.customer_plan(e.customer)["monthly_total_eur"], 199)  # extra sites only once agreed
        self.assertTrue(any("2 of 1 sites" in n and "€40" in n for n in pricing.fit_problems(e)))
        paid = self.customer("starter", extra_sites=1)
        self.assertEqual(pricing.customer_plan(paid.customer)["monthly_total_eur"], 239)  # €199 + one site at the default €40
        notes = " ".join(pricing.fit_problems(e))
        for feature in ("subcontractor compliance tracking", "inspection and booking requests", "provider comparisons"):
            self.assertIn(feature, notes)
        self.assertNotIn("multiple projects", notes)  # covered by the extra-site add-on

    def test_suggested_plan_by_size(self):
        from opsengine import pricing
        self.assertEqual([pricing.suggested(n)["id"] for n in (5, 10, 11, 75, 150, 151)],
                         ["starter", "starter", "growth", "business", "scale", "enterprise"])


class Portal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base, self.portal, self.httpd = start_portal(self.tmp, demo=True)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp)

    def test_how_it_works_answers_the_objections(self):
        c = Client(self.base)
        c.login(DEMO["customer"])
        page = c.get(f"/c/{B}/how")
        for text in ("Who is responsible for what", "A qualified person signs off", "We never", "What it costs",
                     "Paid to the provider, at their price", "we take no commission", "Setup: our team does it",
                     "You don't have to upload your certs", "Your workers' data", "never use the photo to recognise faces",
                     "Your plan: Growth", "€399 a month", "excluding VAT", "One-off onboarding fee", "Additional 25 workers",
                     "Custom pricing", "Included in every plan", "Competent-person review of drafted RAMS",
                     "Additional specialist safety work", "never signs off safety documents"):
            self.assertIn(text, page.replace("&#x27;", "'"))

    def test_bookings_show_provider_price_apart_from_our_fee(self):
        c = Client(self.base)
        c.login(DEMO["customer"])
        home = c.get(f"/c/{B}/home")
        self.assertIn("paid to", home)
        self.assertIn("no extra fee from us", home)

    def test_staff_see_plans_and_revenue_customers_dont(self):
        ops = Client(self.base)
        ops.login(DEMO["ops"])
        self.assertIn("Monthly recurring revenue", ops.get(f"/c/{B}/insights"))
        cust = Client(self.base)
        cust.login(DEMO["customer"])
        self.assertNotIn("Monthly recurring revenue", cust.get(f"/c/{B}/how"))

    def test_only_the_customer_sets_the_standing_approval(self):
        ops = Client(self.base)
        ops.login(DEMO["ops"])
        ops.get(f"/c/{B}/settings")
        self.assertIn("isn't available", ops.flash(ops.post(f"/c/{B}/standing-approval", {"limit": "500"})[1]))
        self.assertIsNone(self.portal.engine(B).standing_approval())
        cust = Client(self.base)
        cust.login(DEMO["customer"])
        cust.get(f"/c/{B}/settings")
        self.assertIn("Saved", cust.flash(cust.post(f"/c/{B}/standing-approval", {"limit": "200", "cap": "1000"})[1]))
        rule = self.portal.engine(B).standing_approval()
        self.assertEqual((rule["limit_eur"], rule["monthly_cap_eur"]), (200, 1000))
        self.assertIn("Gráinne", rule["set_by"])
        self.assertIn("Not saved", cust.flash(cust.post(f"/c/{B}/standing-approval", {"limit": "99999"})[1]))


if __name__ == "__main__":
    unittest.main()
