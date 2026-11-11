"""The operations engine: detect -> plan -> act -> verify -> record.

Every problem found becomes an issue with a plan (playbook steps). The engine advances each
plan as far as it can on its own, stops at approval gates and at steps waiting for proof,
re-checks proof against the rules, and logs every move in the audit trail."""
import json
from datetime import date
from pathlib import Path

from .actions import EXECUTORS, ActionContext
from .detect import _best_doc, detect
from .knowledge import ROOT, Customer, Knowledge
from .store import Store, now_iso

DONE = ("done", "skipped")
STOPS = ("awaiting_approval", "waiting", "blocked", "rejected")


class Engine:
    def __init__(self, customer_dir, state_dir=None, today=None, kb_root=ROOT):
        self.kb = Knowledge.load(kb_root)
        self.customer = Customer.load(customer_dir)
        cid = self.customer.company["id"]
        base = Path(state_dir or ROOT / "state") / cid
        self.store = Store(base / "state.db")
        self.outbox = base / "outbox"
        self.today = today or date.today()
        if not self.store.has_documents():
            for d in self.customer.seed_documents:
                self.store.add_document(d, source="onboarding")

    # ---------------- detect + plan ----------------
    def scan(self):
        findings = detect(self.kb, self.customer, self.store.documents(), self.today)
        seen, opened, updated = set(), [], []
        for f in findings:
            seen.add(f["key"])
            data = json.dumps({k: f.get(k) for k in ("doc_id", "expires", "field", "current_value", "required_value")})
            existing = self.store.open_issue_by_key(f["key"])
            if existing:
                if (existing["kind"], existing["detail"]) != (f["kind"], f["detail"]):
                    self.store.update_issue(existing["id"], kind=f["kind"], severity=f["severity"],
                                            detail=f["detail"], data=data)
                    self.store.audit("engine", "issue_updated", existing["id"], {"kind": f["kind"], "detail": f["detail"]})
                    updated.append(existing["id"])
                continue
            issue_id = self.store.next_issue_id()
            ts = now_iso()
            self.store.insert_issue({
                "id": issue_id, "key": f["key"], "requirement": f["requirement"], "holder": f["holder"],
                "context": f["context"], "category": f["category"], "kind": f["kind"], "severity": f["severity"],
                "status": "open", "detail": f["detail"], "required_by": json.dumps(f["required_by"]),
                "data": data, "created_at": ts, "updated_at": ts, "resolved_at": None, "proof": None,
            })
            for seq, spec in enumerate(self.kb.playbook_for(f["requirement"], f["category"]), start=1):
                self.store.insert_step({
                    "id": f"{issue_id}.{seq}", "issue_id": issue_id, "seq": seq, "action": spec["action"],
                    "spec": json.dumps(spec), "state": "pending", "approval_role": spec.get("approval"),
                    "approved_by": None, "approved_at": None, "result": None, "updated_at": ts,
                })
            self.store.audit("engine", "issue_opened", issue_id,
                             {"requirement": f["requirement"], "holder": f["holder"], "kind": f["kind"],
                              "severity": f["severity"], "detail": f["detail"]})
            opened.append(issue_id)
        closed = []
        for issue in self.store.issues("open"):
            if issue["key"] not in seen:
                self._resolve(issue, proof=issue["proof"] or "no longer detected on rescan", actor="engine")
                closed.append(issue["id"])
        return {"opened": opened, "updated": updated, "closed": closed, "findings": len(findings)}

    # ---------------- act ----------------
    def advance(self):
        events = []
        for issue in self.store.issues("open"):
            events += self._advance_issue(issue["id"])
        return events

    def _advance_issue(self, issue_id):
        events = []
        while True:
            issue = self.store.issue(issue_id)
            if issue["status"] not in ("open", "in_progress", "escalated"):
                return events
            steps = self.store.steps(issue_id)
            prior = {s["action"]: s["result"] for s in steps if s["state"] in DONE and s["result"]}
            nxt = next((s for s in steps if s["state"] not in DONE), None)
            if nxt is None:
                self._resolve(issue, proof=issue["proof"], actor="engine")
                events.append((issue_id, "resolved"))
                return events
            if nxt["state"] in STOPS:
                return events
            if nxt["approval_role"] and not nxt["approved_by"]:
                self.store.update_step(nxt["id"], state="awaiting_approval")
                self.store.audit("engine", "approval_requested", nxt["id"],
                                 {"role": nxt["approval_role"], "summary": self.approval_summary(nxt, prior)})
                events.append((nxt["id"], "awaiting_approval"))
                return events
            if issue["status"] == "open":
                self.store.update_issue(issue_id, status="in_progress")
            if nxt["action"] == "verify":
                events += self._verify(issue, nxt, steps)
                continue
            ctx = ActionContext(self.kb, self.customer, self.store, issue, nxt, prior, self.outbox, self.today)
            result = EXECUTORS[nxt["action"]](ctx)
            if result.get("status") in ("blocked", "no_provider"):
                self.store.update_step(nxt["id"], state="blocked", result=json.dumps(result))
                self.store.update_issue(issue_id, status="escalated")
                self.store.audit("engine", "step_blocked", nxt["id"], result)
                events.append((nxt["id"], "blocked"))
                return events
            waits = nxt["spec"].get("waits_for")
            self.store.update_step(nxt["id"], state="waiting" if waits else "done", result=json.dumps(result))
            self.store.audit("engine", "action_taken", nxt["id"],
                             {"action": nxt["action"], "approved_by": nxt["approved_by"], "result": result})
            events.append((nxt["id"], nxt["action"]))
            if waits:
                return events

    # ---------------- verify ----------------
    def _verify(self, issue, verify_step, steps):
        still_failing = [f for f in detect(self.kb, self.customer, self.store.documents(), self.today)
                         if f["key"] == issue["key"]]
        if not still_failing:
            req = self.kb.requirements[issue["requirement"]]
            ctx = issue["context"] if req["scope"] in ("site", "worker_site") else None
            doc = _best_doc(self.store.documents(), issue["requirement"], issue["holder"], ctx)
            proof = doc["id"] if doc else None
            self.store.update_issue(issue["id"], proof=proof)
            self.store.update_step(verify_step["id"], state="done", result=json.dumps({"verified": True, "proof": proof}))
            self.store.audit("engine", "verified", verify_step["id"], {"proof": proof})
            return [(verify_step["id"], "verified")]
        # Proof didn't satisfy the rule: say why, and ask again by re-running the last request step.
        waiter = [s for s in steps if s["spec"].get("waits_for") and s["seq"] < verify_step["seq"]][-1]
        reason = still_failing[0]["detail"]
        received_id = (self.store.step(waiter["id"])["result"] or {}).get("received")
        received = next((d for d in self.store.documents() if d["id"] == received_id), None)
        if received:
            req = self.kb.requirements[issue["requirement"]]
            gaps = [f for f in req.get("required_fields", []) if received.get(f) in (None, "", [])]
            if gaps:
                reason = f"received document {received_id} is missing: {', '.join(gaps)}"
            elif received.get("expires") and received["expires"] <= (still_failing[0].get("expires") or ""):
                reason = f"received document {received_id} is not newer than the one on file"
        self.store.update_step(waiter["id"], state="pending", result=json.dumps({"retry_reason": reason}))
        self.store.audit("engine", "verification_failed", verify_step["id"], {"reason": reason, "retry_step": waiter["id"]})
        return [(verify_step["id"], f"verification_failed: {reason}")]

    def _resolve(self, issue, proof, actor):
        self.store.update_issue(issue["id"], status="resolved", resolved_at=now_iso(), proof=proof)
        self.store.audit(actor, "issue_resolved", issue["id"], {"proof": proof})

    # ---------------- humans in the loop ----------------
    def approval_summary(self, step, prior=None):
        issue = self.store.issue(step["issue_id"])
        req = self.kb.requirements[issue["requirement"]]
        who = self.customer.holder_name(issue["holder"])
        prior = prior or {}
        if step["action"] == "book_service" and prior.get("find_provider", {}).get("recommended"):
            p = prior["find_provider"]["recommended"]
            return f"Book {who} with {p['name']} for EUR {p['price_eur']} ({p['lead_days']} days lead time) - {req['name']}"
        if step["action"] == "request_signature":
            if "draft_document" in prior:
                return f"Review the draft {req['name']} for {who} and release it for signature"
            return f"Send the {req['name']} to {who} for signature"
        if step["action"] == "request_document":
            return f"Ask {step['spec'].get('from')} to act on {req['name']} for {who}: {issue['detail']}"
        return f"{step['action']} for {req['name']} ({who})"

    def approval_queue(self):
        out = []
        for s in self.store.steps(state="awaiting_approval"):
            prior = {p["action"]: p["result"] for p in self.store.steps(s["issue_id"]) if p["state"] in DONE and p["result"]}
            out.append({"step": s["id"], "role": s["approval_role"], "summary": self.approval_summary(s, prior)})
        return out

    def approve(self, step_id, by):
        s = self.store.step(step_id)
        if not s or s["state"] != "awaiting_approval":
            raise ValueError(f"{step_id} is not awaiting approval")
        self.store.update_step(step_id, state="pending", approved_by=by, approved_at=now_iso())
        self.store.audit(f"human:{by}", "approved", step_id, {"role": s["approval_role"]})
        return self._advance_issue(s["issue_id"])

    def reject(self, step_id, by, reason):
        s = self.store.step(step_id)
        if not s or s["state"] != "awaiting_approval":
            raise ValueError(f"{step_id} is not awaiting approval")
        self.store.update_step(step_id, state="rejected", result=json.dumps({"rejected_by": by, "reason": reason}))
        self.store.update_issue(s["issue_id"], status="escalated")
        self.store.audit(f"human:{by}", "rejected", step_id, {"reason": reason})

    # ---------------- inbound proof ----------------
    def ingest(self, doc, source="inbound"):
        self.store.add_document(doc, source=source, actor=f"inbound:{doc.get('received_via', source)}")
        events = []
        for issue in self.store.issues("open"):
            if issue["requirement"] != doc["type"] or issue["holder"] != doc["holder"]:
                continue
            scope = self.kb.requirements[issue["requirement"]]["scope"]
            if scope in ("site", "worker_site") and issue["context"] != doc.get("context"):
                continue
            steps = self.store.steps(issue["id"])
            waiter = next((s for s in steps if s["spec"].get("waits_for") and s["state"] not in DONE), None)
            if not waiter:
                continue
            for s in steps:
                if s["seq"] < waiter["seq"] and s["state"] not in DONE:
                    self.store.update_step(s["id"], state="skipped", result=json.dumps({"reason": "proof arrived early"}))
                    self.store.audit("engine", "step_skipped", s["id"], {"reason": "proof arrived early"})
            self.store.update_step(waiter["id"], state="done", result=json.dumps({"received": doc["id"]}))
            self.store.audit("engine", "proof_received", waiter["id"], {"document": doc["id"]})
            events.append((waiter["id"], "proof_received"))
            events += self._advance_issue(issue["id"])
        return events
