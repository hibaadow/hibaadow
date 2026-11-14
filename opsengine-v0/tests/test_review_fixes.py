"""Portal review fixes: isolate critical items, grouped approvals, merged issues, customer stats, provider choice."""
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

from helpers import SAMPLE

from opsengine import web
from opsengine.engine import Engine
from opsengine.knowledge import ROOT
from opsengine.report import compliance_register, customer_stats

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
TODAY = date(2026, 11, 11)


class Base(unittest.TestCase):
    folder = BREMORE

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(self.folder, state_dir=self.tmp, today=TODAY)
        self.e.scan()
        self.e.advance()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def body(self, step_id):
        return (self.e.outbox / f"{step_id}-message.md").read_text(encoding="utf-8").strip().split("\n\n")[-1]


# 1. Critical defects: stop using it now
class CriticalIsolation(Base):
    def dumper(self):
        return next(a for a in self.e.corrective_actions("open") if "seat belt" in a["title"])

    def test_first_step_and_first_message_take_it_out_of_use(self):
        ca = self.dumper()
        steps = self.e.store.steps(ca["id"])
        self.assertEqual([s["action"] for s in steps][:2], ["isolate_item", "request_document"])
        first = self.body(steps[0]["id"])
        self.assertTrue(first.startswith("Hi Gráinne, do not use Site dumper 6t DU-07 (SAMPLE) until this is repaired: seat belt does not latch."), first)
        self.assertLess(first.index("do not use"), first.index("by 13 Nov 2026"))  # stop first, then the fix and deadline
        self.assertIn("competent person", first)
        self.assertIn("item_isolated", [a["event"] for a in self.e.store.audit_rows()])

    def test_out_of_use_on_the_register_until_evidence_is_verified(self):
        status = lambda: {r["holder"]: r["status"] for r in compliance_register(self.e) if r["requirement"] == "safe_to_use"}
        self.assertEqual(status(), {"a07": "out_of_use"})
        ca = self.dumper()
        self.e.ingest(json.loads((BREMORE / "incoming" / "a07_repair_evidence.json").read_text()))
        self.assertEqual(status(), {})  # verified: back in use
        close = next(s for s in self.e.store.steps(ca["id"]) if s["action"] == "close_action")
        self.assertEqual((close["state"], close["approval_role"]), ("awaiting_approval", "safety_reviewer"))  # still signed off

    def test_manual_critical_action_on_a_site(self):
        aid = self.e.raise_corrective_action("Edge protection missing at stair core", owner="w01", severity="critical", raised_by="ops")
        self.e._advance_issue(aid)
        first = self.body(f"{aid}.1")
        self.assertIn("do not use the affected equipment or work area until this is repaired: Edge protection missing", first)

    def test_lower_severity_has_no_isolation_step(self):
        ca = next(a for a in self.e.corrective_actions("open") if "tyre" in a["title"])
        self.assertNotIn("isolate_item", [s["action"] for s in self.e.store.steps(ca["id"])])


# 3. Grouped approvals, each still audited on its own
class GroupedApprovals(Base):
    def test_group_shown_and_approve_all_audits_each(self):
        web.Handler.portal = web.Portal(web.SAMPLES, self.tmp / "web")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        cid = "bremore_groundworks_sample"
        try:
            page = urllib.request.urlopen(urllib.request.Request(f"{base}/c/{cid}/home", headers={"Cookie": "role=customer"})).read().decode()
            self.assertIn("Book SOLAS Safe Pass for 4 workers, €690 total", page)
            self.assertIn("Review one by one", page)
            eng = web.Handler.portal.engine(cid)
            group = [s["id"] for s in eng.store.steps(state="awaiting_approval")
                     if s["action"] == "book_service" and eng.store.issue(s["issue_id"])["requirement"] == "safe_pass"]
            self.assertEqual(len(group), 4)

            def post(role):
                req = urllib.request.Request(f"{base}/c/{cid}/approve-group", method="POST", headers={"Cookie": f"role={role}", "Referer": base},
                                             data=urllib.parse.urlencode({"steps": ",".join(group)}).encode())
                try:
                    urllib.request.build_opener(_NoRedirect).open(req)
                except urllib.error.HTTPError as e:
                    return urllib.parse.unquote(e.headers["Location"])
            self.assertIn("Only the right person", post("ops"))
            self.assertIn("Approved all 4", post("customer"))
            eng = web.Handler.portal.engine(cid)
            approved = [a["ref"] for a in eng.store.audit_rows() if a["event"] == "approved"]
            self.assertEqual(sorted(approved), sorted(group))  # one audit entry per approval
            self.assertEqual(len(eng.store.appointments()), 4)
        finally:
            httpd.shutdown()
            httpd.server_close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


# 4. One issue for one fix, covering every contractor at the highest value
class MergedIssues(Base):
    def test_one_public_liability_issue_for_both_contractors(self):
        pl = [i for i in self.e.store.issues() if i["requirement"] == "public_liability" and i["kind"] == "incomplete"]
        self.assertEqual(len(pl), 1)
        iss = pl[0]
        self.assertEqual(sorted(json.loads(iss["required_by"])), ["glenmara_construction_sample", "harbour_construction"])
        msg = self.body(f"{iss['id']}.1")
        self.assertIn("€13m covers both", msg)
        ask = next(q for q in self.e.approval_queue() if q["step"].startswith(iss["id"]))
        self.assertIn("raise your public liability cover to €13m for Glenmara", ask["summary"])
        self.e.approve(ask["step"], "Gráinne Murphy")
        self.e.ingest({"id": "pl-13m", "type": "public_liability", "holder": "company", "insurer": "Sample Insurer DAC",
                       "policy_number": "PL-SAMPLE-9", "limit_eur": 13000000, "expires": "2027-11-30"})
        self.assertEqual(self.e.store.issue(iss["id"])["status"], "resolved")
        sent = sorted(p.name for p in self.e.outbox.glob(f"{iss['id']}.*-distribute-*"))
        self.assertEqual(len(sent), 2)


# 5. Customer stats instead of the automation rate
class CustomerStats(Base):
    def test_stats(self):
        st = customer_stats(self.e)
        self.assertEqual(st["sorted_this_week"], 0)
        self.assertIsNone(st["average_days_to_sort"])
        self.assertGreater(st["could_stop_work"], 5)
        self.e.ingest({"id": "sp-w07", "type": "safe_pass", "holder": "w07", "number": "SP-SAMPLE-1", "expires": "2030-10-01"})
        later = Engine(BREMORE, state_dir=self.tmp, today=date(2026, 11, 14))
        st = customer_stats(later)
        self.assertEqual(st["sorted_this_week"], 1)
        self.assertEqual(st["average_days_to_sort"], 0.0)


# 6. Provider choice: cheapest that finishes in time, fastest only when time is tight
class ProviderChoice(Base):
    folder = SAMPLE

    def choice(self, req, holder):
        iss = next(i for i in self.e.store.issues() if i["requirement"] == req and i["holder"] == holder)
        return next(s for s in self.e.store.steps(iss["id"]) if s["action"] == "find_provider")["result"]

    def test_cheapest_when_there_is_time(self):
        r = self.choice("safe_pass", "w03")  # Andrei: expires in 29 days
        self.assertEqual((r["recommended"]["price_eur"], r["reason"]), (150, "Cheapest option that's done in time."))

    def test_fastest_when_it_stops_work_now(self):
        r = self.choice("safe_pass", "w02")  # Joao: already expired
        self.assertEqual(r["recommended"]["lead_days"], 2)
        self.assertTrue(r["reason"].startswith("Fastest option"))

    def run_on(self, day):
        e = Engine(SAMPLE, state_dir=self.tmp / day.isoformat(), today=day)
        e.scan()
        e.advance()
        iss = next(i for i in e.store.issues() if i["requirement"] == "safe_pass" and i["holder"] == "w03")
        return next(s for s in e.store.steps(iss["id"]) if s["action"] == "find_provider")["result"]

    def test_skips_the_cheap_option_that_would_finish_too_late(self):
        r = self.run_on(date(2026, 11, 28))  # 12 days left: the EUR 150 course ends 3 days before expiry
        self.assertEqual((r["recommended"]["name"], r["recommended"]["price_eur"]), ("Demo Training Group (Dublin 1)", 180))
        self.assertEqual(r["reason"], "Cheapest option in Romanian that's done in time.")

    def test_fastest_when_nothing_finishes_with_a_week_to_spare(self):
        r = self.run_on(date(2026, 12, 5))  # 5 days left
        self.assertEqual(r["recommended"]["lead_days"], 2)
        self.assertEqual(r["reason"], "Fastest option: time is tight (before it expires).")

    def test_reason_shown_in_the_approval(self):
        ask = next(q for q in self.e.approval_queue() if "Andrei" in q["summary"])
        self.assertIn("Cheapest option that's done in time.", ask["summary"])


if __name__ == "__main__":
    unittest.main()
