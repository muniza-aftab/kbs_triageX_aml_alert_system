"""M2 acceptance tests: the inference engine works end to end on a toy rule set.

These are not the domain tests, the real rule base arrives at M3. What is being proved
here is that the machinery behaves as ``docs/03-knowledge-model.md`` specifies: facts
combine correctly, unknowns stay unknown, frames inherit and narrow, rules that would
flatten the layer structure are rejected, and a full inference run produces a trace from
which any conclusion can be traced back to asserted input.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from triagex import frames
from triagex.dsl import (
    Cmp,
    Conclude,
    Has,
    In,
    Missing,
    Provenance,
    Rule,
    RuleSet,
    RuleValidationError,
    Var,
)
from triagex.engine import certainty, conflict
from triagex.engine.forward import ForwardChainer
from triagex.engine.trace import contributing_rules, proof_tree
from triagex.facts import (
    Asserted,
    Fact,
    FactBase,
    FactValidationError,
    MandatoryPremiseError,
    Truth,
)
from triagex.kb.reference import THRESHOLDS

ALERT = "ALT-TEST"


# --------------------------------------------------------------------------------------
# Certainty factors
# --------------------------------------------------------------------------------------


def test_conjunction_is_the_weakest_premise() -> None:
    assert certainty.conjunction([0.9, 0.4, 0.7]) == pytest.approx(0.4)


def test_empty_conjunction_is_certain() -> None:
    # A rule whose premises are all structural tests has nothing to weaken it.
    assert certainty.conjunction([]) == 1.0


def test_supporting_evidence_reinforces_without_reaching_certainty() -> None:
    combined = certainty.combine(0.7, 0.5)
    assert 0.7 < combined < 1.0
    assert combined == pytest.approx(0.85)


def test_opposing_evidence_of_equal_weight_cancels() -> None:
    assert certainty.combine(0.6, -0.6) == pytest.approx(0.0)


def test_rule_strength_caps_the_conclusion() -> None:
    assert certainty.attenuate(0.7, 1.0) == pytest.approx(0.7)
    assert certainty.attenuate(0.7, 0.5) == pytest.approx(0.35)


def test_support_bands_are_monotonic() -> None:
    assert certainty.support_band(0.9) == "strong"
    assert certainty.support_band(0.6) == "moderate"
    assert certainty.support_band(0.35) == "weak"
    assert certainty.support_band(0.1) == "none"


def test_close_incompatible_conclusions_are_irreconcilable() -> None:
    assert certainty.irreconcilable(0.60, 0.55) is True
    assert certainty.irreconcilable(0.80, 0.30) is False


# --------------------------------------------------------------------------------------
# Facts and three-valued logic
# --------------------------------------------------------------------------------------


def _fb() -> FactBase:
    return FactBase()


def test_unknown_is_not_false() -> None:
    fb = _fb()
    assert fb.truth("deposit_frequency", ALERT, "extreme") is Truth.UNKNOWN

    fb.assert_raw("deposit_frequency", ALERT, "extreme", field="test")
    assert fb.truth("deposit_frequency", ALERT, "extreme") is Truth.TRUE
    # A single-valued predicate believed at one value makes other values false.
    assert fb.truth("deposit_frequency", ALERT, "low") is Truth.FALSE


def test_truth_refuses_implicit_boolean_coercion() -> None:
    # The whole point of three-valued logic is lost if UNKNOWN can be used as falsey.
    with pytest.raises(TypeError):
        bool(Truth.UNKNOWN)


def test_not_checked_reads_as_unknown_not_as_clean() -> None:
    fb = _fb()
    fb.assert_raw("sanctions_signal", "CUS-1", "not_checked", field="customer.sanctions_signal")
    assert fb.truth("sanctions_signal", "CUS-1", "not_checked") is Truth.UNKNOWN
    assert fb.is_known("sanctions_signal", "CUS-1") is False


def test_mandatory_premises_refuse_negation_as_failure() -> None:
    fb = _fb()
    with pytest.raises(MandatoryPremiseError, match="mandatory premise"):
        fb.absent("sanctions_signal", "CUS-1")

    # Ordinary predicates are fine to reason about by absence.
    assert fb.absent("declared_purpose", "CUS-1") is True


def test_invalid_value_is_rejected() -> None:
    fb = _fb()
    with pytest.raises(FactValidationError, match="not an allowed value"):
        fb.assert_raw("composite_risk", ALERT, "catastrophic", field="test")


def test_repeated_assertion_combines_certainty() -> None:
    fb = _fb()
    fb.assert_fact(_derived("typology", ALERT, "structuring", 0.70, "R1"))
    fb.assert_fact(_derived("typology", ALERT, "structuring", 0.50, "R2"))
    assert fb.certainty_of("typology", ALERT, "structuring") == pytest.approx(0.85)


def test_multi_valued_predicates_coexist() -> None:
    fb = _fb()
    fb.assert_fact(_derived("typology", ALERT, "structuring", 0.7, "R1"))
    fb.assert_fact(_derived("typology", ALERT, "mule_account", 0.4, "R2"))
    assert len(fb.facts_for("typology", ALERT)) == 2
    assert fb.incompatibilities() == []


def test_single_valued_clash_is_reported_as_an_incompatibility() -> None:
    fb = _fb()
    fb.assert_fact(_derived("composite_risk", ALERT, "low", 0.6, "R1"))
    fb.assert_fact(_derived("composite_risk", ALERT, "severe", 0.55, "R2"))
    clashes = fb.incompatibilities()
    assert len(clashes) == 1
    first, second = clashes[0]
    assert {first.value, second.value} == {"low", "severe"}


def test_conclusions_below_the_noise_floor_are_discarded() -> None:
    fb = _fb()
    assert fb.assert_fact(_derived("typology", ALERT, "structuring", 0.05, "R1")) is None
    assert fb.facts_for("typology", ALERT) == []


def _derived(predicate: str, subject: str, value: str, cf: float, rule_id: str) -> Fact:
    from triagex.facts import Derived

    return Fact(
        predicate=predicate,
        subject=subject,
        value=value,
        cf=cf,
        derivation=Derived(rule_id=rule_id, premises=()))


# --------------------------------------------------------------------------------------
# Frames
# --------------------------------------------------------------------------------------


def test_hierarchy_resolves() -> None:
    frames.validate_hierarchy()


def test_subclass_overrides_inherited_default() -> None:
    retail = frames.resolved_slots("RetailCustomer")["expected_cash_ratio"]
    cash = frames.resolved_slots("CashIntensiveBusiness")["expected_cash_ratio"]
    assert retail.default == 0.15
    assert cash.default == 0.60


def test_inheritance_makes_parent_rules_apply_to_children() -> None:
    shop = frames.instantiate(
        "CashIntensiveBusiness",
        id="CUS-9",
        onboarding_date=date(2025, 1, 1),
        expected_monthly_turnover=40_000)
    assert shop.isa("BusinessCustomer")
    assert shop.isa("Customer")
    assert shop.get("expected_cash_ratio") == 0.60


def test_pessimistic_defaults() -> None:
    customer = frames.instantiate(
        "RetailCustomer",
        id="CUS-1",
        onboarding_date=date(2026, 1, 1),
        expected_monthly_turnover=2_000)
    # A case file that forgets these must not read as clean.
    assert customer.get("sanctions_signal") == "not_checked"
    assert customer.get("kyc_status") == "unknown"


def test_scope_markers_are_recognisable() -> None:
    crypto = frames.instantiate(
        "CryptoTransfer",
        id="T9",
        account="ACC-1",
        amount=500,
        timestamp=datetime(2026, 3, 1, 12, 0),
        direction="in",
        channel="api")
    assert crypto.is_scope_marker is True

    cash = frames.instantiate(
        "CashDeposit",
        id="T1",
        account="ACC-1",
        amount=500,
        timestamp=datetime(2026, 3, 1, 12, 0),
        channel="branch")
    assert cash.is_scope_marker is False


def test_required_slot_is_enforced() -> None:
    with pytest.raises(frames.FrameError, match="required"):
        frames.instantiate("RetailCustomer", id="CUS-2")


def test_unknown_slot_is_rejected() -> None:
    with pytest.raises(frames.FrameError, match="no slot"):
        frames.instantiate(
            "RetailCustomer",
            id="CUS-3",
            onboarding_date=date(2026, 1, 1),
            expected_monthly_turnover=1_000,
            favourite_colour="blue")


# --------------------------------------------------------------------------------------
# Rule validation
# --------------------------------------------------------------------------------------

_TOY_SOURCE = "M2 toy rule set (not domain knowledge)"


def _rule(**kwargs: object) -> Rule:
    defaults: dict[str, object] = {
        "source": _TOY_SOURCE,
        "provenance": Provenance.RECONSTRUCTED,
        "rationale": "Toy rule used to exercise the engine.",
    }
    return Rule(**{**defaults, **kwargs})  # type: ignore[arg-type]


def test_rule_may_not_flatten_the_layers() -> None:
    # A disposition derived straight from a Layer 0 measurement is exactly the
    # degenerate lookup table the layer discipline exists to prevent.
    with pytest.raises(RuleValidationError, match="not below the conclusion"):
        _rule(
            id="BAD-FLAT-01",
            layer=5,
            when=(Cmp("credit_count", Var("a"), ">=", 10),),
            then=Conclude("disposition", Var("a"), "refer_to_investigation")).validate()


def test_rule_layer_must_match_its_conclusion() -> None:
    with pytest.raises(RuleValidationError, match="declared layer"):
        _rule(
            id="BAD-LAYER-01",
            layer=2,
            when=(Has("deposit_frequency", Var("a"), "extreme"),),
            then=Conclude("composite_risk", Var("a"), "high")).validate()


def test_rationale_and_source_are_mandatory() -> None:
    with pytest.raises(RuleValidationError, match="rationale is required"):
        Rule(
            id="BAD-DOC-01",
            layer=2,
            when=(Has("deposit_frequency", Var("a"), "extreme"),),
            then=Conclude("typology", Var("a"), "structuring"),
            source="somewhere",
            provenance=Provenance.GUIDANCE,
            rationale="   ").validate()


def test_duplicate_rule_ids_are_rejected() -> None:
    rule = _rule(
        id="DUP-01",
        layer=1,
        when=(Cmp("credit_count", Var("a"), ">=", 1),),
        then=Conclude("deposit_frequency", Var("a"), "elevated"))
    with pytest.raises(RuleValidationError, match="duplicate rule id"):
        RuleSet([rule, rule])


def test_mandatory_premise_cannot_be_used_under_missing() -> None:
    rules = RuleSet(
        [
            _rule(
                id="BAD-NAF-01",
                layer=1,
                when=(
                    Has("customer_type", Var("c"), In("retail", "business")),
                    Missing("sanctions_signal", Var("c"))),
                then=Conclude("kyc_currency", Var("c"), "stale"))
        ]
    )
    fb = _fb()
    fb.assert_raw("customer_type", "CUS-1", "retail", field="customer.customer_type")

    with pytest.raises(MandatoryPremiseError):
        ForwardChainer(rules).run(fb)


# --------------------------------------------------------------------------------------
# The toy rule set
# --------------------------------------------------------------------------------------

TOY_RULES = RuleSet(
    [
        _rule(
            id="T-IND-FREQ-01",
            layer=1,
            when=(Cmp("credit_count", Var("a"), ">=", THRESHOLDS.frequency_extreme),),
            then=Conclude("deposit_frequency", Var("a"), "extreme")),
        _rule(
            id="T-IND-PROX-01",
            layer=1,
            when=(
                Cmp(
                    "max_single_credit",
                    Var("a"),
                    ">=",
                    THRESHOLDS.internal_review_threshold * THRESHOLDS.proximity_band_lower),
                Cmp("max_single_credit", Var("a"), "<", THRESHOLDS.internal_review_threshold)),
            then=Conclude("threshold_proximity", Var("a"), "high")),
        _rule(
            id="T-IND-AGG-01",
            layer=1,
            when=(Cmp("aggregate_credits", Var("a"), ">=", 20_000),),
            then=Conclude("aggregation_gap", Var("a"), "present")),
        # Base hypothesis.
        _rule(
            id="T-TYP-STRUCT-01",
            layer=2,
            strength=0.70,
            when=(
                Has("deposit_frequency", Var("a"), In("elevated", "extreme")),
                Has("threshold_proximity", Var("a"), "high")),
            then=Conclude("typology", Var("a"), "structuring")),
        # Refinement: strictly more premises, so it must win conflict resolution.
        _rule(
            id="T-TYP-STRUCT-02",
            layer=2,
            strength=0.55,
            when=(
                Has("deposit_frequency", Var("a"), In("elevated", "extreme")),
                Has("threshold_proximity", Var("a"), "high"),
                Has("aggregation_gap", Var("a"), "present")),
            then=Conclude("typology", Var("a"), "structuring")),
        _rule(
            id="T-POS-SUP-01",
            layer=3,
            when=(Has("typology", Var("a"), "structuring", min_cf=0.75),),
            then=Conclude("typology_support", Var("a"), "strong")),
    ],
    name="toy")


def _structuring_case() -> FactBase:
    fb = _fb()
    fb.assert_raw("credit_count", ALERT, 14, field="derived.credit_count")
    fb.assert_raw("max_single_credit", ALERT, 2_400.0, field="derived.max_single_credit")
    fb.assert_raw("aggregate_credits", ALERT, 33_600.0, field="derived.aggregate_credits")
    return fb


def test_forward_chaining_reaches_layer_three() -> None:
    fb = _structuring_case()
    trace = ForwardChainer(TOY_RULES).run(fb)

    assert fb.value_of("deposit_frequency", ALERT) == "extreme"
    assert fb.value_of("threshold_proximity", ALERT) == "high"
    assert fb.value_of("typology_support", ALERT) == "strong"
    assert "T-POS-SUP-01" in trace.fired_rule_ids


def test_both_structuring_rules_contribute_and_certainty_combines() -> None:
    fb = _structuring_case()
    ForwardChainer(TOY_RULES).run(fb)

    # 0.70 then 0.55 combined: 0.70 + 0.55 * 0.30
    assert fb.certainty_of("typology", ALERT, "structuring") == pytest.approx(0.865)


def test_more_specific_rule_fires_first() -> None:
    fb = _structuring_case()
    trace = ForwardChainer(TOY_RULES).run(fb)
    fired = trace.fired_rule_ids
    assert fired.index("T-TYP-STRUCT-02") < fired.index("T-TYP-STRUCT-01")


def test_inference_terminates_and_refracts() -> None:
    fb = _structuring_case()
    trace = ForwardChainer(TOY_RULES, strict=True).run(fb)

    assert trace.halted_early is False
    # Every rule fired at most once per distinct premise combination.
    assert len(trace.fired_rule_ids) == len(set(trace.fired_rule_ids))


def test_conclusions_trace_back_to_asserted_input() -> None:
    fb = _structuring_case()
    ForwardChainer(TOY_RULES).run(fb)

    support = fb.get("typology_support", ALERT, "strong")
    assert support is not None

    rendered = proof_tree(support)
    assert "typology_support(ALT-TEST) = strong" in rendered
    assert "credit_count" in rendered  # bottomed out at asserted input
    assert "asserted from derived.credit_count" in rendered

    rules = contributing_rules(support)
    assert {"T-POS-SUP-01", "T-TYP-STRUCT-01", "T-TYP-STRUCT-02", "T-IND-FREQ-01"} <= rules


def test_trace_records_what_nearly_fired() -> None:
    fb = _structuring_case()
    trace = ForwardChainer(TOY_RULES).run(fb)

    # "Why not?" is answerable only because losing activations are kept.
    assert any(e.note for e in trace.events if e.kind.value == "not_selected")
    rendered = trace.render(include_rejected=True)
    assert "more specific" in rendered


def test_no_rules_fire_on_an_empty_case() -> None:
    fb = _fb()
    trace = ForwardChainer(TOY_RULES).run(fb)
    assert trace.fired == []
    assert trace.cycles_run == 0


def test_weak_input_does_not_reach_strong_support() -> None:
    fb = _fb()
    fb.assert_raw("credit_count", ALERT, 14, field="derived.credit_count")
    fb.assert_raw("max_single_credit", ALERT, 2_400.0, field="derived.max_single_credit")
    # No aggregation gap, so only the 0.70 rule fires, below the 0.75 threshold.
    ForwardChainer(TOY_RULES).run(fb)
    assert fb.value_of("typology_support", ALERT) is None


def test_conflict_resolution_prefers_specificity_then_priority() -> None:
    fb = _structuring_case()
    trace = ForwardChainer(TOY_RULES).run(fb)
    structuring = [a for a in trace.fired if a.conclusion[0] == "typology"]
    assert len(structuring) == 2
    winner, loser = structuring[0], structuring[1]
    assert "more specific" in conflict.explain_choice(winner, loser)


def test_asserted_derivation_describes_its_origin() -> None:
    fact = Fact(
        predicate="credit_count",
        subject=ALERT,
        value=3,
        cf=1.0,
        derivation=Asserted(field="case.transactions"))
    assert "asserted from case.transactions" in proof_tree(fact)
