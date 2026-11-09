from datetime import date

import pytest

from condition_router.checks import (
    analyze, decide, kind_of, parse_date, period_ok, same_person,
)
from condition_router.models import (
    BANK_STATEMENT, BOUNCE, ESCALATE, FILE, INSURANCE_DEC, NAME_MISMATCH, OTHER, PAY_STUB,
    UNREADABLE, WRONG_PERIOD, Condition,
)
from condition_router.synth import make_world

PAY = Condition("c1", PAY_STUB, date(2026, 9, 20), date(2026, 10, 20))
BANK = Condition("c2", BANK_STATEMENT, date(2026, 9, 1), date(2026, 9, 30))
INS = Condition("c3", INSURANCE_DEC, date(2026, 12, 15), date(2026, 12, 15))


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
