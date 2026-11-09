"""The gate between the model and the loan file. It runs before every tool call and returns a refusal or nothing.

Levels: "off" runs no gate (the executor still rejects a call it cannot run, such as an unknown tool), "scope" checks
arguments, ownership and order, and "full" also checks the evidence behind a filing against the document.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .checks import check_evidence
from .specs import TERMINAL, TOOL_SPECS

LEVELS = ("off", "scope", "full")
MAX_TEXT = 500
SCHEMAS = {t["name"]: t["parameters"] for t in TOOL_SPECS}

ADVICE = {
    "WRONG_PERIOD": "The period you quoted is outside the window for that condition. Bounce the upload with WRONG_PERIOD if "
                    "that is what the document shows, or escalate if you are unsure.",
    "UNREADABLE": "The scan is too poor to file from. Bounce it with UNREADABLE.",
    "NAME_MISMATCH": "The holder's name does not match the borrower. Escalate so the loan officer decides.",
    "WRONG_DOCUMENT_TYPE": "This is not the kind of document that condition asks for. Pick the matching condition or escalate.",
    "EVIDENCE_NOT_IN_DOCUMENT": "A quoted value does not appear in the document text. Quote it exactly as written.",
    "EVIDENCE_UNPARSEABLE": "A quoted date could not be read as a date. Quote it exactly as written, or escalate.",
}


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str


def validate(value, schema, path="args"):
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                return f"{path}.{key} is required"
        for key in value:
            if key not in props:
                return f"{path}.{key} is not allowed"
        for key, item in value.items():
            err = validate(item, props[key], f"{path}.{key}")
            if err:
                return err
    elif kind == "string":
        if not isinstance(value, str) or not value.strip():
            return f"{path} must be a non-empty string"
        if len(value) > MAX_TEXT:
            return f"{path} is longer than {MAX_TEXT} characters"
        if "enum" in schema and value not in schema["enum"]:
            return f"{path} must be one of {schema['enum']}"
    return None


class Gate:
    def __init__(self, world, level, decisions):
        assert level in LEVELS and level != "off"
        self.world, self.level, self.decisions = world, level, decisions

    def check(self, session, name, args) -> Optional[Refusal]:
        if name not in SCHEMAS:
            return Refusal("UNKNOWN_TOOL", "No such tool.")
        err = validate(args, SCHEMAS[name])
        if err:
            return Refusal("BAD_ARGS", err)
        loan = self.world.loans[session.loan_id]
        upload_id = args.get("upload_id")
        # One answer for an unknown id and another tenant's id, so a refusal does not say which ids exist.
        if upload_id is not None and upload_id != session.upload_id:
            return Refusal("OUT_OF_SCOPE", "That upload is not the one you were given.")
        cond_id = args.get("condition_id")
        cond = next((c for c in loan.conditions if c.id == cond_id), None)
        if cond_id is not None and cond is None:
            return Refusal("OUT_OF_SCOPE", "That condition is not open on this loan.")
        if name in TERMINAL:
            if upload_id not in session.read:
                return Refusal("NOT_READ", "Read the upload before deciding.")
            if upload_id in self.decisions:
                return Refusal("ALREADY_DECIDED", "This upload already has a decision.")
        if self.level == "full" and name == "file_document":
            up = self.world.uploads[upload_id]
            code = check_evidence(up.text, up.ocr_confidence, cond, loan.borrower, args["evidence"])
            if code:
                return Refusal(code, ADVICE[code])
        return None
