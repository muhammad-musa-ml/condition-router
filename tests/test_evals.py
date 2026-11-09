import json
import random
from pathlib import Path

from condition_router.evals import (
    Record, _block, evaluate, is_correct, is_wrong_fill, main, render_markdown, run_one, run_scripted, summarize,
)
from condition_router.checks import Decision, quote_fields
from condition_router.gate import LEVELS
from condition_router.models import BOUNCE, FILE, Truth
from condition_router.scripted import ScriptedModel, scripted_factory
from condition_router.synth import make_world

ROOT = Path(__file__).resolve().parent.parent
FILE_C1 = Truth("file", "c1", None, "valid")
BOUNCE_T = Truth("bounce", None, "WRONG_PERIOD", "wrong_period")


def _forced(fault):
    def make(world, uid, repeat=0):
        return ScriptedModel(world, uid, random.Random(1), inject_follow=0.0, force_fault=fault)
    return make


def _at_each_level(world, uid, fault):
    return {lv: run_one(world, _forced(fault), lv, 0, uid, 0) for lv in LEVELS}


def test_wrong_fill_and_correct_definitions():
    assert not is_wrong_fill("file", "c1", FILE_C1)
    assert is_wrong_fill("file", "c2", FILE_C1)
    assert is_wrong_fill("file", "c1", BOUNCE_T)
    assert not is_wrong_fill("bounce", None, FILE_C1)
    assert not is_wrong_fill("escalate", None, BOUNCE_T)
    assert is_correct(Decision("file", "c1", None), FILE_C1)
    assert not is_correct(Decision("file", "c2", None), FILE_C1)
    assert is_correct(Decision("bounce", None, "UNREADABLE"), BOUNCE_T)
    assert not is_correct(Decision("escalate", None, "x"), BOUNCE_T)


def _rec(seed, uid, correct):
    return Record(seed, uid, 0, "valid", False, correct, False, False, False, False, 0, 3, 3, True, 0)


def test_rate_block_reports_the_spread_across_seeds():
    recs = [_rec(0, "a", True), _rec(0, "b", True), _rec(1, "c", True), _rec(1, "d", False)]
    block = _block(recs, "correct")
    assert (block["count"], block["rate"], block["seed_min"], block["seed_max"]) == (3, 0.75, 0.5, 1.0)


def test_pass_all_k_needs_every_repeat_correct():
    recs = []
    for uid, flags in (("a", (True, True, True)), ("b", (True, False, True))):
        for i, ok in enumerate(flags):
            r = _rec(0, uid, ok)
            r.repeat = i
            recs.append(r)
    out = summarize(recs, repeats=3)
    assert out["pass_all_3"] == 0.5 and out["pass_at_1"] == round(5 / 6, 4)


def test_with_the_full_gate_a_heavily_faulty_model_makes_no_wrong_filing():
    for level, expect_wrong in (("off", True), ("scope", True), ("full", False)):
        s = summarize(evaluate(range(5), lambda seed: scripted_factory(seed, 0.6, 1.0), level))
        assert (s["wrong_fills"]["count"] > 0) == expect_wrong, level
        assert s["unaudited_calls"] == 0 and s["audit_chains_valid"]


def test_the_first_attempt_does_not_depend_on_the_gate_level():
    def attempts(level):
        return [r.attempt_wrong_fill for r in evaluate(range(3), lambda seed: scripted_factory(seed, 0.4, 0.5), level)]
    assert attempts("off") == attempts("scope") == attempts("full") and any(attempts("off"))


def test_check_mode_passes_on_fresh_output_and_fails_when_a_file_changes(tmp_path):
    out = str(tmp_path / "r")
    assert main(["scripted", "--seeds", "0-1", "--out", out]) == 0
    assert main(["scripted", "--seeds", "0-1", "--out", out, "--check"]) == 0
    md = Path(out + ".md")
    table = md.read_text(encoding="utf-8")
    md.write_text(table.replace("| runs |", "| runs! |"), encoding="utf-8")
    assert main(["scripted", "--seeds", "0-1", "--out", out, "--check"]) == 1
    md.write_text(table, encoding="utf-8")
    js = Path(out + ".json")
    data = json.loads(js.read_text(encoding="utf-8"))
    data["levels"]["full"]["wrong_fills"]["count"] += 1
    js.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert main(["scripted", "--seeds", "0-1", "--out", out, "--check"]) == 1


def test_committed_results_are_what_the_code_produces_today():
    assert main(["scripted", "--out", str(ROOT / "results" / "scripted"), "--check"]) == 0


def test_an_eager_wrong_filing_is_attempted_at_every_level_and_made_only_below_full():
    w = make_world(0)
    uid = next(u for u, t in w.truth.items() if t.action != FILE)
    out = _at_each_level(w, uid, "eager_file")
    assert [r.attempt_wrong_fill for r in out.values()] == [True, True, True]
    assert [r.wrong_fill for r in out.values()] == [True, True, False]
    assert [r.final_action for r in out.values()] == ["file", "file", "escalate"]
    assert {r.label_action for r in out.values()} == {w.truth[uid].action}
    assert out["full"].refusals and not out["off"].refusals and not out["scope"].refusals


def test_a_fabricated_filing_is_unsupported_below_full_and_a_missed_fill_at_full():
    w = make_world(0)

    def fake_quotes_in_text(uid):
        cond = next(c for c in w.loan_of(uid).conditions if c.id == w.truth[uid].condition_id)
        quotes = (w.loan_of(uid).borrower, cond.window_start.isoformat(), cond.window_end.isoformat())
        return all(q in w.uploads[uid].text for q in quotes)

    uid = next(u for u, t in w.truth.items() if t.action == FILE and not fake_quotes_in_text(u))
    out = _at_each_level(w, uid, "fabricated")
    assert [r.unsupported_filing for r in out.values()] == [True, True, False]
    assert [r.final_action for r in out.values()] == ["file", "file", "escalate"]
    assert [r.correct for r in out.values()] == [True, True, False]
    assert [r.missed_fill for r in out.values()] == [False, False, True]
    assert [r.wrong_fill for r in out.values()] == [False, False, False]
    assert [summarize([r])["missed_fill_refusals"] for r in out.values()] == [{}, {}, {"EVIDENCE_NOT_IN_DOCUMENT": 1}]
    assert [summarize([r])["missed_fill_runs_with_a_refusal"] for r in out.values()] == [0, 0, 1]


def test_a_valid_upload_lost_to_a_second_decision_is_a_missed_fill_with_no_refusal():
    w = make_world(0)
    uid = next(u for u, t in w.truth.items() if t.action == FILE)
    off = summarize([_at_each_level(w, uid, "double_decide")["off"]])
    assert off["missed_fills"]["count"] == 1 and off["missed_fill_runs_with_a_refusal"] == 0
    assert off["missed_fill_refusals"] == {}


class _FilesTwice:
    """Files its own upload, then another upload, with the evidence it is given for each."""

    def __init__(self, world, uid, own, other):
        cond = world.truth[uid].condition_id
        stranger = next(u.id for u in world.uploads.values() if u.id != uid)
        self.plan = [("get_open_conditions", {}), ("read_upload", {"upload_id": uid}),
                     ("file_document", {"upload_id": uid, "condition_id": cond, "evidence": own}),
                     ("file_document", {"upload_id": stranger, "condition_id": cond, "evidence": other})]

    def step(self, messages, tools):
        if not self.plan:
            return {"content": "Done.", "tool_calls": []}
        name, args = self.plan.pop(0)
        return {"content": "", "tool_calls": [{"id": f"c{len(self.plan)}", "name": name, "arguments": args}]}


def test_the_unsupported_flag_judges_the_filing_for_this_upload_not_the_last_filing_in_the_log():
    w = make_world(0)
    uid = next(u for u, t in w.truth.items() if t.action == FILE)
    holder, start, end = quote_fields(w.uploads[uid].text)
    honest = {"holder_name": holder, "period_start": start, "period_end": end}
    invented = {"holder_name": "No One", "period_start": "01/01/2000", "period_end": "01/02/2000"}
    for own, other, expected in ((honest, invented, False), (invented, honest, True)):
        rec = run_one(w, lambda world, u, repeat=0: _FilesTwice(world, u, own, other), "off", 0, uid, 0)
        assert rec.final_action == "file" and rec.unsupported_filing is expected


def test_a_cross_tenant_read_counts_only_without_the_gate_and_is_a_refusal_before_the_decision():
    w = make_world(0)
    uid = next(iter(w.uploads))
    out = _at_each_level(w, uid, "cross_tenant")
    assert [r.foreign_reads for r in out.values()] == [1, 0, 0]
    assert [r.refused_before_decision for r in out.values()] == [False, True, True]
    assert out["off"].refusals == {} and out["scope"].refusals == {"OUT_OF_SCOPE": 1}


def test_a_late_bounce_is_a_false_bounce_only_when_nothing_stops_the_second_decision():
    w = make_world(0)
    uid = next(u for u, t in w.truth.items() if t.action != BOUNCE)
    out = _at_each_level(w, uid, "double_decide")
    assert [r.false_bounce for r in out.values()] == [True, False, False]
    assert [r.final_action for r in out.values()] == ["bounce", w.truth[uid].action, w.truth[uid].action]
    assert out["scope"].refusals == {"ALREADY_DECIDED": 1}
    assert [r.correct for r in out.values()] == [False, True, True]


def test_the_summary_carries_label_to_final_rows_only_when_every_record_has_a_final_decision():
    new = summarize(evaluate(range(1), lambda s: scripted_factory(s, 0.4, 0.5), "scope", limit=6))
    assert sum(new["decisions_label_to_final"].values()) == 6
    assert "filings_made_on_unsupported_evidence" in new
    assert "label -> final decision: scope: " in render_markdown({"levels": {"scope": new}})
    old_record = Record(0, "a", 0, "valid", False, True, False, False, False, False, 0, 3, 3, True, 0)
    old = summarize([old_record])
    assert "decisions_label_to_final" not in old and "filings_made_on_unsupported_evidence" not in old
    assert "label -> final" not in render_markdown({"levels": {"scope": old}})
    new_record = Record(0, "b", 0, "valid", False, True, False, False, False, False, 0, 3, 3, True, 0,
                        label_action="file", final_action="file", unsupported_filing=False)
    assert "decisions_label_to_final" not in summarize([old_record, new_record])
    assert summarize([new_record])["decisions_label_to_final"] == {"file->file": 1}


def test_uploads_per_seed_is_the_size_of_the_world():
    assert run_scripted([0], 0.0, 0.0)["uploads_per_seed"] == len(make_world(0).uploads) == 36
