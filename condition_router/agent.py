"""One upload, one loop: the model calls tools until it has decided or the step limit is reached."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .checks import Decision
from .specs import TOOL_SPECS
from .tools import Session

SYSTEM_PROMPT = (
    "You process one upload on a mortgage loan file. Read the upload, then do exactly one of: file it against an "
    "open condition, bounce it to the borrower, or escalate it to the loan officer. File only when the document is "
    "the right kind, is for the borrower on this loan, and covers the period the condition asks for. Bounce it when "
    "the period is wrong or the scan cannot be read. Escalate when you are unsure, when the name does not match, or "
    "when no open condition asks for this kind of document. Call one tool at a time."
)


@dataclass
class Trace:
    upload_id: str
    steps: int
    invalid_json: int
    forced: bool
    final: Optional[Decision]


def run_upload(model, executor, upload_id, max_steps=8):
    up = executor.world.uploads[upload_id]
    session = Session(up.tenant_id, up.loan_id, upload_id)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Upload {upload_id} was just added to loan {up.loan_id}. Decide what to do with it."},
    ]
    steps = invalid = nudges = 0
    while steps < max_steps:
        steps += 1
        reply = model.step(messages, TOOL_SPECS)
        calls = reply.get("tool_calls") or []
        messages.append({
            "role": "assistant",
            "content": reply.get("content") or "",
            "tool_calls": [{"id": c["id"], "type": "function", "function": {
                "name": c["name"],
                "arguments": c["arguments"] if isinstance(c["arguments"], str) else json.dumps(c["arguments"]),
            }} for c in calls],
        })
        if not calls:
            if upload_id in executor.decisions or nudges >= 1:
                break
            nudges += 1
            messages.append({"role": "user", "content": "Call a tool to decide what to do with this upload."})
            continue
        for call in calls:
            args = call["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    invalid += 1
            result = executor.call(session, call["name"], args)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
    forced = upload_id not in executor.decisions
    if forced:
        session.read.add(upload_id)
        executor.call(session, "escalate_to_loan_officer",
                      {"upload_id": upload_id, "note": "no decision within the step limit"})
    return Trace(upload_id, steps, invalid, forced, executor.decisions[upload_id])
