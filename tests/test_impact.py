import random

import pytest

from slipcheck import load_reference, validate
from slipcheck.impact import (
    ERROR_LABEL, TODAY, _clean_slip, impact, inject, load_assumptions, measure_detection, model, scenario_values,
)


@pytest.fixture(scope="module")
def ref():
    return load_reference()


@pytest.fixture(scope="module")
def result(ref):
    return impact(ref, n=120, seed=3)


def test_clean_synthetic_slips_pass(ref):
    rng = random.Random(1)
    statuses = {validate(_clean_slip(rng, ref), ref, TODAY).status for _ in range(100)}
    assert statuses == {"READY"}


@pytest.mark.parametrize("kind", list(ERROR_LABEL))
def test_every_injection_changes_the_slip(ref, kind):
    rng = random.Random(2)
    clean = _clean_slip(rng, ref)
    dirty, _ = inject(kind, _clean_slip(random.Random(2), ref), random.Random(5), ref)
    assert dirty != clean


def test_rules_catch_what_they_are_built_for(result):
    d = result["detection"]
    for kind in ("closed_wo", "pairs_no_unit", "illegible", "missing_signature"):
        assert d[kind]["caught"] == 1.0, kind
    assert d["name_only"]["auto_wrong"] == 0  # never silently picks the wrong part


def test_errors_invisible_on_the_slip_are_not_claimed_as_caught(result):
    # A wrong but plausible quantity contradicts nothing on the slip; the model must not
    # credit the checker with catching it.
    assert result["detection"]["plausible_wrong_qty"]["caught"] < 0.1


def test_scenarios_are_ordered_and_the_floor_can_be_negative(result):
    s = result["scenarios"]
    saved = [s[w]["hours_per_year_saved"] for w in ("pessimistic", "likely", "optimistic")]
    assert saved == sorted(saved)
    assert s["likely"]["hours_per_year_saved"] > 0


def test_break_even_is_where_savings_cross_zero(ref):
    a = load_assumptions()
    det, fa = measure_detection(ref, n=60, seed=3)
    mix, v = a["error_mix"]["shares"], scenario_values(a, "pessimistic")

    def saved(share):
        return model(v | {"slip_caused_share": share}, mix, det, fa)["hours_per_week"]["saved"]

    s_star = model(v, mix, det, fa)["break_even_slip_share"]
    assert 0 < s_star < 1
    assert saved(s_star) == pytest.approx(0, abs=1e-9)
    assert saved(s_star + 0.1) > 0 > saved(s_star - 0.1)


def test_more_slip_caused_mismatches_means_more_saved(ref):
    a = load_assumptions()
    det, fa = measure_detection(ref, n=60, seed=4)
    mix = a["error_mix"]["shares"]
    v = scenario_values(a, "likely")
    saved = [model(v | {"slip_caused_share": s}, mix, det, fa)["hours_per_year_saved"] for s in (0.2, 0.5, 0.8)]
    assert saved == sorted(saved)


def test_excluded_items_stay_out_of_the_math():
    a = load_assumptions()
    assert a["excluded"]["cost_allocation"]["source"] == "unknown"
    assert "receiving_callbacks" in a["excluded"]
