import sqlite3

import pytest

from condition_router.audit import AuditLog
from condition_router.checks import RULES
from condition_router.models import BOUNCE, ESCALATE, FILE
from condition_router.synth import make_world
from condition_router.specs import TOOL_SPECS
from condition_router.tools import Executor, Session


def _setup():
    w = make_world(0)
    uid = next(iter(w.uploads))
    up = w.uploads[uid]
    return w, Executor(w, AuditLog()), Session(up.tenant_id, up.loan_id, uid), uid


def test_chain_verifies_and_detects_a_changed_row():
    log = AuditLog()
    for i in range(4):
        log.append("T1", "L1", f"U{i}", "read_upload", {"upload_id": f"U{i}"}, "ok")
    assert log.verify()
    log.db.execute("DROP TRIGGER audit_no_update")
    log.db.execute("UPDATE audit SET outcome = 'refused' WHERE seq = 2")
    log.db.execute("UPDATE audit SET args = '{}' WHERE seq = 3")
    assert not log.verify()


def test_deleting_a_middle_row_breaks_the_chain():
    log = AuditLog()
    for i in range(3):
        log.append("T1", "L1", f"U{i}", "read_upload", {}, "ok")
    log.db.execute("DROP TRIGGER audit_no_delete")
    log.db.execute("DELETE FROM audit WHERE seq = 2")
    assert not log.verify()


def test_replacing_a_row_with_insert_or_replace_is_refused_by_the_database():
    log = AuditLog()
    log.append("T1", "L1", "U1", "read_upload", {}, "ok")
    log.append("T1", "L1", "U2", "read_upload", {}, "ok")
    with pytest.raises(sqlite3.IntegrityError):
        log.db.execute(
            "INSERT OR REPLACE INTO audit (seq, tenant_id, loan_id, upload_id, tool, args, outcome, code, prev, hash) "
            "VALUES (1, 'T9', 'L9', 'U9', 'x', '{}', 'ok', '', 'p', 'h')")
    assert [r["tenant_id"] for r in log.rows()] == ["T1", "T1"] and log.verify()


def test_update_and_delete_are_refused_by_the_database():
    log = AuditLog()
    log.append("T1", "L1", "U1", "read_upload", {}, "ok")
    with pytest.raises(sqlite3.IntegrityError):
        log.db.execute("UPDATE audit SET outcome = 'x'")
    with pytest.raises(sqlite3.IntegrityError):
        log.db.execute("DELETE FROM audit")


def test_every_call_writes_exactly_one_row_even_when_it_fails():
    w, ex, s, uid = _setup()
    calls = [
        ("get_open_conditions", {}),
        ("read_upload", {"upload_id": uid}),
        ("read_upload", {"upload_id": "nope"}),
        ("file_document", {"upload_id": uid}),
        ("no_such_tool", {}),
        ("escalate_to_loan_officer", "not a dict"),
    ]
    for i, (name, args) in enumerate(calls, 1):
        ex.call(s, name, args)
        assert len(ex.audit.rows()) == i
    assert [r["outcome"] for r in ex.audit.rows()] == ["ok", "ok", "error", "error", "error", "error"]
    assert ex.audit.verify()


def test_terminal_tools_record_a_decision():
    w, ex, s, uid = _setup()
    cond = w.loan_of(uid).conditions[0].id
    ex.call(s, "file_document", {"upload_id": uid, "condition_id": cond,
                                 "evidence": {"holder_name": "x", "period_start": "a", "period_end": "b"}})
    assert (ex.decisions[uid].action, ex.decisions[uid].condition_id) == (FILE, cond)
    ex.call(s, "bounce_to_borrower", {"upload_id": uid, "reason_code": "WRONG_PERIOD", "message": "m"})
    assert ex.decisions[uid].action == BOUNCE
    ex.call(s, "escalate_to_loan_officer", {"upload_id": uid, "note": "n"})
    assert ex.decisions[uid].action == ESCALATE


def test_without_a_gate_a_terminal_tool_on_an_unknown_upload_is_not_found_and_decides_nothing():
    w, ex, s, uid = _setup()
    calls = [
        ("file_document", {"upload_id": "U-none", "condition_id": "c",
                           "evidence": {"holder_name": "x", "period_start": "a", "period_end": "b"}}),
        ("bounce_to_borrower", {"upload_id": "U-none", "reason_code": "WRONG_PERIOD", "message": "m"}),
        ("escalate_to_loan_officer", {"upload_id": "U-none", "note": "n"}),
    ]
    for name, args in calls:
        assert ex.call(s, name, args) == {"error": "NOT_FOUND"}
    assert ex.decisions == {} and [r["outcome"] for r in ex.audit.rows()] == ["error"] * 3


def test_open_conditions_state_the_period_rule_of_each_kind():
    w, ex, s, uid = _setup()
    conditions = ex.call(s, "get_open_conditions", {})["conditions"]
    assert {c["kind"]: c["rule"] for c in conditions} == RULES
    assert len(set(RULES.values())) == len(RULES) == 3


def test_tool_specs_are_well_formed():
    names = [t["name"] for t in TOOL_SPECS]
    assert len(names) == len(set(names)) == 5
    for t in TOOL_SPECS:
        assert t["parameters"]["type"] == "object"
        assert set(t["parameters"]["required"]) <= set(t["parameters"]["properties"])


def test_without_a_gate_the_executor_reads_across_tenants():
    """This is the behaviour the gate exists to remove."""
    w, ex, s, uid = _setup()
    other = next(u for u in w.uploads.values() if u.tenant_id != s.tenant_id)
    out = ex.call(s, "read_upload", {"upload_id": other.id})
    assert out["text"] == other.text
