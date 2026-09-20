"""A flat scorer, for comparison.

This project's documentation repeatedly asserts that a flat scoring model would do worse than a
layered rule base: that it would average incompatible readings into a confident middle, that it
could not abstain, that it would penalise a cash business for being one. Those are claims, and
claims should be measured.

So this is a deliberately *fair* flat baseline, not a straw man. It uses the same thresholds, the
same asymmetric cost matrix, and the same measurements. What it does not have is the layering:
no typologies, no meta reasoning, no veto, no reject option. Every indicator contributes a weight
to one number and the number picks an outcome.

If the layered system cannot beat this, the layering is decoration and the honest thing is to
say so.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from triagex.data.generator import GeneratedCase
from triagex.evaluate import CaseResult, Evaluation, cost_of
from triagex.kb.predicates import FactValue
from triagex.kb.reference import THRESHOLDS as T

# Weights chosen to mirror the rule base's own emphasis as closely as a flat model can:
# the same signals, the same rough ordering of importance.
WEIGHTS: dict[str, float] = {
    "high_frequency": 0.25,
    "threshold_hugging": 0.25,
    "aggregation_gap": 0.15,
    "rapid_passthrough": 0.30,
    "low_retention": 0.15,
    "many_payers": 0.25,
    "undeclared_payers": 0.20,
    "immature_account": 0.15,
    "dormancy_break": 0.15,
    "turnover_far_above": 0.25,
    "cash_above_expectation": 0.20,
    "high_risk_geography": 0.25,
    "designation": 0.90,
    "pep": 0.10,
    "adverse_media": 0.15,
    "documentation_gap": 0.20,
    "stale_kyc": 0.15,
}

REFER_AT = 0.75
ASK_AT = 0.45
MONITOR_AT = 0.25


def _num(measurements: dict[str, FactValue], key: str, default: float = 0.0) -> float:
    value = measurements.get(key, default)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else default


def signals(m: dict[str, FactValue]) -> dict[str, bool]:
    """The same observations the indicator layer makes, as flat booleans."""
    expected_turnover = max(_num(m, "expected_monthly_turnover", 1.0), 1.0)
    observed = _num(m, "observed_monthly_turnover")
    max_credit = _num(m, "max_single_credit")
    aggregate = _num(m, "aggregate_credits")
    expected_cash = max(_num(m, "expected_cash_ratio", 0.15), 0.01)

    return {
        "high_frequency": _num(m, "credit_count") >= T.frequency_elevated,
        "threshold_hugging": (
            T.internal_review_threshold * T.proximity_band_lower
            <= max_credit
            < T.internal_review_threshold
        ),
        "aggregation_gap": max_credit > 0
        and aggregate / max_credit >= T.aggregation_gap_multiple,
        "rapid_passthrough": _num(m, "outflow_within_window_ratio") >= 0.90,
        "low_retention": _num(m, "closing_to_inflow_ratio") < T.retention_ratio_low,
        "many_payers": _num(m, "payer_hub_degree") >= T.concentration_degree,
        "undeclared_payers": _num(m, "undeclared_payer_count") >= 2,
        "immature_account": _num(m, "account_age_days") < T.immaturity_days,
        "dormancy_break": _num(m, "days_since_prior_activity") >= T.dormancy_days,
        "turnover_far_above": observed / expected_turnover >= T.turnover_far_above_multiple,
        "cash_above_expectation": _num(m, "cash_ratio") / expected_cash
        >= 1.0 + T.cash_ratio_tolerance,
        "high_risk_geography": m.get("worst_fatf_status") in {"grey_list", "black_list"},
        "designation": m.get("sanctions_signal") in {"possible", "confirmed"},
        "pep": m.get("pep_status") in {"foreign", "domestic", "associate"},
        "adverse_media": m.get("adverse_media") in {"verified", "unverified"},
        "documentation_gap": m.get("source_of_funds_evidence") in {"absent", "unknown"},
        "stale_kyc": m.get("kyc_status") in {"partial", "expired", "unknown"},
    }


def score(m: dict[str, FactValue]) -> float:
    active = signals(m)
    total = sum(weight for name, weight in WEIGHTS.items() if active.get(name))
    return min(total, 1.0)


def classify(m: dict[str, FactValue]) -> str:
    """One number, four outcomes.

    Note what cannot appear in this function's range: ``refuse_to_decide``. A scorer has no
    way to express "this cannot be judged": every input maps to a band, and the bands cover the
    line.
    That is not an oversight in the baseline, it is the structural consequence of collapsing
    the assessment to a scalar, and it is the single clearest argument for the layered design.
    """
    value = score(m)
    if value >= REFER_AT:
        return "refer_to_investigation"
    if value >= ASK_AT:
        return "request_evidence"
    if value >= MONITOR_AT:
        return "monitor"
    return "clear"


def flat_evaluation(cases: Sequence[GeneratedCase]) -> Evaluation:
    evaluation = Evaluation(config_name="flat scorer")
    for case in cases:
        predicted = classify(case.measurements)
        evaluation.results.append(
            CaseResult(
                alert=case.alert_id,
                intent=case.intent,
                expected=case.expected_family,
                predicted=predicted,
                cost=cost_of(case.expected_family, predicted))
        )
    return evaluation


if __name__ == "__main__":
    from triagex.data.generator import generate

    result = flat_evaluation(generate(900, seed=20260920))
    print(f"flat scorer: cost/case {result.mean_cost:.3f}, coverage {result.coverage:.1%}")
