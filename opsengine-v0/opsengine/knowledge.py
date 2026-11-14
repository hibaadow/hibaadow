"""Loads the engine's knowledge: rules library, main contractor profiles, playbooks,
message templates, provider network, and a customer's company data."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from .labels import Wording

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
    wording: "Wording" = None

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
            wording=Wording.load(root),
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
        assets = {a["id"]: a for a in _load(folder / "assets.json")} if (folder / "assets.json").exists() else {}
        return cls(company=company, workers=workers, seed_documents=docs, path=folder, assets=assets)

    assets: dict = field(default_factory=dict)  # plant, equipment and site facilities that need inspection

    @property
    def sites(self):
        return {s["id"]: s for s in self.company.get("sites", [])}

    @property
    def subcontractors(self):
        """The customer's own subcontractors (spec section 5)."""
        return {s["id"]: s for s in self.company.get("subcontractors", [])}

    def holder_kind(self, holder):
        if holder == "company":
            return "company"
        if holder in self.workers:
            return "worker"
        if holder in self.subcontractors:
            return "subcontractor"
        if holder in self.assets:
            return "asset"
        return "unknown"

    def holder_name(self, holder):
        if holder == "company":
            return self.company["name"]
        for group in (self.workers, self.subcontractors, self.assets):
            if holder in group:
                return group[holder].get("name", holder)
        return holder

    def holder_sites(self, holder):
        """Sites a worker, subcontractor or asset is on."""
        if holder in self.workers:
            return self.worker_sites(holder)
        group = self.subcontractors.get(holder) or self.assets.get(holder) or {}
        return [self.sites[s] for s in group.get("sites", []) if s in self.sites]

    def area_for(self, holder, context=None):
        """Where the work happens, for matching providers by service area."""
        if context in self.sites:
            return self.sites[context].get("area")
        for s in self.holder_sites(holder):
            if s.get("area"):
                return s["area"]
        return self.company.get("area")

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
        return sorted({s["main_contractor"] for s in self.holder_sites(holder)})
