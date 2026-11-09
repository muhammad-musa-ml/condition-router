import json
import random

import pytest

from condition_router.agent import run_upload
from condition_router.audit import AuditLog
from condition_router.models import BOUNCE, FILE
from condition_router.scripted import FAULTS, ScriptedModel
from condition_router.synth import make_world
from condition_router.tools import Executor

LEVELS = ("off", "scope", "full")


def _go(world, uid, level, fault=None):
    ex = Executor(world, AuditLog(), level)
    model = ScriptedModel(world, uid, random.Random(1), inject_follow=0.0, force_fault=fault)
    return ex, run_upload(model, ex, uid)


def _same(decision, truth):
    return decision.action == truth.action and decision.condition_id == truth.condition_id


def _wrong_fill(decision, truth):
    return decision.action == FILE and not _same(decision, truth)


@pytest.mark.parametrize("level", LEVELS)
def test_a_careful_model_reaches_every_label_at_every_level(level):
    for seed in range(4):
        w = make_world(seed)
        for uid in w.uploads:
            ex, tr = _go(w, uid, level)
            assert _same(tr.final, w.truth[uid]) and not tr.forced, (seed, uid)
            assert ex.audit.verify()


def test_with_the_full_gate_no_fault_produces_a_wrong_filing():
    for seed in range(4):
        w = make_world(seed)
        for uid in w.uploads:
            for fault in FAULTS + ("obey_injection",):
                _, tr = _go(w, uid, "full", fault)
                assert not _wrong_fill(tr.final, w.truth[uid]), (seed, uid, fault)


def test_without_a_gate_eager_and_injected_filings_get_through():
    w = make_world(0)
    bad = [u for u, t in w.truth.items() if t.action != FILE]
    assert any(_wrong_fill(_go(w, u, "off", "eager_file")[1].final, w.truth[u]) for u in bad)
    inj = [u for u, t in w.truth.items() if t.scenario == "injection"]
    assert inj and all(_wrong_fill(_go(w, u, "off", "obey_injection")[1].final, w.truth[u]) for u in inj)


def test_the_scope_level_stops_cross_tenant_reads_and_double_decisions():
    w = make_world(0)
    uid = next(iter(w.uploads))
    leaked = {}
    for level in LEVELS:
        ex, _ = _go(w, uid, level, "cross_tenant")
        tenant = w.uploads[uid].tenant_id
        leaked[level] = sum(1 for r in ex.audit.rows() if r["tool"] == "read_upload" and r["outcome"] == "ok"
                            and w.uploads[json.loads(r["args"])["upload_id"]].tenant_id != tenant)
    assert leaked == {"off": 1, "scope": 0, "full": 0}
    not_bounce = next(u for u, t in w.truth.items() if t.action != BOUNCE)
    flipped = {lv: _go(w, not_bounce, lv, "double_decide")[1].final for lv in LEVELS}
    assert flipped["off"].action == BOUNCE
    assert _same(flipped["scope"], w.truth[not_bounce]) and _same(flipped["full"], w.truth[not_bounce])


@pytest.mark.parametrize("fault", ["bad_args", "skip_read"])
@pytest.mark.parametrize("level", LEVELS)
def test_argument_and_order_mistakes_are_recovered_from(fault, level):
    w = make_world(0)
    for uid in list(w.uploads)[:12]:
        _, tr = _go(w, uid, level, fault)
        assert _same(tr.final, w.truth[uid]) and not tr.forced, (uid, fault, level)


class _Silent:
    def step(self, messages, tools):
        return {"content": "I think this is fine.", "tool_calls": []}


class _Loops:
    def step(self, messages, tools):
        return {"content": "", "tool_calls": [{"id": "c", "name": "get_open_conditions", "arguments": "{}"}]}


class _BrokenJson:
    def step(self, messages, tools):
        return {"content": "", "tool_calls": [{"id": "c", "name": "read_upload", "arguments": '{"upload_id": '}]}


@pytest.mark.parametrize("model,steps", [(_Silent(), 2), (_Loops(), 8), (_BrokenJson(), 8)])
def test_a_model_that_never_decides_is_escalated_by_the_loop(model, steps):
    w = make_world(0)
    uid = next(iter(w.uploads))
    ex = Executor(w, AuditLog(), "full")
    tr = run_upload(model, ex, uid)
    assert tr.forced and tr.steps == steps and tr.final.action == "escalate"
    assert ex.audit.rows()[-1]["tool"] == "escalate_to_loan_officer" and ex.audit.verify()


def test_invalid_json_is_counted_and_audited():
    w = make_world(0)
    uid = next(iter(w.uploads))
    ex = Executor(w, AuditLog(), "scope")
    tr = run_upload(_BrokenJson(), ex, uid)
    assert tr.invalid_json == 8
    assert {r["code"] for r in ex.audit.rows()[:-1]} == {"BAD_ARGS"}
