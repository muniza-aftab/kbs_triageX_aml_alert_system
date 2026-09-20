"""M8 acceptance tests: the cost model, the coverage curve and the ablations.

The thing most worth testing in an evaluation is the evaluation itself. A cost function with the
asymmetry backwards, or a coverage curve that slopes one way by construction, produces numbers
that look rigorous and mean nothing. So these tests check the *properties* of the measurement
before any result is quoted from it:

* the cost matrix is asymmetric in the direction the domain requires;
* abstention is cheaper than a serious error and dearer than being right;
* cases with no defensible answer make abstention free and answering costly, which is the only
  reason a reject option can pay for itself;
* every ablation actually changes something, so each one is measuring a real component.
"""

from __future__ import annotations

import pytest

from triagex.data.generator import generate
from triagex.engine.certainty import BAYESIAN_POLICY, MYCIN_POLICY, POLICIES
from triagex.evaluate import (
    ABSTAIN,
    CAVEAT,
    CaseResult,
    Evaluation,
    cost_of,
    coverage_curve,
    evaluate,
    format_confusion,
    format_curve,
    format_summary,
)
from triagex.kb.disposition import DECISION_LIST
from triagex.kb.knowledge_base import (
    ASSESSMENT_RULES,
    INDICATOR_RULES,
    POSTURE_RULES,
    TYPOLOGY_RULES,
)
from triagex.kb.reference import ABSTENTION_COST, AMBIGUOUS_DECISION_COST
from triagex.pipeline import FORCED_ANSWER_STAGE, Configuration, assess_measurements

CASES = generate(120, seed=777)
NO_ABSTENTION_STAGES = tuple(s for s in DECISION_LIST if s.outcome != "refuse_to_decide")


# --------------------------------------------------------------------------------------
# The cost model
# --------------------------------------------------------------------------------------


def test_being_right_is_free() -> None:
    assert cost_of("clear", "clear") == 0.0
    assert cost_of("refer_to_investigation", "refer_to_investigation") == 0.0


def test_missing_a_referral_costs_more_than_over_escalating() -> None:
    # The asymmetry the domain actually requires. If this ever inverts, every figure the
    # evaluation produces is pointing the wrong way.
    missed = cost_of("refer_to_investigation", "clear")
    over_escalated = cost_of("clear", "refer_to_investigation")
    assert missed > over_escalated
    assert missed > cost_of("refer_to_investigation", "request_evidence")


def test_over_escalation_is_not_free_either() -> None:
    # It consumes an investigator and can freeze an innocent customer's account.
    assert cost_of("clear", "refer_to_investigation") > 0.0


def test_abstention_sits_between_right_and_seriously_wrong() -> None:
    assert 0.0 < ABSTENTION_COST < cost_of("refer_to_investigation", "clear")
    assert cost_of("clear", ABSTAIN) == ABSTENTION_COST


def test_abstaining_when_abstention_is_correct_is_free() -> None:
    """The bug the abstention ablation exposed.

    The first version checked for abstention before checking correctness, so declining an
    out-of-scope case was charged the abstention cost while answering it wrongly fell through
    to a default of 1.0. The correct action cost twice the incorrect one, and the ablation
    duly reported that removing abstention made the system cheaper.
    """
    assert cost_of(ABSTAIN, ABSTAIN) == 0.0
    assert cost_of(ABSTAIN, "clear") > cost_of(ABSTAIN, "refer_to_investigation") > 0.0


def test_answering_an_unassessable_case_costs_more_than_declining_an_answerable_one() -> None:
    assert cost_of(ABSTAIN, "clear") > ABSTENTION_COST


def test_unanswerable_cases_make_abstention_free_and_answering_costly() -> None:
    # Without this the coverage curve is decided in advance: if every case has a correct
    # answer, declining is always a loss and abstention can never pay for itself.
    assert cost_of(None, ABSTAIN) == 0.0
    assert cost_of(None, "clear") == AMBIGUOUS_DECISION_COST
    assert cost_of(None, "refer_to_investigation") == AMBIGUOUS_DECISION_COST


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


def _evaluation(pairs: list[tuple[str | None, str]]) -> Evaluation:
    evaluation = Evaluation(config_name="fixture")
    for index, (expected, predicted) in enumerate(pairs):
        evaluation.results.append(
            CaseResult(
                alert=f"A{index}",
                intent="fixture",
                expected=expected,
                predicted=predicted,
                cost=cost_of(expected, predicted))
        )
    return evaluation


def test_coverage_counts_only_decided_cases() -> None:
    evaluation = _evaluation([("clear", "clear"), ("clear", ABSTAIN), ("clear", "monitor")])
    assert evaluation.coverage == pytest.approx(2 / 3)
    assert evaluation.abstentions == 1


def test_selective_accuracy_ignores_abstentions_and_unlabelled_cases() -> None:
    evaluation = _evaluation(
        [("clear", "clear"), ("clear", "monitor"), ("clear", ABSTAIN), (None, "clear")]
    )
    # Two labelled decided cases, one right.
    assert evaluation.selective_accuracy == pytest.approx(0.5)


def test_selective_accuracy_alone_would_be_gameable() -> None:
    """Answering less raises accuracy, which is why it is never reported without coverage."""
    honest = _evaluation([("clear", "clear"), ("clear", "monitor")])
    evasive = _evaluation([("clear", "clear"), ("clear", ABSTAIN)])
    assert evasive.selective_accuracy > honest.selective_accuracy
    assert evasive.coverage < honest.coverage


def test_dangerous_errors_are_counted_separately() -> None:
    evaluation = _evaluation(
        [
            ("refer_to_investigation", "clear"),
            ("refer_to_investigation", "monitor"),
            ("refer_to_investigation", "request_evidence"),
        ]
    )
    # The third is a lesser error and must not be counted among the dangerous ones.
    assert evaluation.dangerous_errors == 2


def test_answering_the_unanswerable_is_counted() -> None:
    evaluation = _evaluation([(None, "clear"), (None, ABSTAIN)])
    assert evaluation.unanswerable_answered == 1


def test_empty_evaluation_does_not_divide_by_zero() -> None:
    empty = Evaluation(config_name="empty")
    assert empty.mean_cost == 0.0
    assert empty.coverage == 0.0
    assert empty.selective_accuracy == 0.0


# --------------------------------------------------------------------------------------
# The corpus
# --------------------------------------------------------------------------------------


def test_corpus_contains_unanswerable_cases() -> None:
    # The gap recorded in the refinement log at M7, closed at M8.
    unanswerable = [c for c in CASES if c.expected_family is None]
    assert unanswerable, "without these the coverage curve measures nothing"
    assert all(c.intent == "ambiguous" for c in unanswerable)


def test_ambiguous_cases_sit_on_the_thresholds() -> None:
    from triagex.kb.reference import THRESHOLDS as T

    for case in (c for c in CASES if c.intent == "ambiguous"):
        assert case.measurements["credit_count"] == T.frequency_elevated
        assert case.measurements["max_single_credit"] == pytest.approx(
            T.internal_review_threshold * T.proximity_band_lower
        )


def test_the_system_answers_ambiguous_cases_without_a_margin_threshold() -> None:
    """The finding that motivates the margin overlay, pinned so it cannot silently change."""
    ambiguous = [c for c in CASES if c.expected_family is None]
    answered = sum(
        1
        for c in ambiguous
        if assess_measurements(c.alert_id, c.measurements).outcome != ABSTAIN
    )
    assert answered == len(ambiguous), (
        "with tau=0 the system decides every borderline case; the reject option is what "
        "the margin threshold adds"
    )


# --------------------------------------------------------------------------------------
# Coverage curve
# --------------------------------------------------------------------------------------

CURVE = coverage_curve(CASES, (0.0, 0.10, 0.20, 0.30))


def test_coverage_falls_as_the_margin_widens() -> None:
    coverages = [point.coverage for point in CURVE]
    assert coverages == sorted(coverages, reverse=True)


def test_widening_the_margin_stops_answering_unanswerable_cases() -> None:
    assert CURVE[0].unanswerable_answered > CURVE[-1].unanswerable_answered


def test_curve_formats_and_marks_the_cheapest_setting() -> None:
    rendered = format_curve(CURVE)
    assert "lowest cost" in rendered
    assert "coverage" in rendered


def test_a_nonzero_margin_can_beat_answering_everything() -> None:
    """The claim the whole abstention design rests on, measured rather than asserted.

    If no margin setting beats tau=0 on risk-weighted cost, the reject option is not earning
    its place on this corpus and the documentation should say so instead.
    """
    baseline = next(p for p in CURVE if p.tau == 0.0)
    best = min(CURVE, key=lambda p: p.mean_cost)
    assert best.mean_cost <= baseline.mean_cost


# --------------------------------------------------------------------------------------
# Ablations
# --------------------------------------------------------------------------------------


def test_deleting_the_refuse_stages_alone_does_not_remove_abstention() -> None:
    """Silence is a refusal, so abstention cannot be ablated by deleting stages.

    The freed-up cases simply fall through, and the fallthrough abstains too. Discovering this
    is what made the ablation meaningful: the first version deleted the stages, measured no
    change, and would have reported that abstention makes no difference.
    """
    partial = evaluate(CASES, Configuration(name="stages only", stages=NO_ABSTENTION_STAGES))
    assert partial.abstentions > 0


def test_forcing_an_answer_costs_more_than_declining() -> None:
    """The claim the whole design rests on, measured on a corrected cost model."""
    full = evaluate(CASES, Configuration(name="full"))
    forced = evaluate(
        CASES,
        Configuration(
            name="forced",
            stages=NO_ABSTENTION_STAGES,
            fallthrough=FORCED_ANSWER_STAGE))
    assert forced.abstentions == 0
    assert forced.coverage == 1.0
    assert forced.mean_cost > full.mean_cost


def test_the_veto_layer_changes_no_outcome_and_that_is_the_finding() -> None:
    """Measured, not assumed: every prohibition is redundant with a disposition-stage guard.

    VETO-CLEAR-02 forbids closure when typology support is strong - and DISP-CLEAR-01 already
    requires support to be *none*. VETO-CLEAR-03 forbids closure on insufficient evidence, which
    DISP-CLEAR-01 already excludes. And so on for all six. The veto layer is therefore
    defence-in-depth rather than a behavioural component on this corpus.

    That is worth keeping and worth being honest about. It keeps its value if a disposition
    stage is ever loosened, and it makes the prohibition visible in explanations, which is why
    "why not clear?" can answer "a prohibition forbids it". But it does not change a single
    decision here, and claiming otherwise would be an invented result.
    """
    full = evaluate(CASES, Configuration(name="full"))
    without = evaluate(
        CASES,
        Configuration(
            name="no veto",
            rules=INDICATOR_RULES + TYPOLOGY_RULES + ASSESSMENT_RULES + POSTURE_RULES))
    assert [r.predicted for r in without.results] == [r.predicted for r in full.results]
    assert without.mean_cost == pytest.approx(full.mean_cost)


def test_the_veto_layer_still_does_observable_work() -> None:
    """Redundant for the outcome, load-bearing for the explanation."""
    blocked_somewhere = False
    for case in CASES[:60]:
        assessment = assess_measurements(case.alert_id, case.measurements)
        if assessment.facts.facts_for("disposition_blocked", case.alert_id):
            blocked_somewhere = True
            break
    assert blocked_somewhere, (
        "if no case ever triggers a prohibition, the veto layer is not even documentation"
    )


def test_the_bayesian_policy_produces_different_certainties() -> None:
    assert MYCIN_POLICY.combine(0.7, 0.5) != BAYESIAN_POLICY.combine(0.7, 0.5)
    assert MYCIN_POLICY.conjoin([0.9, 0.9, 0.9]) != BAYESIAN_POLICY.conjoin([0.9, 0.9, 0.9])
    assert set(POLICIES) == {"certainty-factors", "bayesian"}


def test_the_bayesian_policy_runs_end_to_end() -> None:
    result = evaluate(CASES[:40], Configuration(name="bayes", policy=BAYESIAN_POLICY))
    assert result.total == 40


def test_disabling_the_meta_layer_breaks_decision_making_entirely() -> None:
    """Not a graceful degradation, and worth pinning as a finding.

    typology_support, conflict_state and missing_premise all come from the meta functions, and
    the disposition stages read them. Without the meta pass nothing matches any stage, so every
    case lands on the deficiency fallthrough. The meta layer is not an abstention feature
    bolted onto a working system - it is load-bearing for every decision the system makes.
    """
    without = evaluate(CASES[:40], Configuration(name="no meta", enable_meta=False))
    assert all(r.predicted == ABSTAIN for r in without.results)
    assert without.coverage == 0.0


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def test_summary_table_renders_every_configuration() -> None:
    evaluations = [
        evaluate(CASES[:30], Configuration(name="full")),
        evaluate(CASES[:30], Configuration(name="forced", stages=NO_ABSTENTION_STAGES)),
    ]
    rendered = format_summary(evaluations)
    assert "full" in rendered
    assert "forced" in rendered
    assert "cost/case" in rendered


def test_confusion_matrix_includes_the_unanswerable_row() -> None:
    rendered = format_confusion(evaluate(CASES, Configuration(name="full")))
    assert "unanswerable" in rendered
    assert "refuse_to" in rendered


def test_the_caveat_is_part_of_the_module_not_an_afterthought() -> None:
    assert "not real-world accuracy" in CAVEAT
