"""M7 acceptance tests: the rule-base verifier.

A verifier needs two kinds of test, and the second is the one usually skipped.

**That it finds real defects.** Each check is given a deliberately broken rule set and must
report the defect. A check that has never caught anything is not known to work.

**That it does not cry wolf.** The verifier's first run produced 23 false-positive conflict
warnings, because it could not reason about numeric intervals. A verifier nobody trusts is worse
than no verifier, so the exclusivity reasoning is tested directly.

Plus the standing guarantee: the real knowledge base must stay free of errors.
"""

from __future__ import annotations

import pytest

from triagex.data.generator import generate
from triagex.data.loader import factbase_for, load_library
from triagex.dsl import Cmp, Conclude, Has, In, Missing, Provenance, Rule, RuleSet, Var
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.predicates import PREDICATES
from triagex.kb.veto import PERMISSIVE_OUTCOMES
from triagex.pipeline import assess, assess_measurements
from triagex.verify.anomalies import (
    AuditReport,
    audit,
    audit_static,
    check_conflicts,
    check_dead_rules,
    check_redundancy,
    check_subsumption,
    check_unfirable,
    producible_values,
)

A = Var("a")


def _rule(rule_id: str, when: tuple[object, ...], then: Conclude, **kwargs: object) -> Rule:
    defaults: dict[str, object] = {
        "layer": 1,
        "source": "verifier test fixture",
        "provenance": Provenance.RECONSTRUCTED,
        "rationale": "Fixture rule used to exercise the verifier checks.",
    }
    return Rule(id=rule_id, when=when, then=then, **{**defaults, **kwargs})  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# The real knowledge base
# --------------------------------------------------------------------------------------

STATIC = audit_static()


def test_real_knowledge_base_has_no_errors() -> None:
    assert STATIC.clean, "\n".join(f.describe() for f in STATIC.errors)


def test_real_knowledge_base_has_no_unreachable_values() -> None:
    # A declared value nothing can produce tells a reader something can mean it.
    findings = STATIC.of_kind("unreachable_value")
    assert not findings, "\n".join(f.describe() for f in findings)


def test_real_knowledge_base_has_no_conflicts() -> None:
    findings = STATIC.of_kind("conflict")
    assert not findings, "\n".join(f.describe() for f in findings)


def test_real_knowledge_base_has_no_circularity() -> None:
    # Guaranteed by the layer policy. Verified anyway: an unverified guarantee is a hope.
    assert not STATIC.of_kind("circularity")


def test_deliberate_refinements_are_reported_as_notes_not_warnings() -> None:
    notes = {tuple(f.rule_ids) for f in STATIC.of_kind("refinement")}
    assert ("TYP-STRUCT-01", "TYP-STRUCT-02") in notes
    assert not STATIC.of_kind("subsumption"), "refinement must not be reported as redundancy"


@pytest.mark.slow
def test_no_rule_is_dead_across_the_corpus() -> None:
    """Corpus size is load-bearing here, and 400 cases is not enough.

    TYP-CASH-02 and TYP-PEP-02 need specific *combinations* - a cash business above but not far
    above profile, a foreign PEP with higher-risk geography - and at 400 cases the sampler often
    produces neither. They fire reliably at 800. A "no dead rules" claim measured on a corpus too
    small to contain the rare combinations is not a claim about the rule base.
    """
    fired: list[str] = []
    stages: list[str] = []
    cases = 0
    for case in load_library():
        result = assess(factbase_for(case), case.alert_id)
        fired.extend(result.trace.fired_rule_ids)
        stages.append(result.decision.stage.id)
        cases += 1
    for generated in generate(800, seed=41):
        result = assess_measurements(generated.alert_id, generated.measurements)
        fired.extend(result.trace.fired_rule_ids)
        stages.append(result.decision.stage.id)
        cases += 1

    report = audit(fired_ids=fired, stage_ids=stages, cases_checked=cases)
    dead = report.of_kind("dead_rule")
    assert not dead, dead[0].describe() if dead else ""
    assert not report.of_kind("coverage_gap")


def test_disposition_blocked_declares_only_what_the_veto_layer_can_block() -> None:
    declared = PREDICATES["disposition_blocked"].values or frozenset()
    assert declared == PERMISSIVE_OUTCOMES


# --------------------------------------------------------------------------------------
# Each check catches its defect
# --------------------------------------------------------------------------------------


def test_redundancy_is_caught() -> None:
    premises = (Cmp("credit_count", A, ">=", 5),)
    rules = RuleSet(
        [
            _rule("R-DUP-1", premises, Conclude("deposit_frequency", A, "elevated")),
            _rule("R-DUP-2", premises, Conclude("deposit_frequency", A, "elevated")),
        ]
    )
    report = AuditReport()
    check_redundancy(rules, report)
    assert report.of_kind("redundancy")
    assert report.errors


def test_equal_strength_subsumption_is_caught_as_a_warning() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-GEN",
                (Has("deposit_frequency", A, "extreme"),),
                Conclude("typology", A, "structuring"),
                layer=2,
                strength=0.7),
            _rule(
                "R-SPEC",
                (
                    Has("deposit_frequency", A, "extreme"),
                    Has("threshold_proximity", A, "high")),
                Conclude("typology", A, "structuring"),
                layer=2,
                strength=0.7),
        ]
    )
    report = AuditReport()
    check_subsumption(rules, report)
    # Same strength means the extra premise buys nothing, which is a real defect.
    assert report.of_kind("subsumption")
    assert not report.of_kind("refinement")


def test_differing_strength_subsumption_is_a_refinement_not_a_defect() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-GEN",
                (Has("deposit_frequency", A, "extreme"),),
                Conclude("typology", A, "structuring"),
                layer=2,
                strength=0.7),
            _rule(
                "R-SPEC",
                (
                    Has("deposit_frequency", A, "extreme"),
                    Has("threshold_proximity", A, "high")),
                Conclude("typology", A, "structuring"),
                layer=2,
                strength=0.4),
        ]
    )
    report = AuditReport()
    check_subsumption(rules, report)
    assert report.of_kind("refinement")
    assert not report.of_kind("subsumption")


def test_contradictory_premises_are_caught() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-IMPOSSIBLE",
                (
                    Has("deposit_frequency", A, "extreme"),
                    Has("deposit_frequency", A, "normal")),
                Conclude("typology", A, "structuring"),
                layer=2)
        ]
    )
    report = AuditReport()
    check_unfirable(rules, report)
    assert report.of_kind("unfirable")


def test_present_and_absent_at_once_is_caught() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-BOTH",
                (
                    Has("documentation_gap", A, "source_of_funds"),
                    Missing("documentation_gap", A)),
                Conclude("typology", A, "structuring"),
                layer=2)
        ]
    )
    report = AuditReport()
    check_unfirable(rules, report)
    assert report.of_kind("unfirable")


def test_genuine_conflict_is_caught() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-HIGH",
                (Has("typology_support", A, "strong"),),
                Conclude("composite_risk", A, "high"),
                layer=4),
            _rule(
                "R-LOW",
                (Has("evidence_sufficiency", A, "sufficient"),),
                Conclude("composite_risk", A, "low"),
                layer=4),
        ]
    )
    report = AuditReport()
    check_conflicts(rules, report)
    # Nothing prevents both premises holding, so these two will contradict each other.
    assert report.of_kind("conflict")


def test_dead_rules_are_caught() -> None:
    report = AuditReport()
    check_dead_rules(KNOWLEDGE_BASE, ["IND-FREQ-01"], report)
    findings = report.of_kind("dead_rule")
    assert findings
    assert len(findings[0].rule_ids) == len(KNOWLEDGE_BASE) - 1


# --------------------------------------------------------------------------------------
# The verifier does not cry wolf
# --------------------------------------------------------------------------------------


def test_numeric_bands_are_not_reported_as_conflicts() -> None:
    """The false positive that made the first audit unreadable.

    Twenty-three of twenty-four conflict warnings came from banded indicators like these,
    because the checker compared symbolic values only and could not see that the intervals are
    disjoint.
    """
    rules = RuleSet(
        [
            _rule(
                "R-BAND-HIGH",
                (Cmp("credit_count", A, ">=", 10),),
                Conclude("deposit_frequency", A, "extreme")),
            _rule(
                "R-BAND-MID",
                (Cmp("credit_count", A, ">=", 5), Cmp("credit_count", A, "<", 10),),
                Conclude("deposit_frequency", A, "elevated")),
            _rule(
                "R-BAND-LOW",
                (Cmp("credit_count", A, "<", 5),),
                Conclude("deposit_frequency", A, "normal")),
        ]
    )
    report = AuditReport()
    check_conflicts(rules, report)
    assert not report.of_kind("conflict"), [f.message for f in report.of_kind("conflict")]


def test_strict_and_non_strict_bounds_at_the_same_threshold_are_disjoint() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-GE",
                (Cmp("payer_hub_degree", A, ">=", 12),),
                Conclude("counterparty_concentration", A, "hub")),
            _rule(
                "R-LT",
                (Cmp("payer_hub_degree", A, "<", 12),),
                Conclude("counterparty_concentration", A, "diffuse")),
        ]
    )
    report = AuditReport()
    check_conflicts(rules, report)
    assert not report.of_kind("conflict")


def test_absence_and_presence_premises_are_recognised_as_exclusive() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-PRESENT",
                (Has("documentation_gap", A, "source_of_funds"),),
                Conclude("evidence_sufficiency", A, "partial"),
                layer=3),
            _rule(
                "R-ABSENT",
                (Missing("documentation_gap", A),),
                Conclude("evidence_sufficiency", A, "sufficient"),
                layer=3),
        ]
    )
    report = AuditReport()
    check_conflicts(rules, report)
    assert not report.of_kind("conflict")


def test_ratio_intervals_are_recognised_as_exclusive() -> None:
    from triagex.dsl import Ratio

    rules = RuleSet(
        [
            _rule(
                "R-FAR",
                (Ratio("observed_monthly_turnover", "expected_monthly_turnover", A, ">=", 5.0),),
                Conclude("turnover_deviation", A, "far_above")),
            _rule(
                "R-WITHIN",
                (Ratio("observed_monthly_turnover", "expected_monthly_turnover", A, "<", 2.0),),
                Conclude("turnover_deviation", A, "within")),
        ]
    )
    report = AuditReport()
    check_conflicts(rules, report)
    assert not report.of_kind("conflict")


def test_symbolic_partitions_are_recognised_as_exclusive() -> None:
    rules = RuleSet(
        [
            _rule(
                "R-SEVERE",
                (
                    Has("typology_support", A, "strong"),
                    Has("geographic_risk", A, "high")),
                Conclude("composite_risk", A, "severe"),
                layer=4),
            _rule(
                "R-HIGH",
                (
                    Has("typology_support", A, "strong"),
                    Has("geographic_risk", A, In("low", "elevated", "unknown"))),
                Conclude("composite_risk", A, "high"),
                layer=4),
        ]
    )
    report = AuditReport()
    check_conflicts(rules, report)
    assert not report.of_kind("conflict")


# --------------------------------------------------------------------------------------
# Producibility
# --------------------------------------------------------------------------------------


def test_meta_produced_predicates_are_known_to_the_verifier() -> None:
    # Without this the whole meta layer reads as unproducible: correct and useless.
    produced = producible_values(KNOWLEDGE_BASE)
    assert "strong" in produced["typology_support"]
    assert "irreconcilable" in produced["conflict_state"]


def test_variable_conclusions_are_traced_to_their_premise() -> None:
    # IND-SEG-01 copies customer_type into customer_segment, so every customer_type value is
    # producible for customer_segment even though no rule names them.
    produced = producible_values(KNOWLEDGE_BASE)
    assert {"retail", "business", "cash_intensive", "trust"} <= produced["customer_segment"]


def test_every_disposition_is_producible() -> None:
    produced = producible_values(KNOWLEDGE_BASE)
    assert len(produced["disposition"]) == 5


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def test_report_renders_and_separates_severities() -> None:
    rendered = STATIC.render()
    assert "rule-base audit" in rendered
    assert str(len(KNOWLEDGE_BASE)) in rendered


def test_empty_report_says_so() -> None:
    assert "nothing to report" in AuditReport().render()


def test_clean_means_no_errors_not_no_findings() -> None:
    report = AuditReport()
    report.add("dead_rule", "warning", "something")
    assert report.clean is True
    report.add("redundancy", "error", "something else")
    assert report.clean is False


@pytest.mark.parametrize("severity", ["error", "warning", "note"])
def test_findings_describe_themselves(severity: str) -> None:
    report = AuditReport()
    report.add("kind", severity, "a message", ["R-1"], "extra detail")
    described = report.findings[0].describe()
    assert severity.upper() in described
    assert "R-1" in described
    assert "extra detail" in described
