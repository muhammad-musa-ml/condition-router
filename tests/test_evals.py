import json
from pathlib import Path

from condition_router.evals import (
    Record, _block, evaluate, is_correct, is_wrong_fill, main, summarize,
)
from condition_router.checks import Decision
from condition_router.models import Truth
from condition_router.scripted import scripted_factory

ROOT = Path(__file__).resolve().parent.parent
FILE_C1 = Truth("file", "c1", None, "valid")
BOUNCE_T = Truth("bounce", None, "WRONG_PERIOD", "wrong_period")


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
    assert attempts("off") == attempts("scope") == attempts("full")


def test_check_mode_passes_on_fresh_output_and_fails_when_a_file_changes(tmp_path):
    out = str(tmp_path / "r")
    assert main(["scripted", "--seeds", "0-1", "--out", out]) == 0
    assert main(["scripted", "--seeds", "0-1", "--out", out, "--check"]) == 0
    js = Path(out + ".json")
    data = json.loads(js.read_text(encoding="utf-8"))
    data["levels"]["full"]["wrong_fills"]["count"] += 1
    js.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert main(["scripted", "--seeds", "0-1", "--out", out, "--check"]) == 1


def test_committed_results_are_what_the_code_produces_today():
    assert main(["scripted", "--out", str(ROOT / "results" / "scripted"), "--check"]) == 0
