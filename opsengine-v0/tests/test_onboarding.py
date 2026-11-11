import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SAMPLE

from opsengine import onboarding
from opsengine.knowledge import ROOT


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_sample_customer_is_complete(self):
        self.assertEqual(onboarding.check_customer(SAMPLE), [])

    def test_new_customer_copies_template_and_lists_what_is_missing(self):
        dest = onboarding.create_customer("acme_drylining", "Acme Drylining Ltd", root=self.tmp)
        self.assertEqual({p.name for p in dest.iterdir()}, {p.name for p in onboarding.TEMPLATE.iterdir()})
        company = json.loads((dest / "company.json").read_text())
        self.assertEqual((company["id"], company["name"]), ("acme_drylining", "Acme Drylining Ltd"))
        problems = onboarding.check_customer(dest)
        self.assertTrue(any("owner.name still needs filling in" in p for p in problems))
        self.assertTrue(any("has no rules file" in p for p in problems))
        with self.assertRaises(FileExistsError):
            onboarding.create_customer("acme_drylining", "Again", root=self.tmp)

    def test_check_catches_bad_references(self):
        dest = self.tmp / "c"
        shutil.copytree(SAMPLE, dest)
        docs = json.loads((dest / "documents.json").read_text())
        docs.append({"id": "d-x", "type": "safe_pass", "holder": "w99", "number": "1", "expires": "31/12/2027"})
        (dest / "documents.json").write_text(json.dumps(docs))
        problems = onboarding.check_customer(dest)
        self.assertTrue(any("w99" in p for p in problems))
        self.assertTrue(any("not a date" in p for p in problems))

    def test_bad_id_rejected(self):
        with self.assertRaises(ValueError):
            onboarding.create_customer("Acme Ltd", "Acme", root=self.tmp)

    def test_real_customer_folders_are_git_ignored(self):
        ignore = (ROOT / ".gitignore").read_text()
        self.assertIn("data/customers/*", ignore)
        self.assertIn("!data/customers/_template/", ignore)


if __name__ == "__main__":
    unittest.main()
