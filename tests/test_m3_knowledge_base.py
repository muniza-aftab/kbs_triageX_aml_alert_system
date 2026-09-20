"""M3 acceptance tests: the real knowledge base reaches every disposition.

Two kinds of test here. The first group are *structural*: properties every rule must have,
checked across the whole rule base so a new rule cannot quietly break them. The second group
are *behavioural*: one case per disposition, proving each path through the decision list is
reachable and lands where the knowledge model says it should.

A disposition that no case can reach is dead knowledge, and the abstention outcomes are the
easiest of all to leave untested, since nothing fails when a system never admits ignorance.
"""

from __future__ import annotations

import pytest

from triagex.dsl import PERMITTED_PREMISE_LAYERS, Provenance
from triagex.kb.disposition import DECISION_LIST, FALLTHROUGH
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.meta import find_evidential_conflicts
from triagex.kb.predicates import DISPOSITIONS, spec_for
from triagex.kb.veto import PERMISSIVE_OUTCOMES, VETO_RULES
from triagex.pipeline import assess_measurements

ALERT = "ALT-TEST"


# --------------------------------------------------------------------------------------
# Baseline case
# --------------------------------------------------------------------------------------

CLEAN: dict[str, object] = {
    "credit_count": 3,
    "max_single_credit": 450.0,
    "aggregate_credits": 1_200.0,
    "distinct_channels": 1,
    "account_age_days": 900,
    "days_since_prior_activity": 2,
    "outflow_within_window_ratio": 0.20,
    "closing_to_inflow_ratio": 0.60,
    "cash_ratio": 0.05,
    "expected_cash_ratio": 0.15,
    "observed_monthly_turnover": 1_200.0,
    "expected_monthly_turnover": 2_200.0,
    "payer_hub_degree": 1,
    "undeclared_payer_count": 0,
    "worst_fatf_status": "compliant",
    "customer_type": "retail",
    "kyc_status": "complete",
    "sanctions_signal": "none",
    "pep_status": "none",
    "source_of_funds_evidence": "present",
    "adverse_media": "none",
    "declared_purpose": "consistent",
}


def case(**overrides: object) -> dict[str, object]:
    return {**CLEAN, **overrides}


def run(**overrides: object):  # type: ignore[no-untyped-def]
    return assess_measurements(ALERT, case(**overrides))  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Structural properties of the rule base
# --------------------------------------------------------------------------------------


def test_every_rule_carries_provenance_and_a_rationale() -> None:
    for rule in KNOWLEDGE_BASE:
        assert rule.source.strip(), f"{rule.id} has no source"
        assert rule.rationale.strip(), f"{rule.id} has no rationale"
        assert isinstance(rule.provenance, Provenance)


def test_rationales_are_written_for_a_human_not_a_developer() -> None:
    # The rationale is rendered directly in explanations, so a one-word note is a defect.
    for rule in KNOWLEDGE_BASE:
        assert len(rule.rationale.split()) >= 5, f"{rule.id} rationale is too terse"


def test_no_rule_reads_above_its_permitted_layers() -> None:
    for rule in KNOWLEDGE_BASE:
        permitted = PERMITTED_PREMISE_LAYERS[rule.layer]
        for predicate in rule.premise_predicates():
            assert spec_for(predicate).layer in permitted, (
                f"{rule.id} (layer {rule.layer}) reads {predicate} "
                f"(layer {spec_for(predicate).layer})"
            )


def test_rule_ids_are_unique_and_prefixed_by_layer() -> None:
    prefixes: dict[int, str | tuple[str, ...]] = {
        1: "IND-",
        2: "TYP-",
        3: "POS-",
        4: ("POS-", "VETO-"),
    }
    for rule in KNOWLEDGE_BASE:
        expected = prefixes[rule.layer]
        assert rule.id.startswith(expected), f"{rule.id} does not match layer {rule.layer}"


def test_veto_layer_can_only_block_permissive_outcomes() -> None:
    # The design constraint that makes an override mechanism safe to have at all.
    for rule in VETO_RULES:
        assert rule.then.predicate == "disposition_blocked"
        assert rule.then.value in PERMISSIVE_OUTCOMES, (
            f"{rule.id} blocks {rule.then.value!r}: the veto layer must never be able to "
            f"suppress escalation or abstention"
        )


def test_exculpatory_rules_exist() -> None:
    # Without negative evidence the system can only ever grow more suspicious.
    negative = [r for r in KNOWLEDGE_BASE if r.strength < 0]
    assert len(negative) >= 4
    assert all(r.layer == 2 for r in negative)


def test_every_disposition_is_reachable_from_the_decision_list() -> None:
    reachable = {stage.outcome for stage in (*DECISION_LIST, FALLTHROUGH)}
    assert reachable == set(DISPOSITIONS)


def test_abstentions_always_name_a_reason() -> None:
    for stage in (*DECISION_LIST, FALLTHROUGH):
        if stage.outcome == "refuse_to_decide":
            assert stage.reason, f"{stage.id} abstains without naming why"


# --------------------------------------------------------------------------------------
# Behaviour: one case per disposition
# --------------------------------------------------------------------------------------


def test_clean_case_is_cleared() -> None:
    result = run()
    assert result.outcome == "clear"
    assert result.facts.value_of("typology_support", ALERT) == "none"
    assert result.facts.value_of("composite_risk", ALERT) == "low"


def test_structuring_with_missing_evidence_asks_before_escalating() -> None:
    result = run(
        credit_count=14,
        max_single_credit=2_400.0,
        aggregate_credits=33_600.0,
        account_age_days=21,
        observed_monthly_turnover=33_600.0,
        source_of_funds_evidence="absent")
    assert result.outcome == "request_evidence"
    assert result.facts.value_of("typology_support", ALERT) == "strong"
    assert result.facts.value_of("evidence_sufficiency", ALERT) == "partial"


def test_structuring_with_complete_evidence_escalates() -> None:
    result = run(
        credit_count=14,
        max_single_credit=2_400.0,
        aggregate_credits=33_600.0,
        account_age_days=21,
        observed_monthly_turnover=33_600.0,
        source_of_funds_evidence="present")
    assert result.outcome == "refer_to_investigation"
    assert result.decision.stage.id == "DISP-REFER-01"


def test_confirmed_designation_escalates_regardless_of_everything_else() -> None:
    result = run(sanctions_signal="confirmed")
    assert result.outcome == "refer_to_investigation"
    assert result.decision.stage.id == "DISP-MAND-01"


def test_mandatory_escalation_outranks_abstention() -> None:
    # Out of scope *and* a confirmed match: escalation wins, because declining to act on a
    # designation match would itself be a failure to act.
    result = run(sanctions_signal="confirmed", has_crypto_transaction=True)
    assert result.facts.value_of("scope_state", ALERT) == "out_of_scope"
    assert result.outcome == "refer_to_investigation"


def test_unscreened_customer_produces_an_abstention_not_a_clearance() -> None:
    result = run(sanctions_signal="not_checked")
    assert result.outcome == "refuse_to_decide"
    assert result.decision.stage.reason == "missing_premise"
    assert any("sanctions_signal" in reason for reason in result.decision.reasons)


def test_out_of_scope_instrument_produces_a_named_abstention() -> None:
    result = run(has_crypto_transaction=True)
    assert result.outcome == "refuse_to_decide"
    assert result.decision.stage.reason == "out_of_scope"
    assert any("chain analytics" in reason for reason in result.decision.reasons)


def test_trust_structure_is_out_of_scope() -> None:
    result = run(customer_type="trust")
    assert result.outcome == "refuse_to_decide"
    assert any("beneficial-ownership" in reason for reason in result.decision.reasons)


def test_weak_support_is_monitored_rather_than_escalated_or_closed() -> None:
    result = run(
        credit_count=3,
        max_single_credit=2_500.0,
        aggregate_credits=6_000.0,
        distinct_channels=3,
        observed_monthly_turnover=5_000.0)
    assert result.facts.value_of("typology_support", ALERT) == "weak"
    assert result.outcome == "monitor"


# --------------------------------------------------------------------------------------
# The mechanisms that make abstention meaningful
# --------------------------------------------------------------------------------------


def test_exculpatory_evidence_actually_reduces_certainty() -> None:
    conduit = run(
        outflow_within_window_ratio=0.95,
        closing_to_inflow_ratio=0.02)
    retained = run(
        outflow_within_window_ratio=0.95,
        closing_to_inflow_ratio=0.60)
    conduit_cf = conduit.facts.certainty_of("typology", ALERT, "rapid_pass_through")
    retained_cf = retained.facts.certainty_of("typology", ALERT, "rapid_pass_through")
    assert conduit_cf > 0.7
    assert retained_cf < conduit_cf


def test_cash_typology_does_not_fire_for_a_retail_customer() -> None:
    # Found at M3: the cash-intensive rules originally had no customer-segment premise, so
    # a salaried individual banking cash looked like a business layering its takings.
    result = run(
        cash_ratio=0.90,
        observed_monthly_turnover=33_600.0,
        customer_type="retail")
    assert result.facts.certainty_of("typology", ALERT, "cash_intensive_layering") == 0.0


def test_cash_typology_does_fire_for_a_business() -> None:
    result = run(
        cash_ratio=0.90,
        expected_cash_ratio=0.15,
        observed_monthly_turnover=33_600.0,
        customer_type="business")
    assert result.facts.certainty_of("typology", ALERT, "cash_intensive_layering") > 0.0


def test_veto_blocks_closure_when_due_diligence_has_lapsed() -> None:
    result = run(kyc_status="expired")
    blocked = {str(f.value) for f in result.facts.facts_for("disposition_blocked", ALERT)}
    assert "clear" in blocked
    assert result.outcome != "clear"


def test_no_case_reaches_the_deficiency_fallthrough() -> None:
    # Reaching it is a coverage gap in the knowledge base, not a property of the case.
    for overrides in (
        {},
        {"customer_type": "business"},
        {"kyc_status": "partial"},
        {"worst_fatf_status": "grey_list"},
        {"pep_status": "foreign"},
        {"days_since_prior_activity": 400},
        {"payer_hub_degree": 20, "account_age_days": 10},
        {"worst_fatf_status": "unknown"},
        {"kyc_status": "expired"},
        {"declared_purpose": "absent"}):
        result = run(**overrides)
        assert result.decision.stage.id != FALLTHROUGH.id, f"uncovered case: {overrides}"


def test_conflict_detection_reads_activations_not_surviving_certainty() -> None:
    # A cf near zero from strong opposing evidence and a cf near zero from no evidence at
    # all are very different states; only the first should be able to cause an abstention.
    result = run()
    conflicts = find_evidential_conflicts(result.trace, ALERT)
    assert conflicts == []


def test_every_assessment_records_how_it_got_there() -> None:
    result = run(credit_count=14, max_single_credit=2_400.0, aggregate_credits=33_600.0)
    assert result.trace.fired
    assert result.decision.stage.rationale
    disposition = result.facts.get("disposition", ALERT, result.outcome)
    assert disposition is not None


@pytest.mark.parametrize("sanctions", ["none", "possible", "confirmed"])
def test_screening_outcomes_all_produce_a_decision(sanctions: str) -> None:
    result = run(sanctions_signal=sanctions)
    assert result.outcome in DISPOSITIONS
    if sanctions in {"possible", "confirmed"}:
        assert result.outcome == "refer_to_investigation"
