"""Cross-customer operations console: every queue, every customer, most urgent first; staff only."""
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import DEMO, Client, start_portal

from opsengine import console

B, L = "bremore_groundworks_sample", "liffey_interiors"


class Console(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base, self.portal, self.httpd = start_portal(self.tmp, demo=True)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp)

    def engines(self):
        return {c: self.portal.engine(c) for c in self.portal.customers}

    def test_queues_cover_every_customer_and_sort_by_urgency(self):
        e = self.portal.engine(B)
        e.store.add_delivery(channel="email", to_name="Broker", address="b@x.example.ie", subject="Your quote", body="",
                             issue_id="ISS-0001", step_id="ISS-0001.2", outbox="", status="bounced", last_error="mailbox full")
        rows = console.items(self.engines())
        self.assertEqual({r["customer_id"] for r in rows}, {B, L})
        c = console.counts(rows)
        for q in ("stops_work", "safety_reviews", "customer_approvals", "failed_messages"):
            self.assertGreater(c[q], 0, q)
        ranks = [console.RANK.get(r["severity"], 2) for r in rows]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(rows[0]["severity"], "critical")

    def test_reviewers_see_only_safety_reviews(self):
        rows = console.items(self.engines(), role="reviewer")
        self.assertTrue(rows)
        self.assertEqual({r["queue"] for r in rows}, {"safety_reviews"})

    def test_portal_page_is_staff_only_and_filters(self):
        ops = Client(self.base)
        ops.login(DEMO["ops"])
        page = ops.get(f"/c/{B}/console")
        self.assertIn("All customers", page)
        self.assertIn("Liffey Interiors", page)
        self.assertIn("Bremore Groundworks", page)
        only = ops.get(f"/c/{B}/console?queue=safety_reviews")
        self.assertNotIn("Waiting on the customer&#x27;s approval</td>", only)
        cust = Client(self.base)
        cust.login(DEMO["customer"])
        self.assertIn("isn&#x27;t available", cust.get(f"/c/{B}/console"))
        rev = Client(self.base)
        rev.login(DEMO["reviewer"])
        page = rev.get(f"/c/{B}/console")
        self.assertIn("Safety reviews waiting", page)
        self.assertNotIn("Could stop work</td>", page)


if __name__ == "__main__":
    unittest.main()
