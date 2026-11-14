import json
import re
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from helpers import SAMPLE

from opsengine import onboarding, scheduler
from opsengine.detect import detect
from opsengine.engine import Engine
from opsengine.knowledge import ROOT, Customer, Knowledge

BREMORE = ROOT / "data" / "sample" / "bremore_groundworks"
GLENMARA = "glenmara_construction_sample"
FORM = ROOT / "rules" / "main_contractors" / "forms" / "glenmara_construction_SAMPLE_PQQ.md"
TODAY = date(2026, 11, 11)


class SampleDataIsMarked(unittest.TestCase):
    def test_customer_contractor_and_form_say_sample(self):
        company = json.loads((BREMORE / "company.json").read_text())
        self.assertTrue(company["sample"])
        self.assertIn("(SAMPLE)", company["name"])
        self.assertTrue(all(s["name"].startswith("SAMPLE") for s in company["sites"]))
        mc = json.loads((ROOT / "rules" / "main_contractors" / f"{GLENMARA}.json").read_text())
        self.assertTrue(mc["sample"])
        self.assertIn("SAMPLE", mc["name"])
        self.assertIn("SAMPLE DOCUMENT - NOT A REAL FORM", FORM.read_text())
        self.assertIn("SAMPLE DATA - FICTIONAL", (BREMORE / "README.md").read_text())

    def test_every_sample_folder_and_contractor_is_flagged(self):
        for folder in (ROOT / "data" / "sample").iterdir():
            if (folder / "company.json").exists():
                self.assertTrue(json.loads((folder / "company.json").read_text()).get("sample"), folder.name)
        for f in (ROOT / "rules" / "main_contractors").glob("*.json"):
            self.assertTrue(json.loads(f.read_text()).get("sample"), f.name)

    def test_contacts_are_fictional(self):
        text = "".join((BREMORE / n).read_text() for n in ("company.json", "workers.json"))
        for email in re.findall(r"[\w.+-]+@[\w.-]+", text):
            self.assertTrue(email.endswith(".example.ie"), email)
        for phone in re.findall(r"\+353[\d ]+", text):
            self.assertTrue(phone.startswith("+353 87 000 "), phone)


class GlenmaraFormRules(unittest.TestCase):
    def setUp(self):
        self.kb = Knowledge.load()
        self.findings = {f["key"]: f for f in detect(self.kb, Customer.load(BREMORE),
                                                     Customer.load(BREMORE).seed_documents, TODAY)}

    def kinds(self):
        return {(f["requirement"], f["holder"], f["kind"]) for f in self.findings.values()}

    def test_designed_gaps_are_found(self):
        k = self.kinds()
        for expected in [("professional_indemnity", "company", "missing"),
                         ("safety_certification", "company", "expiring"),
                         ("accident_incident_history", "company", "expired"),
                         ("trade_references", "company", "incomplete"),
                         ("tax_clearance", "company", "expiring"),
                         ("rams", "company", "missing"),
                         ("cscs_excavator", "w03", "expired"),
                         ("cscs_slinger_signaller", "w08", "missing"),
                         ("safe_pass", "w07", "expired"),
                         ("safe_pass", "w16", "missing"),
                         ("manual_handling", "w11", "missing"),
                         ("written_terms", "w16", "incomplete")]:
            self.assertIn(expected, k)
        self.assertEqual(len(self.findings), 19)

    def test_public_liability_checked_against_each_contractor(self):
        pl = sorted((f["context"], f["required_value"]) for f in self.findings.values()
                    if f["requirement"] == "public_liability")
        self.assertEqual(pl, [(GLENMARA, 13000000), ("harbour_construction", 10000000)])

    def test_contractor_only_rules_apply_only_where_asked(self):
        pi = self.findings["professional_indemnity|company|-|validity"]
        self.assertEqual(pi["required_by"], [GLENMARA])
        # manual handling only for Glenmara-site workers: w13-w16 are on the Harbour site only
        mh = {f["holder"] for f in self.findings.values() if f["requirement"] == "manual_handling"}
        self.assertEqual(mh, {"w11", "w12"})
        # the existing sample firm has no Glenmara site, so none of these rules touch it
        liffey = detect(self.kb, Customer.load(SAMPLE), Customer.load(SAMPLE).seed_documents, TODAY)
        new = {"company_details", "professional_indemnity", "safety_certification",
               "accident_incident_history", "trade_references"}
        self.assertFalse(new & {f["requirement"] for f in liffey})

    def test_only_safe_t_cert_or_ciri_accepted(self):
        docs = [dict(d) for d in Customer.load(BREMORE).seed_documents]
        cert = next(d for d in docs if d["type"] == "safety_certification")
        cert.update(scheme="ISO 45001", expires="2028-01-01")
        found = [f for f in detect(self.kb, Customer.load(BREMORE), docs, TODAY)
                 if f["requirement"] == "safety_certification"]
        self.assertEqual(len(found), 1)
        self.assertIn("not accepted", found[0]["detail"])

    def test_rules_library_is_consistent(self):
        """Every requirement has a playbook path, every template and provider category exists."""
        for mc in self.kb.main_contractors.values():
            for rid in mc.get("extra_requirements", []) + list(mc.get("field_minimums", {})):
                self.assertIn(rid, self.kb.requirements, mc["id"])
        for rid, book in self.kb.playbooks.items():
            if rid.startswith("_"):
                continue
            self.assertIn(rid, self.kb.requirements, rid)
            for steps in book.values():
                for step in steps:
                    if "template" in step:
                        self.assertIn(step["template"], self.kb.templates, f"{rid}: {step['template']}")
                    if step["action"] == "find_provider":
                        self.assertTrue(any(p["category"] == step["category"] for p in self.kb.providers), step["category"])
                    if step["action"] in ("book_service",) or (step.get("template") or "").startswith("insurance_limit_increase"):
                        self.assertEqual(step.get("approval"), "customer", f"{rid}: money needs customer approval")


class SamplePilotLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = Engine(BREMORE, state_dir=self.tmp, today=TODAY)
        self.e.scan()
        self.e.advance()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def issue(self, req, context=None):
        return next(i for i in self.e.store.issues() if i["requirement"] == req and (context is None or i["context"] == context))

    def test_insurance_increase_waits_for_customer(self):
        iss = self.issue("public_liability", GLENMARA)
        step = next(s for s in self.e.store.steps(iss["id"]) if s["action"] == "request_document")
        self.assertEqual((step["state"], step["approval_role"]), ("awaiting_approval", "customer"))

    def test_new_pi_certificate_closes_issue_and_goes_only_to_glenmara(self):
        iss = self.issue("professional_indemnity")
        self.e.ingest(json.loads((BREMORE / "incoming" / "new_pi_certificate.json").read_text()))
        self.assertEqual(self.e.store.issue(iss["id"])["status"], "resolved")
        sent = sorted(p.name for p in self.e.outbox.glob(f"{iss['id']}.*-distribute-*"))
        self.assertEqual(sent, [f"{iss['id']}.3-distribute-{GLENMARA}.md"])

    def test_messages_render_for_new_requirements(self):
        hist = self.issue("accident_incident_history")
        text = (self.e.outbox / f"{hist['id']}.1-message.md").read_text()
        self.assertIn("Glenmara Construction", text)
        self.assertIn("lost-time injuries", text)
        andriy = next(i for i in self.e.store.issues() if i["requirement"] == "safe_pass" and i["holder"] == "w16")
        self.assertIn("TRANSLATION NEEDED: Ukrainian", (self.e.outbox / f"{andriy['id']}.1-message.md").read_text())

    def test_plant_card_booking_needs_approval(self):
        iss = self.issue("cscs_excavator")
        states = {s["action"]: (s["state"], s["approval_role"]) for s in self.e.store.steps(iss["id"])}
        self.assertEqual(states["book_service"], ("awaiting_approval", "customer"))

    def test_audit_intact(self):
        self.assertTrue(self.e.store.verify_audit()[0])


class SampleAndRealStayApart(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.customers = self.tmp / "customers"
        self.customers.mkdir()
        self.p1 = mock.patch.object(onboarding, "CUSTOMERS", self.customers)
        self.p2 = mock.patch.object(scheduler, "CUSTOMERS_ROOT", self.customers)
        self.p1.start(); self.p2.start()

    def tearDown(self):
        self.p1.stop(); self.p2.stop()
        shutil.rmtree(self.tmp)

    def test_sample_customer_passes_check(self):
        self.assertEqual(onboarding.check_customer(BREMORE), [])

    def test_sample_copied_into_real_customers_is_refused(self):
        dest = self.customers / "bremore"
        shutil.copytree(BREMORE, dest)
        self.assertTrue(any("SAMPLE data" in p for p in onboarding.check_customer(dest)))
        with self.assertRaises(ValueError):
            scheduler.run_customer(dest, state_dir=self.tmp / "state", today=TODAY)
        r = scheduler.daily_run(scheduler.customer_folders(self.customers), state_dir=self.tmp / "state", today=TODAY)
        self.assertEqual(r[0]["status"], "failed")

    def test_real_customer_using_sample_contractor_rules_is_flagged(self):
        dest = self.customers / "real_co"
        shutil.copytree(BREMORE, dest)
        company = json.loads((dest / "company.json").read_text())
        company.pop("sample")
        company["name"] = "Real Co Ltd"
        (dest / "company.json").write_text(json.dumps(company))
        problems = onboarding.check_customer(dest)
        self.assertTrue(any("SAMPLE main contractor rules" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
