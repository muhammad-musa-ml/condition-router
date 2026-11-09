"""Read the fields a condition needs out of an upload, and apply the rules a condition states."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .models import (
    BANK_STATEMENT, BOUNCE, ESCALATE, FILE, INSURANCE_DEC, MONTHS, NAME_MISMATCH, NO_OPEN_CONDITION,
    OTHER, PAY_STUB, UNREADABLE, WRONG_PERIOD,
)

LEGIBLE_AT = 0.75

_US = r"\d{1,2}/\d{1,2}/\d{4}"
_ISO = r"\d{4}-\d{2}-\d{2}"
_LONG = r"[A-Z][a-z]{2} \d{1,2}, \d{4}"
DATE_RE = re.compile(f"{_US}|{_ISO}|{_LONG}")
_HOLDER = re.compile(r"^(?:Employee|Account Holder|Named Insured): *(.+?) *$", re.M)
_PERIOD = re.compile(r"^(?:Pay Period|Statement Period|Policy Period|Service Period): *(.+?) *$", re.M)

KIND_MARKERS = {
    PAY_STUB: ("earnings statement", "pay period"),
    BANK_STATEMENT: ("account statement", "statement period"),
    INSURANCE_DEC: ("declarations page", "policy period"),
}


def parse_date(s) -> Optional[date]:
    s = s.strip()
    try:
        if re.fullmatch(_ISO, s):
            return date.fromisoformat(s)
        if re.fullmatch(_US, s):
            month, day, year = s.split("/")
            return date(int(year), int(month), int(day))
        m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", s)
        if m and m.group(1) in MONTHS:
            return date(int(m.group(3)), MONTHS.index(m.group(1)) + 1, int(m.group(2)))
    except ValueError:
        return None
    return None


def kind_of(text) -> str:
    low = text.lower()
    for kind, markers in KIND_MARKERS.items():
        if any(m in low for m in markers):
            return kind
    return OTHER


@dataclass(frozen=True)
class Facts:
    kind: str
    holder: Optional[str]
    start: Optional[date]
    end: Optional[date]


def analyze(text) -> Facts:
    holder = _HOLDER.search(text)
    start = end = None
    period = _PERIOD.search(text)
    if period:
        found = DATE_RE.findall(period.group(1))
        if len(found) == 2:
            start, end = parse_date(found[0]), parse_date(found[1])
    return Facts(kind_of(text), holder.group(1) if holder else None, start, end)


def _name_key(name):
    if "," in name:
        last, _, first = name.partition(",")
        parts = f"{first} {last}".split()
    else:
        parts = name.split()
    parts = [p.strip(".").lower() for p in parts if p.strip(".")]
    return (parts[0], parts[-1]) if len(parts) >= 2 else None


def same_person(a, b) -> bool:
    ka = _name_key(a)
    return ka is not None and ka == _name_key(b)


def period_ok(cond, start, end) -> bool:
    if start is None or end is None or end < start:
        return False
    if cond.kind == INSURANCE_DEC:
        return start <= cond.window_end <= end
    if cond.kind == BANK_STATEMENT:
        return cond.window_start <= start and end <= cond.window_end
    return cond.window_start <= end <= cond.window_end


@dataclass(frozen=True)
class Decision:
    action: str
    condition_id: Optional[str]
    reason: Optional[str]


def decide(text, ocr_confidence, loan) -> Decision:
    """The rule-based processor. It reads the strict layout only, so it is the baseline the model is compared with."""
    facts = analyze(text)
    if ocr_confidence < LEGIBLE_AT or facts.start is None or facts.holder is None:
        return Decision(BOUNCE, None, UNREADABLE)
    matching = [c for c in loan.conditions if c.kind == facts.kind]
    if not matching:
        return Decision(ESCALATE, None, NO_OPEN_CONDITION)
    if not same_person(facts.holder, loan.borrower):
        return Decision(ESCALATE, None, NAME_MISMATCH)
    for c in matching:
        if period_ok(c, facts.start, facts.end):
            return Decision(FILE, c.id, None)
    return Decision(BOUNCE, None, WRONG_PERIOD)
