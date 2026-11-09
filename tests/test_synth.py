from collections import Counter

from condition_router.models import ACTIONS, FILE
from condition_router.synth import INJECTION_LINE, SCENARIOS, make_world


def test_same_seed_gives_same_world():
    a, b = make_world(3), make_world(3)
    assert [u.text for u in a.uploads.values()] == [u.text for u in b.uploads.values()]
    assert a.truth == b.truth


def test_different_seeds_differ():
    assert [u.text for u in make_world(3).uploads.values()] != [u.text for u in make_world(4).uploads.values()]


def test_shape_and_tenant_ownership():
    w = make_world(1)
    assert len(w.loans) == 6 and len(w.uploads) == 36
    assert {l.tenant_id for l in w.loans.values()} == {"T1", "T2"}
    for up in w.uploads.values():
        assert w.loans[up.loan_id].tenant_id == up.tenant_id
        tr = w.truth[up.id]
        assert tr.action in ACTIONS
        if tr.action == FILE:
            assert tr.condition_id in {c.id for c in w.loan_of(up.id).conditions}
        else:
            assert tr.condition_id is None


def test_scenario_mix_is_close_to_the_weights():
    counts = Counter(t.scenario for s in range(30) for t in make_world(s).truth.values())
    total = sum(counts.values())
    for name, weight in SCENARIOS:
        assert abs(counts[name] / total - weight) < 0.06, name


def test_injection_and_confidence_markers():
    for s in range(10):
        w = make_world(s)
        for uid, up in w.uploads.items():
            scenario = w.truth[uid].scenario
            assert (INJECTION_LINE in up.text) == (scenario == "injection")
            assert (up.ocr_confidence < 0.7) == (scenario == "unreadable")
