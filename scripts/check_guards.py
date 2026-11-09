"""Break each guard in a copy of the repository and require the test suite to fail.

A guard whose test still passes when the guard is gone is not tested. The repository itself is never edited.
The results-snapshot test is left out of these runs: it fails on any change, so it would hide a guard with no test of its own.
Run: python scripts/check_guards.py [--write results/guards.txt] [--workers 4]
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_TEST = "tests/test_evals.py::test_committed_results_are_what_the_code_produces_today"

MUTANTS = [
    ("checks: ignore the confidence floor", "condition_router/checks.py",
     "    if ocr_confidence < LEGIBLE_AT:\n        return UNREADABLE\n    if kind_of(text) != cond.kind:",
     "    if kind_of(text) != cond.kind:"),
    ("checks: ignore the document kind", "condition_router/checks.py",
     "    if kind_of(text) != cond.kind:\n        return WRONG_DOCUMENT_TYPE", "    if False:\n        return WRONG_DOCUMENT_TYPE"),
    ("checks: accept quotes that are not in the text", "condition_router/checks.py",
     'if " ".join(evidence[key].split()) not in flat:', "if False:"),
    ("checks: ignore the period rule", "condition_router/checks.py",
     "    if not period_ok(cond, start, end):\n        return WRONG_PERIOD", "    if False:\n        return WRONG_PERIOD"),
    ("checks: ignore the name rule", "condition_router/checks.py",
     'if not same_person(evidence["holder_name"], borrower):', "if False:"),
    ("checks: pay stub window excludes its first day", "condition_router/checks.py",
     "return cond.window_start <= end <= cond.window_end", "return cond.window_start < end <= cond.window_end"),
    ("checks: names match on first name only", "condition_router/checks.py",
     "return (parts[0], parts[-1]) if len(parts) >= 2 else None", "return (parts[0],) if len(parts) >= 2 else None"),
    ("gate: allow any upload id", "condition_router/gate.py",
     "if upload_id is not None and upload_id != session.upload_id:", "if False:"),
    ("gate: allow a condition from another loan", "condition_router/gate.py",
     "if cond_id is not None and cond is None:", "if False:"),
    ("gate: allow a decision before reading", "condition_router/gate.py",
     "if upload_id not in session.read:", "if False:"),
    ("gate: allow a second decision", "condition_router/gate.py",
     "if upload_id in self.decisions:", "if False:"),
    ("gate: allow unknown argument names", "condition_router/gate.py",
     "            if key not in props:", "            if False:"),
    ("gate: skip the enum check", "condition_router/gate.py",
     'if "enum" in schema and value not in schema["enum"]:', "if False:"),
    ("gate: skip the length limit", "condition_router/gate.py",
     "if len(value) > MAX_TEXT:", "if False:"),
    ("gate: skip the document checks at the full level", "condition_router/gate.py",
     'if self.level == "full" and name == "file_document":', "if False:"),
    ("audit: allow UPDATE", "condition_router/audit.py",
     'for verb in ("UPDATE", "DELETE"):', 'for verb in ("DELETE",):'),
    ("audit: verify() accepts any chain", "condition_router/audit.py",
     "if stored_prev != prev or _link(prev, fields) != stored:", "if False:"),
    ("tools: log only the calls that succeed", "condition_router/tools.py",
     "        self.audit.append(session.tenant_id,", '        if outcome == "ok": self.audit.append(session.tenant_id,'),
    ("agent: no escalation when the model never decides", "condition_router/agent.py",
     "    if forced:", "    if False:"),
    ("agent: no nudge for a model that answers in text", "condition_router/agent.py",
     "if upload_id in executor.decisions or nudges >= 1:", "if True:"),
    ("evals: a filing is never counted as wrong", "condition_router/evals.py",
     "    return action == FILE and not (truth.action == FILE and condition_id == truth.condition_id)", "    return False"),
    ("synth: injection lines are not added", "condition_router/synth.py",
     'text += INJECTION_LINE + "\\n"', "pass"),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def run_suite(cwd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "--deselect", SNAPSHOT_TEST]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900, env=env)
    failed = re.findall(r"^FAILED (\S+)", p.stdout, re.M)
    return p.returncode, failed[0] if failed else ""


def fresh_copy(dst):
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    return Path(dst)


def judge(job):
    work, i, (name, rel, old, new) = job
    copy = fresh_copy(Path(work) / f"copy{i}")
    target = copy / rel
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        return f"UNRUN    {name}: the anchor occurs {text.count(old)} times in {rel}", False
    before = digest(target)
    target.write_text(text.replace(old, new), encoding="utf-8", newline="")
    if digest(target) == before:
        return f"UNRUN    {name}: the file did not change", False
    code, first = run_suite(copy)
    if code == 0:
        return f"SURVIVED {name}", False
    return f"KILLED   {name} -> {first or 'collection error'}", True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", help="also write the table to this path")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as work:
        code, _ = run_suite(fresh_copy(Path(work) / "baseline"))
        if code != 0:
            print("the unmodified suite fails, so no mutant can be judged")
            return 2
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(judge, [(work, i, m) for i, m in enumerate(MUTANTS)]))
    lines = [line for line, _ in results]
    killed = sum(ok for _, ok in results)
    lines.append(f"{killed} of {len(MUTANTS)} guards broken in a copy made a test fail")
    out = "\n".join(lines) + "\n"
    print(out)
    if args.write:
        with open(args.write, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
