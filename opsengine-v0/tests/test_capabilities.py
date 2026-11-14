"""One test class per section of PRODUCT.md that the earlier tests didn't cover."""
import csv
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from helpers import PHOTOS, SAMPLE, fake_claude_for

from opsengine import connectors, scheduler
from opsengine.actions import provider_problems
from opsengine.detect import detect, review_document
from opsengine.engine import Engine
from opsengine.insights import insights
from opsengine.knowledge import ROOT, Customer, Knowledge
from opsengine.report import compliance_register, export_records, risk_overview

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

    def issue(self, req, holder=None):
        return next(i for i in self.e.store.issues() if i["requirement"] == req and (holder is None or i["holder"] == holder))

    def step(self, issue, action):
        return next(s for s in self.e.store.steps(issue["id"]) if s["action"] == action)


# ---- 1. Compliance monitoring -------------------------------------------------------------
class Monitoring(Base):
    def test_register_covers_people_company_subcontractors_assets_and_sites(self):
        kinds = {r["holder_kind"] for r in compliance_register(self.e)}
        self.assertEqual(kinds, {"company", "worker", "subcontractor", "asset"})

    def test_risks_flag_what_can_stop_work_and_what_lapses_soon(self):
        r = risk_overview(self.e)
        blocking = {(x["holder"], x["requirement"]) for x in r["blocking"]}
        self.assertIn(("a03", "lifting_accessories_examination"), blocking)
        self.assertIn(("sc02", "subcontractor_public_liability"), blocking)
        self.assertIn(("a06", "portable_tools_test"), {(x["holder"], x["requirement"]) for x in r["lapsing_soon"]})
        self.assertGreater(r["by_site"]["s1"]["blocking"], 0)


# ---- 2. Document management --------------------------------------------------------------
class DocumentReview(Base):
    def test_rams_must_cover_tasks_and_brief_everyone(self):
        kb, c = self.e.kb, Customer.load(BREMORE)
        rams = next(d for d in c.seed_documents if d["id"] == "sample-rams-s1")
        gaps = review_document(kb.requirements["rams"], {**rams, "briefed_workers": ["w01"]}, c, "s1")
        self.assertTrue(any("dumper work" in g for g in gaps))
        self.assertTrue(any("not briefed" in g and "Tomasz Kowalski" in g for g in gaps))

    def test_safety_statement_must_be_signed_by_owner_or_director(self):
        kb, c = self.e.kb, Customer.load(BREMORE)
        req = kb.requirements["safety_statement"]
        self.assertEqual(review_document(req, {"signed_by": "Declan Murphy"}, c), [])
        self.assertTrue(review_document(req, {"signed_by": "Paddy Walsh"}, c))

    def test_insurance_must_name_the_right_company(self):
        kb, c = self.e.kb, Customer.load(BREMORE)
        self.assertTrue(review_document(kb.requirements["public_liability"], {"insured": "Other Firm Ltd"}, c))
        self.assertEqual(review_document(kb.requirements["public_liability"], {"insured": "Bremore Groundworks Limited"}, c), [])

    def test_content_gap_becomes_an_action_with_the_points_to_fix(self):
        iss = self.issue("rams")
        rams_content = next(i for i in self.e.store.issues() if i["key"] == "rams|company|s1|content")
        text = (self.e.outbox / f"{rams_content['id']}.1-message.md").read_text()
        self.assertIn("dumper work", text)
        self.assertIn("we do not sign off safety documents", text)

    def test_versions_and_current_document(self):
        self.e.ingest({"id": "sample-sp-w07-new", "type": "safe_pass", "holder": "w07", "number": "SP-SAMPLE-9", "expires": "2030-10-01"})
        g = next(g for g in self.e.document_history(holder="w07") if g["type"] == "safe_pass")
        self.assertEqual(g["current"], "sample-sp-w07-new")
        self.assertEqual([d["id"] for d in g["versions"]], ["sample-sp-w07-new", "sample-sp-w07"])

    def test_evidence_file_is_kept_by_hash(self):
        self.e.ingest_photo(PHOTOS / "cscs_scaffolding.png", "company", call=fake_claude_for("cscs_scaffolding.png"))
        review = self.e.review_queue()[0]  # name doesn't match: goes to review
        self.e.accept_review(review["id"], "Ops", doc_type="cscs_excavator", corrections={"number": "CS-1"})
        stored = list((self.e.evidence_dir).glob("*.png"))
        self.assertEqual(len(stored), 1)
        doc = next(d for d in self.e.store.documents() if d.get("evidence"))
        self.assertEqual(doc["evidence"]["stored_as"], stored[0].name)


# ---- 4 and 7. Training, providers, quotes, appointments -------------------------------------
class ProvidersAndBookings(Base):
    def test_expired_provider_is_never_recommended(self):
        lapsed = next(p for p in self.e.kb.providers if p["id"] == "p-sp-4")
        self.assertTrue(provider_problems(lapsed, TODAY))  # cheapest, fastest, every language - but expired
        safe_pass_searches = [s["result"] for s in self.e.store.steps()
                              if s["action"] == "find_provider" and s["spec"]["category"] == "safe_pass_course"]
        self.assertEqual(len(safe_pass_searches), 4)
        for found in safe_pass_searches:
            self.assertNotEqual(found["recommended"]["id"], "p-sp-4")
            self.assertIn("p-sp-4", found["excluded"])
            self.assertNotIn("p-sp-4", found["alternatives"])

    def test_service_area_is_respected(self):
        cork_only = next(p for p in self.e.kb.providers if p["id"] == "p-le-2")
        self.assertIn("does not cover Dublin", provider_problems(cork_only, TODAY, "Dublin"))

    def test_quotes_requested_and_booking_waits_for_customer(self):
        iss = self.issue("safe_pass", "w07")
        self.assertEqual(len(self.e.store.quotes(iss["id"])), 3)
        book = self.step(iss, "book_service")
        self.assertEqual((book["state"], book["approval_role"]), ("awaiting_approval", "customer"))
        self.assertEqual(self.e.store.appointments(issue_id=iss["id"]), [])  # nothing booked before approval

    def test_approval_books_an_appointment_and_tracks_attendance(self):
        iss = self.issue("safe_pass", "w07")
        self.e.approve(self.step(iss, "book_service")["id"], by="Gráinne Murphy")
        appt = self.e.store.appointments(issue_id=iss["id"])[0]
        self.assertEqual(appt["status"], "requested")
        self.e.update_appointment(appt["id"], "attended", by="Ops")
        self.assertEqual(self.e.store.provider_stats()[appt["provider_id"]]["completed"], 1)

    def test_no_show_goes_back_to_customer_for_rebooking(self):
        iss = self.issue("safe_pass", "w07")
        self.e.approve(self.step(iss, "book_service")["id"], by="Gráinne Murphy")
        appt = self.e.store.appointments(issue_id=iss["id"])[0]
        self.e.update_appointment(appt["id"], "no_show", by="Ops", notes="Paddy did not turn up")
        book = self.step(iss, "book_service")
        self.assertEqual((book["state"], book["approved_by"]), ("awaiting_approval", None))
        self.assertEqual(self.e.store.provider_stats()[appt["provider_id"]]["no_show"], 1)

    def test_scheduler_asks_provider_what_happened_after_the_date(self):
        iss = self.issue("safe_pass", "w07")
        self.e.approve(self.step(iss, "book_service")["id"], by="Gráinne Murphy")
        appt = self.e.store.appointments(issue_id=iss["id"])[0]
        later = Engine(BREMORE, state_dir=self.tmp, today=date.fromisoformat(appt["date"]) + timedelta(days=1))
        self.assertIn((appt["id"], "provider asked whether it went ahead"), scheduler.follow_up_appointments(later))
        self.assertEqual(scheduler.follow_up_appointments(later), [])  # once only


# ---- 5. Subcontractors ---------------------------------------------------------------------
class Subcontractors(Base):
    def test_non_compliant_subcontractor_is_flagged_and_chased(self):
        iss = self.issue("subcontractor_public_liability", "sc02")
        self.assertEqual(iss["severity"], "critical")
        flag = (self.e.outbox / f"{iss['id']}.1-message.md").read_text()
        self.assertIn("Gráinne", flag)
        request = (self.e.outbox / f"{iss['id']}.2-message.md").read_text()
        self.assertIn("ops@sample-traffic.example.ie", request)

    def test_compliant_subcontractor_has_no_insurance_issue(self):
        self.assertFalse([i for i in self.e.store.issues() if i["holder"] == "sc01" and "liability" in i["requirement"]])

    def test_subcontractor_insured_name_checked(self):
        kb, c = self.e.kb, Customer.load(BREMORE)
        req = kb.requirements["subcontractor_public_liability"]
        self.assertTrue(review_document(req, {"holder": "sc01", "insured": "Wrong Name Ltd"}, c))


# ---- 6 and 8. Inspections, defects, corrective actions -------------------------------------------
class InspectionsAndCorrectiveActions(Base):
    def test_overdue_inspection_books_a_qualified_inspector_with_approval(self):
        iss = self.issue("lifting_accessories_examination", "a03")
        found = self.step(iss, "find_provider")["result"]
        self.assertEqual(found["recommended"]["id"], "p-le-1")  # p-le-2 doesn't cover Dublin
        self.assertEqual(self.step(iss, "book_service")["state"], "awaiting_approval")
        self.e.approve(self.step(iss, "book_service")["id"], by="Gráinne Murphy")
        appt = self.e.store.appointments(issue_id=iss["id"])[0]
        self.assertEqual(appt["kind"], "inspection")
        report = self.step(iss, "request_document")
        self.assertEqual(report["state"], "waiting")
        self.assertIn("jobs@sample-lifting.example.ie", (self.e.outbox / f"{report['id']}-message.md").read_text())

    def test_inspection_report_with_defects_opens_corrective_actions(self):
        iss = self.issue("lifting_accessories_examination", "a03")
        self.e.approve(self.step(iss, "book_service")["id"], by="Gráinne Murphy")
        events = self.e.ingest({"id": "insp-a03-new", "type": "lifting_accessories_examination", "holder": "a03",
                                "issued": "2026-11-15", "inspector": "Sample Lifting Inspections Ltd",
                                "result": "pass_with_defects", "defects": [{"description": "one sling tag missing", "severity": "minor"}]})
        self.assertEqual(self.e.store.issue(iss["id"])["status"], "resolved")
        self.assertTrue(any("corrective action opened" in what for _, what in events))
        self.assertTrue(any("sling tag" in a["title"] for a in self.e.corrective_actions("open")))

    def test_dangerous_defect_needs_evidence_then_reviewer_sign_off(self):
        ca = next(a for a in self.e.corrective_actions("open") if "seat belt" in a["title"])
        self.assertEqual(ca["severity"], "critical")
        self.assertEqual(ca["due"], "2026-11-13")
        ev = json.loads((BREMORE / "incoming" / "a07_repair_evidence.json").read_text())
        self.e.ingest(ev)
        self.assertNotEqual(self.e.store.issue(ca["id"])["status"], "resolved")
        close = self.step(ca, "close_action")
        self.assertEqual((close["state"], close["approval_role"]), ("awaiting_approval", "safety_reviewer"))
        self.e.approve(close["id"], by="Safety reviewer")
        self.assertEqual(self.e.store.issue(ca["id"])["status"], "resolved")
        self.assertEqual(self.e.store.issue(ca["id"])["proof"], "sample-ca-a07-repair")

    def test_evidence_without_content_is_rejected(self):
        ca = next(a for a in self.e.corrective_actions("open") if "tyre" in a["title"])
        self.e.ingest({"id": "empty-ev", "type": "corrective_action", "holder": "a02", "action": ca["id"]})
        self.assertNotEqual(self.e.store.issue(ca["id"])["status"], "resolved")

    def test_raise_action_with_owner_deadline_and_evidence(self):
        aid = self.e.raise_corrective_action("Guard rail missing at stair core", holder="company", owner="w01",
                                             severity="high", context="s1", evidence_required="photo of fixed rail",
                                             raised_by="Site visit", due="2026-11-14")
        self.e._advance_issue(aid)
        msg = (self.e.outbox / f"{aid}.1-message.md").read_text()
        self.assertIn("Declan Murphy", msg)  # owner w01, via WhatsApp
        self.assertIn("2026-11-14", msg)
        self.assertIn("photo of fixed rail", msg)
        self.assertIn("corrective_action_raised", [a["event"] for a in self.e.store.audit_rows()])

    def test_rescan_never_closes_a_corrective_action(self):
        aid = self.e.raise_corrective_action("Tidy compound", raised_by="ops")
        self.e.scan()
        self.assertNotEqual(self.e.store.issue(aid)["status"], "resolved")

    def test_overdue_action_reminds_owner_and_escalates_once(self):
        aid = self.e.raise_corrective_action("Replace first aid kit", owner="company", due="2026-11-12", raised_by="ops")
        self.e._advance_issue(aid)
        later = Engine(BREMORE, state_dir=self.tmp, today=date(2026, 11, 14))
        events = scheduler.chase_overdue_actions(later)
        self.assertIn(aid, [ref for ref, _ in events])
        self.assertEqual(later.store.issue(aid)["status"], "escalated")
        self.assertNotIn(aid, [ref for ref, _ in scheduler.chase_overdue_actions(later)])


# ---- 9. Communication ------------------------------------------------------------------------
class Communication(Base):
    def test_every_message_is_in_the_history(self):
        comms = self.e.store.comms()
        self.assertGreater(len(comms), 30)
        self.assertEqual(len(comms), len([c for c in comms if c["outbox"]]))
        self.assertTrue(all(c["status"].startswith(("queued_in_outbox", "internal")) for c in comms))

    def test_email_sent_through_smtp_when_turned_on(self):
        sent = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=None): sent.append(("connect", host, port))
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): pass
            def login(self, u, p): sent.append(("login", u))
            def send_message(self, msg): sent.append(("send", msg["To"], msg["Subject"]))

        env = {"EMAIL_MODE": "smtp", "SMTP_HOST": "smtp.example.ie", "SMTP_USER": "ops", "SMTP_PASSWORD": "x",
               "EMAIL_FROM": "ops@example.ie", "OPSENGINE_ALLOW_SEND_IN_TESTS": "true"}
        with mock.patch.dict(os.environ, env), mock.patch.object(connectors.smtplib, "SMTP", FakeSMTP):
            self.assertEqual(connectors.send("email", "owner@x.example.ie", "Hi", "Body"), "sent")
            self.assertTrue(connectors.send("whatsapp", "+353", "Hi", "Body").startswith("queued_in_outbox (no whatsapp"))
        self.assertIn(("send", "owner@x.example.ie", "Hi"), sent)

    def test_inbound_documents_are_logged(self):
        self.e.ingest(json.loads((BREMORE / "incoming" / "new_pi_certificate.json").read_text()))
        self.assertTrue(any(c["direction"] == "in" for c in self.e.store.comms()))


# ---- 10. Reporting and audit ---------------------------------------------------------------
class RecordsAndAudit(Base):
    def test_export_has_everything_an_auditor_needs(self):
        out = export_records(self.e, self.tmp / "export")
        for name in ("compliance_register.csv", "issues.csv", "actions.csv", "communications.csv",
                     "appointments.csv", "quotes.csv", "audit_log.csv", "documents.json", "README.txt"):
            self.assertTrue((out / name).exists(), name)
        self.assertIn("hash chain: intact", (out / "README.txt").read_text())
        self.assertIn("does not certify compliance", (out / "README.txt").read_text())
        with open(out / "compliance_register.csv", encoding="utf-8") as f:
            self.assertGreater(len(list(csv.DictReader(f))), 50)

    def test_issue_history_shows_ai_and_human_actions(self):
        iss = self.issue("safe_pass", "w07")
        self.e.approve(self.step(iss, "book_service")["id"], by="Gráinne Murphy")
        h = self.e.issue_history(iss["id"])
        actors = {a["actor"] for a in h["audit"]}
        self.assertIn("engine", actors)
        self.assertIn("human:Gráinne Murphy", actors)
        self.assertTrue(h["comms"])
        self.assertTrue(h["appointments"])

    def test_audit_chain_intact_after_everything(self):
        self.assertTrue(self.e.store.verify_audit()[0])


# ---- 11. Continuous improvement --------------------------------------------------------------
class Insights(Base):
    def test_patterns_and_recommendations(self):
        liffey = Engine(SAMPLE, state_dir=self.tmp / "l", today=TODAY)
        liffey.scan()
        r = insights([self.e, liffey])
        self.assertEqual(r["issues_total"], len(self.e.store.issues()) + len(liffey.store.issues()))
        self.assertEqual(r["most_common_problems"][0][0], "SOLAS Safe Pass")
        self.assertIn("SOLAS Safe Pass", dict(r["frequently_missing"]))
        self.assertTrue(any("Clongriffin" in name for name, _ in r["hotspots"]))
        self.assertTrue(any("Safe Pass" in rec for rec in r["recommendations"]))

    def test_unreliable_provider_flagged(self):
        for req, holder in (("safe_pass", "w07"), ("safe_pass", "w16")):
            iss = self.issue(req, holder)
            self.e.approve(self.step(iss, "book_service")["id"], by="Owner")
            appt = self.e.store.appointments(issue_id=iss["id"])[0]
            self.e.store.update_appointment(appt["id"], status="no_show")
        self.assertTrue(any("completed only 0 of 2" in rec for rec in insights([self.e])["recommendations"]))


# ---- Boundaries still hold across the new capabilities --------------------------------------------
class Boundaries(unittest.TestCase):
    def test_every_booking_and_insurance_change_needs_customer_approval(self):
        kb = Knowledge.load()
        for rid, book in kb.playbooks.items():
            for steps in book.values() if isinstance(book, dict) else []:
                for st in steps:
                    if st["action"] == "book_service" or st.get("template") == "insurance_limit_increase":
                        self.assertEqual(st.get("approval"), "customer", rid)

    def test_new_providers_and_contractors_are_sample(self):
        self.assertTrue(json.loads((ROOT / "data" / "providers.json").read_text())["sample"])

    def test_engine_never_claims_to_certify(self):
        texts = json.dumps(Knowledge.load().templates).lower()
        for phrase in ("we certify", "is certified compliant", "we confirm compliance"):
            self.assertNotIn(phrase, texts)


if __name__ == "__main__":
    unittest.main()
