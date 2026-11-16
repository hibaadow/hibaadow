"""Versioned rules (AUDIT.md Phase 2).

The rules version is a fingerprint of everything that decides what counts as a problem and how it
is fixed: rules/requirements.json, rules/main_contractors/*.json and playbooks/playbooks.json.
Change any of them and the version changes. Every finding records the version that produced it.

rules/versions.json lists known versions with a note and, once a competent person has checked
them, who signed them off and when. With OPSENGINE_REQUIRE_SIGNED_RULES=true the daily run refuses
to use rules nobody has signed off."""
import hashlib
import json
from datetime import date
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent


def rule_files(root=ROOT):
    root = Path(root)
    return ([root / "rules" / "requirements.json"] + sorted((root / "rules" / "main_contractors").glob("*.json"))
            + [root / "playbooks" / "playbooks.json"])


def current_version(root=ROOT):
    h = hashlib.sha256()
    for f in rule_files(root):
        h.update(f.relative_to(root).as_posix().encode() + b"\0")
        h.update(json.dumps(json.loads(f.read_text(encoding="utf-8")), sort_keys=True).encode() + b"\0")
    return "r-" + h.hexdigest()[:12]


def _path(root=ROOT):
    return Path(root) / "rules" / "versions.json"


def load(root=ROOT):
    p = _path(root)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"versions": []}


def _save(data, root=ROOT):
    _path(root).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find(version, root=ROOT):
    return next((v for v in load(root)["versions"] if v["id"] == version), None)


def register(note, root=ROOT):
    data = load(root)
    vid = current_version(root)
    if any(v["id"] == vid for v in data["versions"]):
        return vid, False
    data["versions"].append({"id": vid, "registered_on": date.today().isoformat(), "note": note, "sign_off": None,
                             "files": [f.relative_to(Path(root)).as_posix() for f in rule_files(root)]})
    _save(data, root)
    return vid, True


def sign_off(version, by, qualification, root=ROOT):
    if not by.strip() or not qualification.strip():
        raise ValueError("give the competent person's name and qualification")
    data = load(root)
    v = next((v for v in data["versions"] if v["id"] == version), None)
    if not v:
        raise ValueError(f"{version} is not registered; run `rules register` first")
    v["sign_off"] = {"by": by.strip(), "qualification": qualification.strip(), "on": date.today().isoformat()}
    _save(data, root)
    return v


def status(root=ROOT):
    vid = current_version(root)
    v = find(vid, root)
    return {"current": vid, "registered": bool(v), "signed_off": bool(v and v.get("sign_off")),
            "sign_off": (v or {}).get("sign_off"), "note": (v or {}).get("note")}


def check_allowed(root=ROOT):
    """Raise if production requires signed-off rules and the current rules aren't."""
    s = status(root)
    if config.flag("OPSENGINE_REQUIRE_SIGNED_RULES") and not s["signed_off"]:
        raise PermissionError(f"Rules version {s['current']} has not been signed off by a competent person "
                              "(OPSENGINE_REQUIRE_SIGNED_RULES is on). Run `opsengine rules status`.")
    return s
