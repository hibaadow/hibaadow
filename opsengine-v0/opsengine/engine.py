"""The operations engine: detect -> plan -> act -> verify -> record.

Every problem found becomes an issue with a plan (playbook steps). The engine advances each
plan as far as it can on its own, stops at approval gates and at steps waiting for proof,
re-checks proof against the rules, and logs every move in the audit trail."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from . import vision
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
        self.evidence_dir = base / "evidence"
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
        opened += self._raise_defect_actions()
        closed = []
        for issue in self.store.issues("open"):
            if self._is_manual(issue):
                continue  # corrective actions close only with evidence, never because a rescan stopped seeing them
            if issue["key"] not in seen:
                self._resolve(issue, proof=issue["proof"] or "no longer detected on rescan", actor="engine")
                closed.append(issue["id"])
        return {"opened": opened, "updated": updated, "closed": closed, "findings": len(findings)}

    # ---------------- act ----------------
    def advance(self):
        events = []
        for issue in self.store.issues("open"):
            events += self._advance_issue(issue["id"])
        for issue_id in self._raise_defect_actions():
            events.append((issue_id, "corrective action opened from inspection defects"))
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
                self.store.update_step(nxt["id"], state="awaiting_approval",
                                       result=json.dumps({"awaiting_since": self.today.isoformat()}))
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
            if waits:
                result = {**result, "waiting_since": self.today.isoformat()}  # lets the scheduler chase stalls
            self.store.update_step(nxt["id"], state="waiting" if waits else "done", result=json.dumps(result))
            self.store.audit("engine", "action_taken", nxt["id"],
                             {"action": nxt["action"], "approved_by": nxt["approved_by"], "result": result})
            events.append((nxt["id"], nxt["action"]))
            if waits:
                return events

    # ---------------- verify ----------------
    def _verify(self, issue, verify_step, steps):
        if self._is_manual(issue):
            return self._verify_corrective(issue, verify_step, steps)
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
            asked = len((prior.get("request_quotes") or {}).get("requested_from", []))
            quotes = f"; quotes requested from {asked} providers" if asked else ""
            return (f"Book {who} with {p['name']} for EUR {p['price_eur']} ({p['lead_days']} days lead time) - "
                    f"{req['name']} (listed price{quotes})")
        if step["action"] == "request_signature":
            if "draft_document" in prior:
                return f"Review the draft {req['name']} for {who} and release it for signature"
            return f"Send the {req['name']} to {who} for signature"
        if step["action"] == "close_action":
            data = json.loads(issue["data"] or "{}")
            return (f"Sign off corrective action: {data.get('title', issue['detail'])} "
                    f"(evidence on file: {issue['proof']})")
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
    def store_evidence(self, doc, file_path=None):
        """Keep a copy of the evidence file, named by its SHA-256, so records survive (spec 10)."""
        candidates = [Path(file_path)] if file_path else []
        if doc.get("file") and self.customer.path:
            candidates += [self.customer.path / "incoming" / doc["file"], self.customer.path / doc["file"]]
        src = next((c for c in candidates if c and c.is_file()), None)
        if not src:
            return doc
        data = src.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        dest = self.evidence_dir / f"{digest}{src.suffix.lower()}"
        if not dest.exists():
            dest.write_bytes(data)
        return {**doc, "evidence": {"sha256": digest, "stored_as": dest.name, "original_name": src.name}}

    def ingest(self, doc, source="inbound", file_path=None):
        doc = self.store_evidence(doc, file_path)
        self.store.add_document(doc, source=source, actor=f"inbound:{doc.get('received_via', source)}")
        self.store.log_comm("in", doc.get("received_via", source), self.customer.holder_name(doc["holder"]), "",
                            f"{doc['type']} received ({doc['id']})", None, None, "received")
        events = []
        for issue in self.store.issues("open"):
            if issue["requirement"] != doc["type"] or issue["holder"] != doc["holder"]:
                continue
            if self._is_manual(issue) and not self._evidence_for(issue, doc):
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
        for issue_id in self._raise_defect_actions():
            events.append((issue_id, "corrective action opened from inspection defects"))
        return events

    # ---------------- inbound photos (Claude vision) ----------------
    def ingest_photo(self, path, holder, context=None, expected_type=None, received_via="whatsapp", call=None):
        """Read a card/certificate photo. Confident, consistent reads go straight into ingest();
        everything else waits in the human review queue. Nothing is ever guessed."""
        if holder != "company" and holder not in self.customer.workers:
            raise ValueError(f"unknown holder {holder}")
        ex = vision.read_photo(path, self.kb, expected_type=expected_type, call=call)
        confidence, reasons, values = vision.assess(ex, self.kb, self.customer, holder, expected_type)
        self.store.audit("engine", "photo_read", str(Path(path).name),
                         {"holder": holder, "source": ex["source"], "model": ex.get("model"),
                          "document_type": ex.get("document_type"), "confidence": confidence, "reasons": reasons})
        if not reasons:
            doc = vision.to_document(ex, values, holder, context, received_via, confidence=confidence)
            return {"status": "ingested", "document": doc["id"], "confidence": confidence, "source": ex["source"],
                    "events": self.ingest(doc, source="photo", file_path=path)}
        review_id = self.store.add_review({"file": str(path), "holder": holder, "context": context,
                                           "extraction": {**ex, "received_via": received_via, "values": values},
                                           "confidence": confidence, "reasons": reasons})
        self.store.audit("engine", "review_queued", review_id,
                         {"file": str(Path(path).name), "holder": holder, "confidence": confidence, "reasons": reasons})
        return {"status": "needs_review", "review": review_id, "confidence": confidence, "reasons": reasons,
                "source": ex["source"]}

    def review_queue(self):
        return self.store.reviews("pending")

    def accept_review(self, review_id, by, doc_type=None, corrections=None):
        """A human has looked at the photo: accept the read (with any corrections) and ingest it."""
        r = self.store.review(review_id)
        if not r or r["status"] != "pending":
            raise ValueError(f"{review_id} is not pending review")
        ex = r["extraction"]
        ex = {**ex, "document_type": doc_type or ex.get("document_type")}
        if ex["document_type"] not in self.kb.requirements:
            raise ValueError("say which document type this is (doc_type)")
        values = {**(ex.get("values") or {}), **(corrections or {})}
        values = {k: v for k, v in values.items() if v not in (None, "")}
        doc = vision.to_document(ex, values, r["holder"], r["context"], ex.get("received_via", "whatsapp"),
                                 confidence=r["confidence"], reviewed_by=by)
        self.store.update_review(review_id, status="accepted", decided_by=by, decided_at=now_iso(),
                                 decision={"corrections": corrections or {}, "doc_type": ex["document_type"]},
                                 document_id=doc["id"])
        self.store.audit(f"human:{by}", "review_accepted", review_id,
                         {"document": doc["id"], "corrections": corrections or {}})
        return self.ingest(doc, source="human_review", file_path=r["file"])

    def reject_review(self, review_id, by, reason):
        r = self.store.review(review_id)
        if not r or r["status"] != "pending":
            raise ValueError(f"{review_id} is not pending review")
        self.store.update_review(review_id, status="rejected", decided_by=by, decided_at=now_iso(),
                                 decision={"reason": reason})
        self.store.audit(f"human:{by}", "review_rejected", review_id, {"reason": reason})

    # ---------------- corrective actions (spec section 8) ----------------
    @staticmethod
    def _is_manual(issue):
        return issue["requirement"] == "corrective_action"

    def raise_corrective_action(self, title, holder="company", owner="company", due=None, severity="medium",
                                context=None, detail="", evidence_required="photo or document showing the work is done",
                                raised_by="ops", source=None, key=None):
        """Record a safety or compliance issue with an owner, a deadline and the evidence needed to close it."""
        if severity not in ("critical", "high", "medium"):
            raise ValueError("severity must be critical, high or medium")
        for who in (holder, owner):
            if who not in ("company", "ops") and self.customer.holder_kind(who) == "unknown":
                raise ValueError(f"unknown holder/owner {who}")
        due = due or (self.today + timedelta(days={"critical": 2, "high": 7, "medium": 14}[severity])).isoformat()
        issue_id = self.store.next_issue_id()
        key = key or f"corrective_action|{holder}|{context or '-'}|{issue_id}"
        if self.store.open_issue_by_key(key) or any(i["key"] == key for i in self.store.issues()):
            return None
        ts = now_iso()
        data = {"title": title, "owner": owner, "due": due, "evidence_required": evidence_required,
                "raised_by": raised_by, "source": source}
        self.store.insert_issue({
            "id": issue_id, "key": key, "requirement": "corrective_action", "holder": holder, "context": context,
            "category": "corrective", "kind": "corrective", "severity": severity, "status": "open",
            "detail": f"{title}. {detail}".strip(), "required_by": "[]", "data": json.dumps(data),
            "created_at": ts, "updated_at": ts, "resolved_at": None, "proof": None})
        book = "corrective_high" if severity in ("critical", "high") else "corrective"
        for seq, spec in enumerate(self.kb.playbook_for("corrective_action", book), start=1):
            self.store.insert_step({
                "id": f"{issue_id}.{seq}", "issue_id": issue_id, "seq": seq, "action": spec["action"],
                "spec": json.dumps(spec), "state": "pending", "approval_role": spec.get("approval"),
                "approved_by": None, "approved_at": None, "result": None, "updated_at": ts})
        self.store.audit(raised_by if raised_by.startswith(("human:", "engine")) else f"human:{raised_by}",
                         "corrective_action_raised", issue_id,
                         {"title": title, "holder": holder, "owner": owner, "due": due, "severity": severity,
                          "evidence_required": evidence_required, "source": source})
        return issue_id

    @staticmethod
    def _evidence_for(issue, doc):
        """Evidence names the action (ISS-...) or the inspection defect it fixes (<doc id>#<n>)."""
        return doc.get("action") == issue["id"] or (
            bool(doc.get("defect")) and issue["key"] == f"corrective_action|{doc['holder']}|{doc['defect']}|defect")

    def _raise_defect_actions(self):
        """Every defect listed in an inspection report becomes a corrective action, once."""
        opened = []
        for doc in self.store.documents():
            for n, defect in enumerate(doc.get("defects") or [], start=1):
                desc = defect.get("description") if isinstance(defect, dict) else str(defect)
                sev = (defect.get("severity") if isinstance(defect, dict) else None) or "high"
                sev = {"dangerous": "critical", "major": "high", "minor": "medium"}.get(sev, sev)
                if sev not in ("critical", "high", "medium"):
                    sev = "high"
                issue_id = self.raise_corrective_action(
                    title=f"Fix defect on {self.customer.holder_name(doc['holder'])}: {desc}",
                    holder=doc["holder"], owner="company", severity=sev,
                    detail=f"Found in {doc['id']} ({doc.get('inspector', 'inspection')}, {doc.get('issued', '')}).",
                    evidence_required="repair record or job sheet from the competent person who did the repair",
                    raised_by="engine", source=doc["id"], key=f"corrective_action|{doc['holder']}|{doc['id']}#{n}|defect")
                if issue_id:
                    opened.append(issue_id)
        return opened

    def _verify_corrective(self, issue, verify_step, steps):
        evidence = [d for d in self.store.documents() if d.get("type") == "corrective_action" and self._evidence_for(issue, d)]
        waiter = [s for s in steps if s["spec"].get("waits_for") and s["seq"] < verify_step["seq"]][-1]
        if evidence and any(evidence[-1].get(k) for k in ("file", "evidence", "note", "description")):
            proof = evidence[-1]["id"]
            self.store.update_issue(issue["id"], proof=proof)
            self.store.update_step(verify_step["id"], state="done", result=json.dumps({"verified": True, "proof": proof}))
            self.store.audit("engine", "verified", verify_step["id"], {"proof": proof, "evidence_received": True})
            return [(verify_step["id"], "verified")]
        reason = "no evidence attached (send a photo, document or job sheet)"
        self.store.update_step(waiter["id"], state="pending", result=json.dumps({"retry_reason": reason}))
        self.store.audit("engine", "verification_failed", verify_step["id"], {"reason": reason, "retry_step": waiter["id"]})
        return [(verify_step["id"], f"verification_failed: {reason}")]

    def corrective_actions(self, status=None):
        out = []
        for i in self.store.issues(status):
            if self._is_manual(i):
                out.append({**i, **json.loads(i["data"] or "{}")})
        return out

    # ---------------- appointments (spec 4, 6, 9) ----------------
    def update_appointment(self, appt_id, status, by, date=None, notes=""):
        allowed = ("confirmed", "attended", "completed", "no_show", "cancelled")
        if status not in allowed:
            raise ValueError(f"status must be one of {', '.join(allowed)}")
        a = self.store.appointment(appt_id)
        if not a:
            raise ValueError(f"unknown appointment {appt_id}")
        fields = {"status": status, "notes": notes or a["notes"]}
        if date:
            fields["date"] = date
        self.store.update_appointment(appt_id, **fields)
        self.store.audit(f"human:{by}", "appointment_updated", appt_id,
                         {"from": a["status"], "to": status, "date": date or a["date"], "notes": notes})
        if status in ("no_show", "cancelled"):
            return self._rebook(a, by, status)
        return []

    def _rebook(self, appt, by, why):
        """Follow up incomplete work: put the booking back to the customer for approval."""
        steps = self.store.steps(appt["issue_id"])
        book = next((s for s in steps if s["id"] == appt["step_id"]), None)
        if not book or self.store.issue(appt["issue_id"])["status"] == "resolved":
            return []
        for s in steps:
            if s["seq"] >= book["seq"] and s["state"] in ("done", "waiting"):
                self.store.update_step(s["id"], state="pending", approved_by=None, approved_at=None,
                                       result=json.dumps({"rebook_after": why, "appointment": appt["id"]}))
        self.store.audit("engine", "rebooking", appt["issue_id"], {"appointment": appt["id"], "reason": why, "reported_by": by})
        return self._advance_issue(appt["issue_id"])

    # ---------------- records (spec 2 and 10) ----------------
    def document_history(self, holder=None, doc_type=None):
        """Every version of each document, newest first, with the one in force marked current."""
        docs = [d for d in self.store.documents()
                if (holder is None or d["holder"] == holder) and (doc_type is None or d["type"] == doc_type)]
        groups = {}
        for d in docs:
            groups.setdefault((d["type"], d["holder"], d.get("context")), []).append(d)
        out = []
        for (t, h, ctx), versions in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2] or "")):
            current = _best_doc(versions, t, h, ctx)
            ordered = sorted(versions, key=lambda d: d.get("expires") or d.get("issued") or "", reverse=True)
            out.append({"type": t, "holder": h, "context": ctx, "current": current["id"] if current else None,
                        "versions": ordered})
        return out

    def issue_history(self, issue_id):
        """Everything about one issue, for audits: steps, messages, appointments, evidence and audit entries."""
        issue = self.store.issue(issue_id)
        if not issue:
            raise ValueError(f"unknown issue {issue_id}")
        refs = {issue_id} | {s["id"] for s in self.store.steps(issue_id)}
        return {"issue": issue, "steps": self.store.steps(issue_id), "comms": self.store.comms(issue_id),
                "appointments": self.store.appointments(issue_id=issue_id), "quotes": self.store.quotes(issue_id),
                "proof": next((d for d in self.store.documents() if d["id"] == issue["proof"]), None),
                "audit": [a for a in self.store.audit_rows() if a["ref"] in refs or a["ref"].startswith(issue_id + ".")]}
