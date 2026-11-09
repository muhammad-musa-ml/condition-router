import pytest

from condition_router.audit import AuditLog
from condition_router.checks import kind_of, quote_fields
from condition_router.models import FILE
from condition_router.synth import make_world
from condition_router.tools import Executor, Session


def _run(level, seed=0, scenario=None):
    w = make_world(seed)
    uid = next(u for u, t in w.truth.items() if scenario is None or t.scenario == scenario)
    up = w.uploads[uid]
    return w, Executor(w, AuditLog(), level), Session(up.tenant_id, up.loan_id, uid), uid


def _evidence(w, uid):
    holder, start, end = quote_fields(w.uploads[uid].text)
    return {"holder_name": holder, "period_start": start, "period_end": end}


def _file(ex, s, uid, cond_id, evidence):
    return ex.call(s, "file_document", {"upload_id": uid, "condition_id": cond_id, "evidence": evidence})


def test_scope_refuses_another_tenants_upload_and_returns_no_text():
    w, ex, s, uid = _run("scope")
    other = next(u for u in w.uploads.values() if u.tenant_id != s.tenant_id)
    out = ex.call(s, "read_upload", {"upload_id": other.id})
    assert out["error"] == "OUT_OF_SCOPE" and "text" not in out
    assert ex.audit.rows()[-1]["outcome"] == "refused"


def test_scope_refuses_another_upload_on_the_same_loan():
    w, ex, s, uid = _run("scope")
    sibling = next(u for u in w.uploads.values() if u.loan_id == s.loan_id and u.id != uid)
    assert ex.call(s, "read_upload", {"upload_id": sibling.id})["error"] == "OUT_OF_SCOPE"


def test_unknown_and_foreign_ids_get_the_same_answer():
    w, ex, s, uid = _run("scope")
    other = next(u for u in w.uploads.values() if u.tenant_id != s.tenant_id)
    assert ex.call(s, "read_upload", {"upload_id": other.id}) == ex.call(s, "read_upload", {"upload_id": "U-none"})


def test_scope_refuses_a_condition_from_another_loan():
    w, ex, s, uid = _run("scope")
    foreign = next(l for l in w.loans.values() if l.id != s.loan_id).conditions[0].id
    ex.call(s, "read_upload", {"upload_id": uid})
    assert _file(ex, s, uid, foreign, {"holder_name": "a b", "period_start": "x", "period_end": "y"})["error"] == "OUT_OF_SCOPE"
    assert uid not in ex.decisions


def test_deciding_before_reading_is_refused():
    w, ex, s, uid = _run("scope")
    out = ex.call(s, "escalate_to_loan_officer", {"upload_id": uid, "note": "n"})
    assert out["error"] == "NOT_READ" and uid not in ex.decisions


def test_second_decision_is_refused_and_the_first_stands():
    w, ex, s, uid = _run("scope")
    ex.call(s, "read_upload", {"upload_id": uid})
    ex.call(s, "escalate_to_loan_officer", {"upload_id": uid, "note": "n"})
    out = ex.call(s, "bounce_to_borrower", {"upload_id": uid, "reason_code": "UNREADABLE", "message": "m"})
    assert out["error"] == "ALREADY_DECIDED"
    assert ex.decisions[uid].action == "escalate"


@pytest.mark.parametrize("name,args", [
    ("read_upload", {}),
    ("read_upload", {"upload_id": "U", "extra": 1}),
    ("read_upload", {"upload_id": 7}),
    ("read_upload", "U"),
    ("bounce_to_borrower", {"upload_id": "U", "reason_code": "BORED", "message": "m"}),
    ("escalate_to_loan_officer", {"upload_id": "U", "note": "  "}),
    ("escalate_to_loan_officer", {"upload_id": "U", "note": "x" * 501}),
    ("file_document", {"upload_id": "U", "condition_id": "c", "evidence": {"holder_name": "a b"}}),
    ("file_document", {"upload_id": "U", "condition_id": "c", "evidence": "a b"}),
])
def test_malformed_arguments_are_refused_as_bad_args(name, args):
    w, ex, s, uid = _run("scope")
    assert ex.call(s, name, args)["error"] == "BAD_ARGS"


def test_unknown_tool_is_refused():
    w, ex, s, uid = _run("scope")
    assert ex.call(s, "delete_loan", {})["error"] == "UNKNOWN_TOOL"


def test_every_refusal_is_in_the_audit_log_with_its_code():
    w, ex, s, uid = _run("full")
    ex.call(s, "read_upload", {"upload_id": "U-none"})
    ex.call(s, "escalate_to_loan_officer", {"upload_id": uid, "note": "n"})
    rows = ex.audit.rows()
    assert [(r["outcome"], r["code"]) for r in rows] == [("refused", "OUT_OF_SCOPE"), ("refused", "NOT_READ")]
    assert ex.audit.verify()


def test_scope_level_does_not_check_the_document():
    w, ex, s, uid = _run("scope", scenario="wrong_period")
    ex.call(s, "read_upload", {"upload_id": uid})
    cond = next(c for c in w.loan_of(uid).conditions if c.kind == kind_of(w.uploads[uid].text))
    out = _file(ex, s, uid, cond.id, _evidence(w, uid))
    assert out.get("status") == "filed"


@pytest.mark.parametrize("scenario,code", [
    ("wrong_period", "WRONG_PERIOD"),
    ("injection", "WRONG_PERIOD"),
    ("name_mismatch", "NAME_MISMATCH"),
])
def test_full_refuses_a_filing_the_document_does_not_support(scenario, code):
    w, ex, s, uid = _run("full", scenario=scenario)
    ex.call(s, "read_upload", {"upload_id": uid})
    for cond in w.loan_of(uid).conditions:
        out = _file(ex, s, uid, cond.id, _evidence(w, uid))
        assert out["error"] == (code if cond.kind == kind_of(w.uploads[uid].text) else "WRONG_DOCUMENT_TYPE")
    assert uid not in ex.decisions


def test_full_refuses_evidence_that_is_not_in_the_document():
    w, ex, s, uid = _run("full", scenario="valid")
    ex.call(s, "read_upload", {"upload_id": uid})
    good = _evidence(w, uid)
    fake = dict(good, period_end="12/31/2099")
    for cond in w.loan_of(uid).conditions:
        assert _file(ex, s, uid, cond.id, fake)["error"] in ("EVIDENCE_NOT_IN_DOCUMENT", "WRONG_DOCUMENT_TYPE")
    assert uid not in ex.decisions


def test_full_refuses_a_scan_below_the_confidence_floor_even_with_quotes():
    w, ex, s, uid = _run("full", scenario="valid")
    up = w.uploads[uid]
    w.uploads[uid] = type(up)(up.id, up.loan_id, up.tenant_id, up.text, 0.5)
    ex.call(s, "read_upload", {"upload_id": uid})
    codes = {_file(ex, s, uid, c.id, _evidence(w, uid)).get("error") for c in w.loan_of(uid).conditions}
    assert "UNREADABLE" in codes and uid not in ex.decisions


def test_full_gate_is_exactly_as_permissive_as_the_labels_for_honest_quotes():
    """File every upload to every condition with the document's own quotes: only the labelled filing gets through."""
    checked = 0
    for seed in range(15):
        w = make_world(seed)
        for uid, up in w.uploads.items():
            if quote_fields(up.text) is None:
                assert w.truth[uid].scenario == "unreadable"
                continue
            for cond in w.loan_of(uid).conditions:
                ex, s = Executor(w, AuditLog(), "full"), Session(up.tenant_id, up.loan_id, uid)
                ex.call(s, "read_upload", {"upload_id": uid})
                out = _file(ex, s, uid, cond.id, _evidence(w, uid))
                t = w.truth[uid]
                assert ("error" not in out) == (t.action == FILE and t.condition_id == cond.id), (seed, uid, cond.id)
                checked += 1
    assert checked > 1000
