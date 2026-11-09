"""Plain data types: loans, open conditions, uploads and the labels the evaluation scores against."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

PAY_STUB = "pay_stub"
BANK_STATEMENT = "bank_statement"
INSURANCE_DEC = "insurance_dec"
OTHER = "other"
CONDITION_KINDS = (PAY_STUB, BANK_STATEMENT, INSURANCE_DEC)

FILE = "file"
BOUNCE = "bounce"
ESCALATE = "escalate"
ACTIONS = (FILE, BOUNCE, ESCALATE)

WRONG_PERIOD = "WRONG_PERIOD"
UNREADABLE = "UNREADABLE"
NAME_MISMATCH = "NAME_MISMATCH"
NO_OPEN_CONDITION = "NO_OPEN_CONDITION"
BOUNCE_REASONS = (WRONG_PERIOD, UNREADABLE)


@dataclass(frozen=True)
class Condition:
    id: str
    kind: str
    window_start: date
    window_end: date


@dataclass(frozen=True)
class Upload:
    id: str
    loan_id: str
    tenant_id: str
    text: str
    ocr_confidence: float


@dataclass(frozen=True)
class Loan:
    id: str
    tenant_id: str
    borrower: str
    conditions: tuple


@dataclass(frozen=True)
class Truth:
    """What a careful processor would do with one upload. Set by the generator, never by the checks."""

    action: str
    condition_id: Optional[str]
    reason: Optional[str]
    scenario: str


@dataclass
class World:
    loans: dict
    uploads: dict
    truth: dict

    def loan_of(self, upload_id):
        return self.loans[self.uploads[upload_id].loan_id]
