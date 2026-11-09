from datetime import date

import pytest

from condition_router.checks import (
    analyze, check_evidence, decide, kind_of, parse_date, period_ok, same_person,
)
from condition_router.models import (
    BANK_STATEMENT, BOUNCE, ESCALATE, EVIDENCE_NOT_IN_DOCUMENT, EVIDENCE_UNPARSEABLE, FILE, INSURANCE_DEC,
    NAME_MISMATCH, OTHER, PAY_STUB, UNREADABLE, Condition, Loan,
)
from condition_router.synth import make_world

PAY = Condition("c1", PAY_STUB, date(2026, 9, 20), date(2026, 10, 20))
BANK = Condition("c2", BANK_STATEMENT, date(2026, 9, 1), date(2026, 9, 30))
INS = Condition("c3", INSURANCE_DEC, date(2026, 12, 15), date(2026, 12, 15))
STUB = ("Cedar Ridge Logistics   EARNINGS STATEMENT\nEmployee: Jordan Rivera\nPay Period: Oct 7, 2026 - Oct 20, 2026\n"
        "Gross Pay: $3,000.00   Net Pay: $2,220.00\n")
QUOTES = {"holder_name": "Jordan Rivera", "period_start": "Oct 7, 2026", "period_end": "Oct 20, 2026"}


@pytest.mark.parametrize("text,want", [
    ("10/01/2026", date(2026, 10, 1)),
    ("2026-10-01", date(2026, 10, 1)),
    ("Oct 1, 2026", date(2026, 10, 1)),
    ("13/01/2026", None),
    ("2026-02-30", None),
    ("Foo 1, 2026", None),
    ("1O/O1/2O26", None),
])
def test_parse_date(text, want):
    assert parse_date(text) == want


def test_same_person_variants():
    assert same_person("Jordan A. Rivera", "Jordan Rivera")
    assert same_person("RIVERA, JORDAN", "Jordan Rivera")
    assert not same_person("Jordan Rivers", "Jordan Rivera")
    assert not same_person("Rivera", "Jordan Rivera")


def test_period_rule_boundaries():
    assert period_ok(PAY, date(2026, 10, 7), date(2026, 10, 20))
    assert period_ok(PAY, date(2026, 9, 7), date(2026, 9, 20))
    assert not period_ok(PAY, date(2026, 10, 8), date(2026, 10, 21))
    assert not period_ok(PAY, date(2026, 9, 6), date(2026, 9, 19))
    assert period_ok(BANK, date(2026, 9, 1), date(2026, 9, 30))
    assert not period_ok(BANK, date(2026, 8, 31), date(2026, 9, 30))
    assert not period_ok(BANK, date(2026, 10, 1), date(2026, 10, 31))
    assert period_ok(INS, date(2025, 12, 15), date(2026, 12, 15))
    assert not period_ok(INS, date(2025, 12, 14), date(2026, 12, 14))
    assert not period_ok(INS, date(2026, 12, 16), date(2027, 12, 16))
    assert not period_ok(PAY, date(2026, 10, 20), date(2026, 10, 7))


def test_analyze_reads_each_layout():
    text = "Cedar Ridge Logistics   EARNINGS STATEMENT\nEmployee: RIVERA, JORDAN\nPay Period: Oct 7, 2026 - Oct 20, 2026\n"
    f = analyze(text)
    assert (f.kind, f.holder, f.start, f.end) == (PAY_STUB, "RIVERA, JORDAN", date(2026, 10, 7), date(2026, 10, 20))
    assert kind_of("Evergreen Electric   MONTHLY BILL\nAccount Holder: A B\n") == OTHER


def test_garbled_period_line_is_not_read():
    f = analyze("EARNINGS STATEMENT\nEmployee: Jordan Rivera\nPay Per1od: l0/O7/2O26 - l0/2O/2O26\n")
    assert f.start is None and f.end is None


def test_words_that_are_in_the_document_but_are_not_dates_are_unparseable_evidence():
    assert check_evidence(STUB, 0.9, PAY, "Jordan Rivera", QUOTES) is None
    not_dates = dict(QUOTES, period_start="Gross Pay", period_end="Net Pay")
    assert check_evidence(STUB, 0.9, PAY, "Jordan Rivera", not_dates) == EVIDENCE_UNPARSEABLE


def test_each_of_the_three_quotes_must_be_in_the_document():
    holder_written_another_way = STUB.replace("Jordan Rivera", "RIVERA, JORDAN")
    assert check_evidence(holder_written_another_way, 0.9, PAY, "Jordan Rivera", QUOTES) == EVIDENCE_NOT_IN_DOCUMENT
    for key, value in (("period_start", "Oct 8, 2026"), ("period_end", "Oct 19, 2026")):
        assert check_evidence(STUB, 0.9, PAY, "Jordan Rivera", dict(QUOTES, **{key: value})) == EVIDENCE_NOT_IN_DOCUMENT


def test_a_quote_may_not_start_or_end_inside_a_word_or_a_number():
    text = "EARNINGS STATEMENT\nEmployee: Ann Leeson\nPay Period: 11/07/2026 - 11/20/2026\n"
    prefix_of_a_name = {"holder_name": "Ann Lee", "period_start": "11/07/2026", "period_end": "11/20/2026"}
    assert check_evidence(text, 0.9, PAY, "Ann Lee", prefix_of_a_name) == EVIDENCE_NOT_IN_DOCUMENT
    tail_of_a_number = {"holder_name": "Ann Leeson", "period_start": "1/07/2026", "period_end": "1/20/2026"}
    assert check_evidence(text, 0.9, PAY, "Ann Leeson", tail_of_a_number) == EVIDENCE_NOT_IN_DOCUMENT


def test_a_quote_is_matched_after_its_whitespace_is_collapsed():
    spaced = dict(QUOTES, holder_name="Jordan   Rivera")
    assert check_evidence(STUB, 0.9, PAY, "Jordan Rivera", spaced) is None
    assert check_evidence(STUB.replace("Jordan Rivera", "Jordan  Rivera"), 0.9, PAY, "Jordan Rivera", QUOTES) is None


def test_the_confidence_floor_is_at_or_above_0_75():
    loan = Loan("L1", "T1", "Jordan Rivera", (PAY, BANK, INS))
    assert check_evidence(STUB, 0.75, PAY, "Jordan Rivera", QUOTES) is None
    assert check_evidence(STUB, 0.7499, PAY, "Jordan Rivera", QUOTES) == UNREADABLE
    assert decide(STUB, 0.75, loan) == decide(STUB, 0.99, loan) and decide(STUB, 0.75, loan).action == FILE
    assert (decide(STUB, 0.7499, loan).action, decide(STUB, 0.7499, loan).reason) == (BOUNCE, UNREADABLE)


def test_decide_order_unreadable_first():
    w = make_world(0)
    loan = next(iter(w.loans.values()))
    text = "EARNINGS STATEMENT\nEmployee: Someone Else\nPay Period: 10/07/2026 - 10/20/2026\n"
    assert decide(text, 0.5, loan).reason == UNREADABLE
    assert decide(text, 0.95, loan).reason == NAME_MISMATCH


def test_rule_baseline_matches_the_generator_labels():
    """The labels come from how each document was built, so agreement here is not circular."""
    for seed in range(40):
        w = make_world(seed)
        for uid, up in w.uploads.items():
            d, t = decide(up.text, up.ocr_confidence, w.loan_of(uid)), w.truth[uid]
            assert (d.action, d.condition_id, d.reason) == (t.action, t.condition_id, t.reason), (seed, uid, t.scenario)
            assert d.action in (FILE, BOUNCE, ESCALATE)
