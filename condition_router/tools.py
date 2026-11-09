"""The executor: runs a tool call against a world, behind the gate when a level is set, and writes the audit log."""
from __future__ import annotations

from dataclasses import dataclass, field

from .checks import RULES, Decision
from .gate import LEVELS, Gate
from .models import BOUNCE, ESCALATE, FILE
from .specs import TOOL_SPECS

TOOL_NAMES = {t["name"] for t in TOOL_SPECS}


@dataclass
class Session:
    """The context the caller fixes for one upload event. The model never chooses these."""

    tenant_id: str
    loan_id: str
    upload_id: str
    read: set = field(default_factory=set)


class Executor:
    def __init__(self, world, audit, level="off"):
        assert level in LEVELS
        self.world = world
        self.audit = audit
        self.level = level
        self.decisions = {}
        self.gate = Gate(world, level, self.decisions) if level != "off" else None

    def call(self, session, name, args):
        refusal = self.gate.check(session, name, args) if self.gate else None
        if refusal:
            result = {"error": refusal.code, "message": refusal.message}
        else:
            handler = getattr(self, "_" + name, None) if name in TOOL_NAMES else None
            if handler is None:
                result = {"error": "UNKNOWN_TOOL"}
            elif not isinstance(args, dict):
                result = {"error": "BAD_ARGS"}
            else:
                try:
                    result = handler(session, **args)
                except TypeError:
                    result = {"error": "BAD_ARGS"}
        outcome = "refused" if refusal else ("error" if "error" in result else "ok")
        upload_id = args.get("upload_id", "") if isinstance(args, dict) else ""
        self.audit.append(session.tenant_id, session.loan_id, str(upload_id), name, args, outcome, result.get("error", ""))
        return result

    def _get_open_conditions(self, session):
        loan = self.world.loans[session.loan_id]
        return {"conditions": [
            {"id": c.id, "kind": c.kind, "window_start": c.window_start.isoformat(),
             "window_end": c.window_end.isoformat(), "rule": RULES[c.kind]}
            for c in loan.conditions
        ]}

    def _read_upload(self, session, upload_id):
        up = self.world.uploads.get(upload_id)
        if up is None:
            return {"error": "NOT_FOUND"}
        session.read.add(upload_id)
        return {"upload_id": upload_id, "text": up.text, "ocr_confidence": up.ocr_confidence}

    def _file_document(self, session, upload_id, condition_id, evidence):
        if upload_id not in self.world.uploads:
            return {"error": "NOT_FOUND"}
        self.decisions[upload_id] = Decision(FILE, condition_id, None)
        return {"status": "filed", "upload_id": upload_id, "condition_id": condition_id}

    def _bounce_to_borrower(self, session, upload_id, reason_code, message):
        if upload_id not in self.world.uploads:
            return {"error": "NOT_FOUND"}
        self.decisions[upload_id] = Decision(BOUNCE, None, reason_code)
        return {"status": "bounced", "upload_id": upload_id}

    def _escalate_to_loan_officer(self, session, upload_id, note):
        if upload_id not in self.world.uploads:
            return {"error": "NOT_FOUND"}
        self.decisions[upload_id] = Decision(ESCALATE, None, note)
        return {"status": "escalated", "upload_id": upload_id}
