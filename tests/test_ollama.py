import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from condition_router.agent import run_upload
from condition_router.audit import AuditLog
from condition_router.evals import RecordStore, evaluate, setup_digest
from condition_router.ollama_model import OllamaModel, ollama_factory
from condition_router.scripted import scripted_factory
from condition_router.synth import make_world
from condition_router.tools import Executor

META = {"model": "m", "temperature": 0.3}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, body))
        msg = self.server.replies.pop(0)
        status = msg.get("_status", 200)
        data = json.dumps({"choices": [{"message": msg}]} if status == 200 else {"error": "model not found"}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    srv.requests, srv.replies = [], []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _call(name, args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_request_carries_the_tools_in_function_form_and_the_seed(server):
    server.replies.append({"role": "assistant", "content": "hi"})
    model = OllamaModel("m", f"http://127.0.0.1:{server.server_port}", temperature=0.3, seed=7)
    from condition_router.specs import TOOL_SPECS
    out = model.step([{"role": "user", "content": "x"}], TOOL_SPECS)
    path, body = server.requests[0]
    assert path == "/v1/chat/completions" and body["model"] == "m" and body["stream"] is False
    assert (body["temperature"], body["seed"]) == (0.3, 7)
    assert [t["function"]["name"] for t in body["tools"]] == [t["name"] for t in TOOL_SPECS]
    assert all(t["type"] == "function" for t in body["tools"])
    assert out == {"content": "hi", "tool_calls": []}


def test_an_error_answer_from_the_server_names_the_status_and_the_body(server):
    server.replies.append({"_status": 404})
    model = OllamaModel("missing", f"http://127.0.0.1:{server.server_port}")
    with pytest.raises(RuntimeError, match="404.*model not found"):
        model.step([{"role": "user", "content": "x"}], [])


def test_the_loop_runs_a_decision_through_the_server(server):
    w = make_world(0)
    uid = next(iter(w.uploads))
    server.replies += [
        _call("get_open_conditions", {}),
        _call("read_upload", {"upload_id": uid}),
        _call("escalate_to_loan_officer", {"upload_id": uid, "note": "unsure"}),
        {"role": "assistant", "content": "Done."},
    ]
    ex = Executor(w, AuditLog(), "full")
    model = ollama_factory("m", f"http://127.0.0.1:{server.server_port}")(w, uid, 0)
    tr = run_upload(model, ex, uid)
    assert tr.final.action == "escalate" and not tr.forced
    assert [r["tool"] for r in ex.audit.rows()] == ["get_open_conditions", "read_upload", "escalate_to_loan_officer"]
    last_messages = server.requests[-1][1]["messages"]
    assert [m["role"] for m in last_messages][-2:] == ["assistant", "tool"]
    assert last_messages[-2]["tool_calls"][0]["function"]["arguments"] == json.dumps({"upload_id": uid, "note": "unsure"})


def test_command_line_writes_results_and_one_stored_run(server, tmp_path):
    from condition_router.evals import main
    uid = next(iter(make_world(0).uploads))
    server.replies += [
        _call("get_open_conditions", {}),
        _call("read_upload", {"upload_id": uid}),
        _call("escalate_to_loan_officer", {"upload_id": uid, "note": "unsure"}),
        {"role": "assistant", "content": "Done."},
    ]
    out = str(tmp_path / "o")
    code = main(["ollama", "--model", "m", "--host", f"http://127.0.0.1:{server.server_port}",
                 "--limit", "1", "--out", out])
    data = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    assert code == 0 and data["model"] == "m" and data["levels"]["full"]["runs"] == 1
    assert data["uploads_per_seed"] == 1 and list(data["levels"]) == ["full"]
    lines = (tmp_path / "o.records.jsonl").read_text(encoding="utf-8").splitlines()
    meta = {"model": "m", "temperature": 0.3, "setup": setup_digest()}
    assert len(lines) == 2 and json.loads(lines[0]) == {"meta": meta}


def test_seed_is_fixed_per_upload_and_repeat_and_differs_between_repeats():
    w = make_world(0)
    uid = next(iter(w.uploads))
    f = ollama_factory("m", base_seed=3)
    assert f(w, uid, 0).seed == ollama_factory("m", base_seed=3)(w, uid, 0).seed
    assert f(w, uid, 0).seed != f(w, uid, 1).seed
    assert f(w, uid, 0).seed != ollama_factory("m", base_seed=4)(w, uid, 0).seed


def test_a_stored_run_is_not_run_again(tmp_path):
    asked = []

    def factory_for_seed(seed):
        inner = scripted_factory(seed, 0.0, 0.0)

        def make(world, uid, repeat=0):
            asked.append(uid)
            return inner(world, uid, repeat)
        return make

    path = tmp_path / "runs.jsonl"
    first = evaluate([0], factory_for_seed, "full", limit=3, store=RecordStore(path, META))
    assert len(asked) == 3
    again = evaluate([0], factory_for_seed, "full", limit=3, store=RecordStore(path, META))
    assert len(asked) == 3 and again == first
    evaluate([0], factory_for_seed, "full", limit=5, store=RecordStore(path, META))
    assert len(asked) == 5
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1 + 5


def test_a_file_from_another_run_or_with_no_description_is_refused(tmp_path):
    path = tmp_path / "runs.jsonl"
    store = RecordStore(path, META)
    evaluate([0], lambda seed: scripted_factory(seed, 0.0, 0.0), "full", limit=2, store=store)
    for other in ({"model": "m2", "temperature": 0.3}, {"model": "m", "temperature": 0.7}):
        with pytest.raises(ValueError, match="another run"):
            RecordStore(path, other)
    old = tmp_path / "old.jsonl"
    old.write_text("\n".join(path.read_text(encoding="utf-8").splitlines()[1:]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="run description"):
        RecordStore(old, META)
    assert len(RecordStore(path, META).done) == 2


def test_a_last_line_cut_short_by_a_stop_is_dropped_but_damage_elsewhere_is_an_error(tmp_path):
    path = tmp_path / "runs.jsonl"
    evaluate([0], lambda seed: scripted_factory(seed, 0.0, 0.0), "full", limit=3, store=RecordStore(path, META))
    whole = path.read_text(encoding="utf-8")
    path.write_text(whole + '{"seed": 0, "upload_id": "U-x', encoding="utf-8")
    store = RecordStore(path, META)
    assert len(store.done) == 3 and path.read_text(encoding="utf-8") == whole
    lines = whole.splitlines()
    lines[2] = lines[2][:20]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        RecordStore(path, META)


def test_the_setup_digest_changes_with_the_prompt_and_the_tool_descriptions(monkeypatch):
    from condition_router import evals
    base = setup_digest()
    monkeypatch.setattr(evals, "SYSTEM_PROMPT", evals.SYSTEM_PROMPT + " Be quick.")
    assert setup_digest() != base
    monkeypatch.undo()
    monkeypatch.setattr(evals, "TOOL_SPECS", evals.TOOL_SPECS[:-1])
    assert setup_digest() != base
