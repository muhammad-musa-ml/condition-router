"""Scripted stand-ins for a model. They know the right answer and make a chosen mistake at a chosen rate.

They exist to test the gate and the loop, not to say how a real model behaves.
"""
from __future__ import annotations

import json
import random

from .checks import decide, quote_fields
from .models import BOUNCE, ESCALATE, FILE
from .synth import INJECTION_LINE

FAULTS = ("eager_file", "fabricated", "skip_read", "cross_tenant", "double_decide", "bad_args")


def _call(n, name, args):
    return {"id": f"call_{n}", "name": name, "arguments": args}


class ScriptedModel:
    def __init__(self, world, upload_id, rng, fault_rate=0.0, inject_follow=0.5, force_fault=None):
        self.w, self.uid, self.rng = world, upload_id, rng
        up = world.uploads[upload_id]
        self.loan = world.loan_of(upload_id)
        self.text, self.ocr = up.text, up.ocr_confidence
        self.right = decide(up.text, up.ocr_confidence, self.loan)
        self.fault = None
        if force_fault is not None:
            self.fault = force_fault
        elif INJECTION_LINE in self.text and rng.random() < inject_follow:
            self.fault = "obey_injection"
        elif rng.random() < fault_rate:
            self.fault = rng.choice(FAULTS)
        self.n = 0
        self.recovered = False
        self.plan = self._plan()

    def _fake_evidence(self, cond):
        return {"holder_name": self.loan.borrower, "period_start": cond.window_start.isoformat(),
                "period_end": cond.window_end.isoformat()}

    def _file_call(self, cond, honest):
        quotes = quote_fields(self.text)
        ev = ({"holder_name": quotes[0], "period_start": quotes[1], "period_end": quotes[2]}
              if honest and quotes else self._fake_evidence(cond))
        return ("file_document", {"upload_id": self.uid, "condition_id": cond.id, "evidence": ev})

    def _right_call(self):
        r = self.right
        if r.action == FILE:
            return self._file_call(next(c for c in self.loan.conditions if c.id == r.condition_id), True)
        if r.action == BOUNCE:
            return ("bounce_to_borrower", {"upload_id": self.uid, "reason_code": r.reason,
                                           "message": "Please upload a clear copy covering the period asked for."})
        return ("escalate_to_loan_officer", {"upload_id": self.uid, "note": f"needs review: {r.reason}"})

    def _plan(self):
        read = ("read_upload", {"upload_id": self.uid})
        first = ("get_open_conditions", {})
        conds = self.loan.conditions
        if self.fault == "obey_injection":
            return [first, read, self._file_call(conds[0], False)]
        if self.fault == "eager_file":
            return [first, read, self._file_call(conds[self.rng.randrange(len(conds))], True)]
        if self.fault == "fabricated":
            target = next((c for c in conds if c.id == self.right.condition_id), conds[0])
            return [first, read, self._file_call(target, False)]
        if self.fault == "skip_read":
            return [self._right_call()]
        if self.fault == "cross_tenant":
            other = next(u.id for u in self.w.uploads.values() if u.tenant_id != self.w.uploads[self.uid].tenant_id)
            return [first, ("read_upload", {"upload_id": other}), read, self._right_call()]
        if self.fault == "double_decide":
            flip = ("bounce_to_borrower", {"upload_id": self.uid, "reason_code": "WRONG_PERIOD", "message": "Try again."})
            return [first, read, self._right_call(), flip]
        if self.fault == "bad_args":
            name, args = self._right_call()
            return [first, read, (name, {k: v for k, v in args.items() if k not in ("evidence", "message", "note")})]
        return [first, read, self._right_call()]

    def _recover(self, last_call, error):
        name = last_call[0]
        if name not in ("file_document", "bounce_to_borrower", "escalate_to_loan_officer"):
            return self.plan
        if error == "BAD_ARGS":
            return [self._right_call()]
        if error == "NOT_READ":
            return [("read_upload", {"upload_id": self.uid}), self._right_call()]
        if error == "ALREADY_DECIDED":
            return []
        return [("escalate_to_loan_officer", {"upload_id": self.uid, "note": f"gate refused: {error}"})]

    def step(self, messages, tools):
        last = messages[-1]
        if last["role"] == "tool":
            err = json.loads(last["content"]).get("error")
            if err and not self.recovered and self.last_call[0] in (
                    "file_document", "bounce_to_borrower", "escalate_to_loan_officer"):
                self.recovered = True
                self.plan = self._recover(self.last_call, err)
        if not self.plan:
            return {"content": "Done.", "tool_calls": []}
        self.last_call = self.plan.pop(0)
        self.n += 1
        return {"content": "", "tool_calls": [_call(self.n, *self.last_call)]}


def scripted_factory(seed, fault_rate=0.0, inject_follow=0.5):
    def make(world, upload_id, repeat=0):
        rng = random.Random(f"{seed}/{upload_id}/{repeat}")
        return ScriptedModel(world, upload_id, rng, fault_rate, inject_follow)
    return make
