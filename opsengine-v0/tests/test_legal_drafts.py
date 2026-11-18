"""Legal drafts are drafts: labelled on every file, and nothing in the product treats them as approved."""
import json
import unittest

from opsengine import gdpr
from opsengine.knowledge import ROOT

LEGAL = ROOT / "docs" / "legal"
BANNER = "**DRAFT – AWAITING APPROVAL FROM AN IRISH DATA PROTECTION SOLICITOR.**"
EXPECTED = {"README.md", "data-processing-agreement.md", "worker-privacy-notice-template.md", "opsengine-privacy-notice.md",
            "whatsapp-opt-in-wording.md", "records-of-processing.md", "model-dpia.md", "legitimate-interests-assessments.md",
            "breach-procedure.md", "dpo-assessment.md", "sub-processor-change-notice.md"}


class LegalDrafts(unittest.TestCase):
    def test_every_draft_is_labelled_as_awaiting_a_solicitor(self):
        files = {f.name for f in LEGAL.glob("*.md")}
        self.assertEqual(files, EXPECTED)
        for f in LEGAL.glob("*.md"):
            text = f.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("> " + BANNER), f.name)
            self.assertIn("Not approved for use with real customers or workers", text, f.name)

    def test_drafts_never_claim_approval_and_deletion_stays_off(self):
        for f in LEGAL.glob("*.md"):
            low = f.read_text(encoding="utf-8").lower()
            for claim in ("approved by our solicitor", "has been approved", "solicitor-approved", "legally approved"):
                self.assertNotIn(claim, low, f.name)
        self.assertFalse(gdpr.retention()["solicitor_confirmed"])
        inv = json.loads((ROOT / "docs" / "data-inventory.json").read_text())
        self.assertIn("awaiting solicitor confirmation", inv["status"])


if __name__ == "__main__":
    unittest.main()
