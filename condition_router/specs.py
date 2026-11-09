"""The five tools the model may call. The gate validates arguments against these same schemas."""
from __future__ import annotations

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
