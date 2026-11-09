"""Replay the uploads of a stored local-model run in which a valid upload was not filed.

The stored records keep counts and flags, not the model's arguments. This runs the same model with the same sampling
seeds behind the same gate and prints every decision call and what the gate answered, so a refusal can be read next
to the document. It needs the model server that made the run.

    python -m condition_router.replay results/ollama.records.jsonl --out results/ollama-missed-calls.txt
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .agent import run_upload
from .audit import AuditLog
from .checks import _quoted_in, analyze, parse_date, same_person
from .evals import EVIDENCE_KEYS, Record, setup_digest
from .ollama_model import ollama_factory
from .specs import TERMINAL
from .synth import make_world
from .tools import Executor

SAME_VALUE = ("same date, other format", "same name, written another way")
WRONG_FIELD = "the document's other date"


def quote_kind(key, quote, text):
    """How a quote that is not in the document relates to it.

    The same value in the same position written another way, the date from the other end of the period, or neither.
    """
    facts = analyze(text)
    if key == "holder_name":
        return SAME_VALUE[1] if facts.holder and same_person(quote, facts.holder) else "other"
    when = parse_date(quote)
    wanted, other = (facts.start, facts.end) if key == "period_start" else (facts.end, facts.start)
    if when is not None and when == wanted:
        return SAME_VALUE[0]
    if when is not None and when == other:
        return WRONG_FIELD
    return "other"


def missing_quotes(evidence, text):
    """For a filing's evidence, {key: kind} for each quote that is not in the document as quoted."""
    flat = " ".join(text.split())
    return {k: quote_kind(k, evidence[k], text) for k in EVIDENCE_KEYS
            if isinstance(evidence.get(k), str) and not _quoted_in(evidence[k], flat)}


def describe(row, text):
    args = json.loads(row["args"])
    if row["tool"] == "file_document" and isinstance(args, dict) and isinstance(args.get("evidence"), dict):
        ev = args["evidence"]
        line = f"file_document condition={args.get('condition_id')} " + " ".join(f"{k}={ev.get(k)!r}" for k in EVIDENCE_KEYS)
        if row["code"] == "EVIDENCE_NOT_IN_DOCUMENT":
            line += " [" + "; ".join(f"{k}: {v}" for k, v in missing_quotes(ev, text).items()) + "]"
    else:
        line = f"{row['tool']} {json.dumps(args, sort_keys=True)[:140]}"
    return f"{line} -> {row['outcome']}{' ' + row['code'] if row['code'] else ''}"


def replay(records_path, host):
    lines = Path(records_path).read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])["meta"]
    if meta.get("setup") != setup_digest():
        raise SystemExit("the system prompt or the tool descriptions changed since this run, so a replay would differ")
    records = [Record(**json.loads(line)) for line in lines[1:]]
    out, tally, worlds = [f"model {meta['model']}, temperature {meta['temperature']}, replayed from {Path(records_path).name}"], Counter(), {}
    for rec in (r for r in records if r.missed_fill):
        world = worlds.setdefault(rec.seed, make_world(rec.seed))
        text = world.uploads[rec.upload_id].text
        ex = Executor(world, AuditLog(), "full")
        trace = run_upload(ollama_factory(meta["model"], host, meta["temperature"], rec.seed)(world, rec.upload_id, rec.repeat), ex, rec.upload_id)
        rows = ex.audit.rows()
        same = trace.final.action == rec.final_action and dict(Counter(r["code"] for r in rows if r["outcome"] == "refused")) == rec.refusals
        tally["replays"] += 1
        tally["matching the stored record"] += same
        out += ["", f"{rec.upload_id}: label {rec.label_action}, stored final {rec.final_action}, replay final {trace.final.action}, "
                    f"replay matches the stored record: {'yes' if same else 'NO'}",
                "  document: " + " | ".join(text.splitlines()[1:3])]
        upload_kinds = set()
        for row in rows:
            if row["tool"] in TERMINAL:
                out.append("  " + describe(row, text))
                if row["code"] == "EVIDENCE_NOT_IN_DOCUMENT":
                    kinds = set(missing_quotes(json.loads(row["args"])["evidence"], text).values())
                    tally["refused for quotes not in the document"] += 1
                    tally["of those, only the format of a date or a name differs"] += bool(kinds) and kinds <= set(SAME_VALUE)
                    tally["of those, a quoted date is the document's other date"] += WRONG_FIELD in kinds
                    upload_kinds |= kinds
        if same and upload_kinds:
            tally["matching replays with a filing refused for its quotes"] += 1
            tally["of those, every refused quote differs only in format"] += upload_kinds <= set(SAME_VALUE)
            tally["of those, a refused quote is the document's other date"] += WRONG_FIELD in upload_kinds
    out += ["", "summary"] + [f"  {k}: {v}" for k, v in tally.items()]
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(prog="condition_router.replay")
    p.add_argument("records")
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    text = replay(args.records, args.host)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
