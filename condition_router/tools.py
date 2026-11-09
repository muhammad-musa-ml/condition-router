"""The five tools the model may call, and the executor that runs them against a world and writes the audit log."""
from __future__ import annotations

from dataclasses import dataclass, field

from .checks import Decision
from .models import BOUNCE, BOUNCE_REASONS, ESCALATE, FILE

TOOL_SPECS = [
    {
        "name": "get_open_conditions",
        "description": "List the open conditions on the loan this upload belongs to.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_upload",
        "description": "Return the extracted text and OCR confidence of an upload.",
        "parameters": {
            "type": "object",
            "properties": {"upload_id": {"type": "string"}},
            "required": ["upload_id"],
        },
    },
    {
        "name": "file_document",
        "description": (
            "Attach the upload to one open condition. Evidence must quote, exactly as written in the document, "
            "the holder's name and the first and last date of the period the document covers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "upload_id": {"type": "string"},
                "condition_id": {"type": "string"},
                "evidence": {
                    "type": "object",
                    "properties": {
                        "holder_name": {"type": "string"},
                        "period_start": {"type": "string"},
                        "period_end": {"type": "string"},
                    },
                    "required": ["holder_name", "period_start", "period_end"],
                },
            },
            "required": ["upload_id", "condition_id", "evidence"],
        },
    },
    {
        "name": "bounce_to_borrower",
        "description": "Send the upload back to the borrower with a reason and a short message saying what to upload instead.",
        "parameters": {
            "type": "object",
            "properties": {
                "upload_id": {"type": "string"},
                "reason_code": {"type": "string", "enum": list(BOUNCE_REASONS)},
                "message": {"type": "string"},
            },
            "required": ["upload_id", "reason_code", "message"],
        },
    },
    {
        "name": "escalate_to_loan_officer",
        "description": "Hand the upload to the loan officer when it needs a person's judgment.",
        "parameters": {
            "type": "object",
            "properties": {"upload_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["upload_id", "note"],
        },
    },
]
TERMINAL = ("file_document", "bounce_to_borrower", "escalate_to_loan_officer")
ACTION_OF = {"file_document": FILE, "bounce_to_borrower": BOUNCE, "escalate_to_loan_officer": ESCALATE}


@dataclass
class Session:
    """The context the caller fixes for one upload event. The model never chooses these."""

    tenant_id: str
    loan_id: str
    upload_id: str
    read: set = field(default_factory=set)


class Executor:
    def __init__(self, world, audit):
        self.world = world
        self.audit = audit
        self.decisions = {}

    def call(self, session, name, args):
        handler = getattr(self, "_" + name, None) if name in {t["name"] for t in TOOL_SPECS} else None
        if handler is None:
            result = {"error": "UNKNOWN_TOOL"}
        elif not isinstance(args, dict):
            result = {"error": "BAD_ARGS"}
        else:
            try:
                result = handler(session, **args)
            except TypeError:
                result = {"error": "BAD_ARGS"}
        self._log(session, name, args, result)
        return result

    def _log(self, session, name, args, result):
        outcome = "error" if "error" in result else "ok"
        upload_id = args.get("upload_id", "") if isinstance(args, dict) else ""
        self.audit.append(session.tenant_id, session.loan_id, str(upload_id), name, args, outcome, result.get("error", ""))

    def _get_open_conditions(self, session):
        loan = self.world.loans[session.loan_id]
        return {"conditions": [
            {"id": c.id, "kind": c.kind, "window_start": c.window_start.isoformat(), "window_end": c.window_end.isoformat()}
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
