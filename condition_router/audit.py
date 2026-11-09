"""Append-only, hash-chained log of every tool call, kept in SQLite."""
from __future__ import annotations

import hashlib
import json
import sqlite3

GENESIS = "0" * 64
COLUMNS = ("tenant_id", "loan_id", "upload_id", "tool", "args", "outcome", "code")


def _link(prev, fields):
    return hashlib.sha256((prev + json.dumps(fields)).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, tenant_id TEXT, loan_id TEXT, "
            "upload_id TEXT, tool TEXT, args TEXT, outcome TEXT, code TEXT, prev TEXT, hash TEXT)"
        )
        for verb in ("UPDATE", "DELETE"):
            self.db.execute(
                f"CREATE TRIGGER IF NOT EXISTS audit_no_{verb.lower()} BEFORE {verb} ON audit "
                "BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END"
            )
        # INSERT OR REPLACE would delete the row it replaces without firing the DELETE trigger.
        self.db.execute(
            "CREATE TRIGGER IF NOT EXISTS audit_no_replace BEFORE INSERT ON audit "
            "WHEN EXISTS (SELECT 1 FROM audit WHERE seq = NEW.seq) "
            "BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END"
        )

    def append(self, tenant_id, loan_id, upload_id, tool, args, outcome, code=""):
        row = self.db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row[0] if row else GENESIS
        fields = [tenant_id, loan_id, upload_id, tool, json.dumps(args, sort_keys=True), outcome, code]
        self.db.execute(
            "INSERT INTO audit (tenant_id, loan_id, upload_id, tool, args, outcome, code, prev, hash) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (*fields, prev, _link(prev, fields)),
        )
        self.db.commit()

    def rows(self):
        cur = self.db.execute("SELECT seq, " + ", ".join(COLUMNS) + " FROM audit ORDER BY seq")
        return [dict(zip(("seq",) + COLUMNS, r)) for r in cur.fetchall()]

    def verify(self):
        prev = GENESIS
        for r in self.db.execute("SELECT " + ", ".join(COLUMNS) + ", prev, hash FROM audit ORDER BY seq"):
            fields, stored_prev, stored = list(r[:-2]), r[-2], r[-1]
            if stored_prev != prev or _link(prev, fields) != stored:
                return False
            prev = stored
        return True
