"""M4 acceptance tests: the case library and the loader.

Every case file is a claim, and this module checks the claims. A case that declares a
disposition must reach it; a case that names rules must fire them; a case that names rules it
must *not* fire must not fire them.

The generated corpus is checked differently. Its labels are true by construction, so agreement
with them measures consistency rather than accuracy, the tests assert a floor on agreement
and on abstention, not perfection, because a synthetic corpus that the system matched
perfectly would only prove the corpus was built from the same assumptions as the rules.
"""

from __future__ import annotations

from datetime import date

import pytest

from triagex.data.generator import DEFAULT_WEIGHTS, PROFILES, generate
from triagex.data.loader import (
    CASE_DIR,
    CaseFormatError,
    case_paths,
    factbase_for,
    load_library,
    measurements,
    parse_case,
)
from triagex.kb.meta import META_CONFLICT, META_PREMISE, META_SUPPORT
from triagex.kb.predicates import DISPOSITIONS
from triagex.pipeline import Assessment, assess, assess_measurements

LIBRARY = load_library()
BY_NAME = {case.source_path.stem: case for case in LIBRARY if case.source_path}

META_RULES = {META_SUPPORT, META_CONFLICT, META_PREMISE}


def _assess(case) -> Assessment:  # type: ignore[no-untyped-def]
    return assess(factbase_for(case), case.alert_id)


def _rules_involved(result: Assessment) -> set[str]:
    """Every rule or stage that contributed, including the decision stage itself."""
    return {*result.trace.fired_rule_ids, result.decision.stage.id, *META_RULES}


# --------------------------------------------------------------------------------------
# The library loads
# --------------------------------------------------------------------------------------


def test_library_is_not_empty() -> None:
    assert len(LIBRARY) >= 20


def test_every_case_file_parses() -> None:
    assert len(LIBRARY) == len(case_paths())


def test_alert_ids_are_unique() -> None:
    ids = [case.alert_id for case in LIBRARY]
    assert len(ids) == len(set(ids))


def test_every_case_is_documented() -> None:
    for case in LIBRARY:
        assert case.expectation.notes.strip(), f"{case.alert_id} has no notes"


def test_every_disposition_appears_in_the_library() -> None:
    declared = {c.expectation.disposition for c in LIBRARY if c.expectation.disposition}
    # refuse_to_decide by deficiency is deliberately absent: it is a coverage defect, so a
    # case asserting it would be asserting that the knowledge base stays broken.
    assert declared == set(DISPOSITIONS)


# --------------------------------------------------------------------------------------
# Loader behaviour
# --------------------------------------------------------------------------------------


def test_repeat_expands_into_individual_transactions() -> None:
    case = BY_NAME["request_structuring_no_sof_01"]
    assert len(case.credits()) == 14
    ids = [t.id for t in case.credits()]
    assert len(set(ids)) == 14, "each repeated transaction must stay individually identifiable"


def test_amount_step_walks_the_amount() -> None:
    case = BY_NAME["refer_mule_hub_01"]
    amounts = sorted(float(t.require("amount")) for t in case.credits())
    assert amounts[0] == 640.0
    assert amounts[-1] == 640.0 + 15.0 * 13


def test_measurements_are_computed_not_declared() -> None:
    case = BY_NAME["request_structuring_no_sof_01"]
    m = measurements(case)
    assert m["credit_count"] == 14
    assert m["max_single_credit"] == 2_400.0
    assert m["aggregate_credits"] == pytest.approx(33_600.0)
    assert m["cash_ratio"] == pytest.approx(1.0)  # every credit came in at a branch


def test_omitted_screening_becomes_not_checked_not_none() -> None:
    # The pessimistic default, demonstrated through a real case file rather than asserted.
    case = BY_NAME["refuse_never_screened_01"]
    assert case.source_path is not None
    lines = case.source_path.read_text(encoding="utf-8").splitlines()
    assert not any(line.strip().startswith("sanctions_signal =") for line in lines)
    assert measurements(case)["sanctions_signal"] == "not_checked"


def test_frame_inheritance_supplies_the_cash_expectation() -> None:
    takeaway = measurements(BY_NAME["clear_cash_intensive_legitimate_01"])
    salaried = measurements(BY_NAME["clear_salaried_01"])
    assert takeaway["expected_cash_ratio"] == 0.60
    assert salaried["expected_cash_ratio"] == 0.15


def test_malformed_case_is_rejected_at_the_door() -> None:
    with pytest.raises(CaseFormatError, match="missing required section"):
        parse_case({"alert_id": "X"})


def test_invalid_slot_value_is_rejected_with_the_slot_named() -> None:
    with pytest.raises(CaseFormatError, match="kyc_status"):
        parse_case(
            {
                "alert_id": "X",
                # tomllib yields real date objects, so the test supplies them too.
                "window": {"start": date(2026, 3, 1), "end": date(2026, 3, 7)},
                "customer": {
                    "frame": "RetailCustomer",
                    "id": "C",
                    "onboarding_date": date(2020, 1, 1),
                    "expected_monthly_turnover": 100,
                    "kyc_status": "probably fine",
                },
            }
        )


def test_dates_must_be_dates() -> None:
    with pytest.raises(CaseFormatError, match="expected a date"):
        parse_case(
            {
                "alert_id": "X",
                "window": {"start": "not a date", "end": "also not"},
                "customer": {"frame": "RetailCustomer", "id": "C"},
            }
        )


# --------------------------------------------------------------------------------------
# Every case meets its own claim
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(BY_NAME), ids=sorted(BY_NAME))
def test_case_reaches_its_declared_disposition(name: str) -> None:
    case = BY_NAME[name]
    if case.expectation.disposition is None:
        pytest.skip("case asserts rule behaviour rather than an outcome")
    result = _assess(case)
    assert result.outcome == case.expectation.disposition, (
        f"{case.alert_id}: {case.expectation.notes.strip()[:120]}"
    )


@pytest.mark.parametrize("name", sorted(BY_NAME), ids=sorted(BY_NAME))
def test_case_fires_the_rules_it_claims(name: str) -> None:
    case = BY_NAME[name]
    if not case.expectation.must_fire:
        pytest.skip("no must_fire claim")
    involved = _rules_involved(_assess(case))
    missing = [rule for rule in case.expectation.must_fire if rule not in involved]
    assert not missing, f"{case.alert_id} did not fire {missing}"


@pytest.mark.parametrize("name", sorted(BY_NAME), ids=sorted(BY_NAME))
def test_case_does_not_fire_the_rules_it_excludes(name: str) -> None:
    case = BY_NAME[name]
    if not case.expectation.must_not_fire:
        pytest.skip("no must_not_fire claim")
    fired = set(_assess(case).trace.fired_rule_ids)
    unexpected = [rule for rule in case.expectation.must_not_fire if rule in fired]
    assert not unexpected, f"{case.alert_id} unexpectedly fired {unexpected}"


@pytest.mark.parametrize("name", sorted(BY_NAME), ids=sorted(BY_NAME))
def test_abstentions_name_the_expected_reason(name: str) -> None:
    case = BY_NAME[name]
    if not case.expectation.reason:
        pytest.skip("no reason claim")
    result = _assess(case)
    assert result.decision.stage.reason == case.expectation.reason
    assert result.decision.reasons, "an abstention must say what it could not handle"


def test_no_library_case_falls_through_to_a_deficiency() -> None:
    offenders = [c.alert_id for c in LIBRARY if _assess(c).decision.stage.id == "DISP-DEFICIENT-01"]
    assert not offenders, f"coverage gap in the knowledge base for: {offenders}"


# --------------------------------------------------------------------------------------
# The generated corpus
# --------------------------------------------------------------------------------------


def test_generation_is_reproducible() -> None:
    first = generate(40, seed=7)
    second = generate(40, seed=7)
    assert [c.measurements for c in first] == [c.measurements for c in second]
    assert [c.alert_id for c in first] == [c.alert_id for c in second]


def test_different_seeds_give_different_corpora() -> None:
    assert [c.measurements for c in generate(40, seed=7)] != [
        c.measurements for c in generate(40, seed=8)
    ]


def test_weights_cover_every_profile() -> None:
    assert set(DEFAULT_WEIGHTS) == set(PROFILES)
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_generated_case_produces_a_valid_disposition() -> None:
    for gen in generate(150, seed=11):
        result = assess_measurements(gen.alert_id, gen.measurements)
        assert result.outcome in DISPOSITIONS


def test_generated_corpus_broadly_agrees_with_its_own_labels() -> None:
    """Agreement measures consistency, not accuracy, the labels are true by construction.

    The floor is deliberately not 100%: profiles overlap at the edges on purpose, and a
    corpus the system matched perfectly would only show the generator and the rule base
    shared assumptions.
    """
    cases = generate(200, seed=13)
    agreed = sum(
        assess_measurements(g.alert_id, g.measurements).outcome == g.expected_family
        for g in cases
    )
    assert agreed / len(cases) >= 0.60


def test_generator_produces_cases_the_system_declines() -> None:
    # A corpus that never triggers an abstention cannot exercise the mechanism at all.
    cases = generate(200, seed=13)
    abstained = sum(
        assess_measurements(g.alert_id, g.measurements).outcome == "refuse_to_decide"
        for g in cases
    )
    assert abstained >= 10


def test_clean_profile_is_mostly_cleared() -> None:
    clean = [g for g in generate(300, seed=17) if g.intent == "clean"]
    assert len(clean) >= 30
    cleared = sum(
        assess_measurements(g.alert_id, g.measurements).outcome == "clear" for g in clean
    )
    assert cleared / len(clean) >= 0.80, "too many false positives on unremarkable accounts"


def test_case_directory_is_packaged() -> None:
    assert CASE_DIR.is_dir()
    assert any(CASE_DIR.glob("*.toml"))
