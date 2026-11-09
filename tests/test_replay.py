import json
import re

import pytest

from condition_router.checks import analyze, quote_fields
from condition_router.evals import RecordStore, run_one, setup_digest
from condition_router.ollama_model import ollama_factory
from condition_router.replay import main, missing_quotes, replay
from condition_router.synth import make_world
from test_ollama import _call, server  # noqa: F401  (the stub server fixture and the reply helper)

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def test_a_quote_that_is_the_documents_own_value_in_another_form_is_told_from_other_quotes():
    text = "EARNINGS STATEMENT\nEmployee: RIVERA, JORDAN\nPay Period: Sep 12, 2026 - Sep 25, 2026\n"
    quotes = {"holder_name": "Jordan Rivera", "period_start": "2026-09-12", "period_end": "2026-10-01"}
    assert missing_quotes(quotes, text) == {
        "holder_name": "same name, written another way", "period_start": "same date, other format", "period_end": "other"}
    assert missing_quotes({"holder_name": "RIVERA, JORDAN", "period_start": "Sep 12, 2026", "period_end": "Sep 25, 2026"}, text) == {}


def _iso_filing_replies(world, uid):
    """What a model sends when it rewrites the document's dates as ISO dates: a refused filing, then an escalation."""
    text = world.uploads[uid].text
    facts = analyze(text)
    evidence = {"holder_name": quote_fields(text)[0], "period_start": facts.start.isoformat(), "period_end": facts.end.isoformat()}
    cond = world.truth[uid].condition_id
    return [_call("get_open_conditions", {}), _call("read_upload", {"upload_id": uid}),
            _call("file_document", {"upload_id": uid, "condition_id": cond, "evidence": evidence}),
            _call("escalate_to_loan_officer", {"upload_id": uid, "note": "could not file"}),
            {"role": "assistant", "content": "Done."}]


def _stored_run(server, tmp_path):
    world = make_world(0)
    uid = next(u for u, t in world.truth.items() if t.scenario == "valid" and not ISO.search(world.uploads[u].text))
    host = f"http://127.0.0.1:{server.server_port}"
    server.replies += _iso_filing_replies(world, uid)
    rec = run_one(world, ollama_factory("m", host, 0.3, 0), "full", 0, uid, 0)
    assert rec.missed_fill and rec.refusals == {"EVIDENCE_NOT_IN_DOCUMENT": 1}
    path = tmp_path / "runs.jsonl"
    RecordStore(path, {"model": "m", "temperature": 0.3, "setup": setup_digest()}).add(rec)
    return world, uid, host, path


def test_the_replay_reads_the_refused_filing_next_to_the_document(server, tmp_path):
    world, uid, host, path = _stored_run(server, tmp_path)
    server.replies += _iso_filing_replies(world, uid)
    text = replay(path, host)
    assert "replay matches the stored record: yes" in text
    assert "period_start: same date, other format" in text and "period_end: same date, other format" in text
    assert "refused for quotes not in the document: 1" in text
    assert "of those, only the format of a date or a name differs: 1" in text
    out = tmp_path / "calls.txt"
    server.replies += _iso_filing_replies(world, uid)
    assert main([str(path), "--host", host, "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").endswith("differs: 1\n")


def test_a_replay_that_does_not_reproduce_the_stored_run_says_so(server, tmp_path):
    world, uid, host, path = _stored_run(server, tmp_path)
    server.replies += [_call("get_open_conditions", {}), _call("read_upload", {"upload_id": uid}),
                       _call("escalate_to_loan_officer", {"upload_id": uid, "note": "unsure"}),
                       {"role": "assistant", "content": "Done."}]
    text = replay(path, host)
    assert "replay matches the stored record: NO" in text and "matching the stored record: 0" in text


def test_a_run_made_with_another_prompt_is_not_replayed(server, tmp_path):
    world, uid, host, path = _stored_run(server, tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    head = json.loads(lines[0])
    head["meta"]["setup"] = "0" * 12
    path.write_text("\n".join([json.dumps(head)] + lines[1:]) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        replay(path, host)
