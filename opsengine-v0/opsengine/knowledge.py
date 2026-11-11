"""Loads the engine's knowledge: rules library, main contractor profiles, playbooks,
message templates, provider network, and a customer's company data."""
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LANGUAGE_NAMES = {"en": "English", "pt": "Portuguese", "ro": "Romanian", "pl": "Polish",
                  "lt": "Lithuanian", "es": "Spanish", "uk": "Ukrainian", "ar": "Arabic", "so": "Somali"}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Knowledge:
    requirements: dict
    main_contractors: dict
    playbooks: dict
    templates: dict
    providers: list

    @classmethod
    def load(cls, root=ROOT):
        root = Path(root)
        reqs = {r["id"]: r for r in _load(root / "rules" / "requirements.json")["requirements"]}
        mcs = {}
        for p in sorted((root / "rules" / "main_contractors").glob("*.json")):
            mc = _load(p)
            mcs[mc["id"]] = mc
        return cls(
            requirements=reqs,
            main_contractors=mcs,
            playbooks=_load(root / "playbooks" / "playbooks.json"),
            templates=_load(root / "templates" / "messages.json"),
            providers=_load(root / "data" / "providers.json")["providers"],
        )

    def playbook_for(self, requirement_id, category):
        book = self.playbooks.get(requirement_id, {})
        return book.get(category) or self.playbooks["_default"][category]


@dataclass
class Customer:
    company: dict
    workers: dict
    seed_documents: list = field(default_factory=list)
    path: Path = None

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        company = _load(folder / "company.json")
        workers = {w["id"]: w for w in _load(folder / "workers.json")}
        docs = _load(folder / "documents.json") if (folder / "documents.json").exists() else []
        return cls(company=company, workers=workers, seed_documents=docs, path=folder)

    @property
    def sites(self):
        return {s["id"]: s for s in self.company.get("sites", [])}

    def holder_name(self, holder):
        if holder == "company":
            return self.company["name"]
        return self.workers.get(holder, {}).get("name", holder)

    def worker_sites(self, worker_id):
        return [s for s in self.company.get("sites", []) if worker_id in s.get("workers", [])]

    def main_contractors_for(self, holder, context=None, kb=None):
        """Main contractors that will receive this holder's documents."""
        sites = self.sites
        if context and context in sites:
            return [sites[context]["main_contractor"]]
        if context and kb and context in kb.main_contractors:
            return [context]
        if holder == "company":
            return sorted({s["main_contractor"] for s in sites.values()})
        return sorted({s["main_contractor"] for s in self.worker_sites(holder)})
