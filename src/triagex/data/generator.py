"""Seeded synthetic case generation.

The curated library in ``cases/`` is small and hand-argued: every file is a claim about how
the system should behave in one situation. This module supplies the *volume* the evaluation
needs, hundreds of cases sampled from parameterised profiles, reproducibly.

**The honest limitation.** Labels here are true *by construction*: a case generated from the
structuring profile is labelled as one because that is what it was built to be, not because
anyone confirmed a real customer was laundering. That makes the generated corpus useful for
measuring consistency, coverage and the shape of the abstention trade-off, and useless for
claiming real-world accuracy. Real calibration would need outcome data from filed reports,
which no public dataset provides. The evaluation says so rather than quietly implying
otherwise.

Profiles deliberately overlap at the edges. A generator that produces only unambiguous cases
would make any system look good, and would never exercise the grey band the abstention
mechanism exists for.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from triagex.kb.predicates import FactValue
from triagex.kb.reference import THRESHOLDS as T

Measurements = dict[str, FactValue]


@dataclass(frozen=True, slots=True)
class GeneratedCase:
    alert_id: str
    intent: str
    """The profile this case was sampled from."""

    expected_family: str | None
    """The disposition the profile is built to produce. True by construction only.

    ``None`` marks a case with no defensible answer, where abstaining is the only correct
    response and any decision is wrong. The evaluation needs these or the coverage curve is
    decided in advance."""

    measurements: Measurements = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------------------


def _baseline(rng: random.Random) -> Measurements:
    """An unremarkable retail account. Every profile perturbs this."""
    turnover = rng.uniform(1_200, 4_500)
    credit_count = rng.randint(1, 4)
    total = turnover * rng.uniform(0.7, 1.1)
    return {
        "credit_count": credit_count,
        "max_single_credit": total / max(credit_count, 1),
        "aggregate_credits": total,
        "distinct_payers": rng.randint(1, 2),
        "distinct_channels": rng.randint(1, 2),
        "payer_hub_degree": rng.randint(1, 2),
        "undeclared_payer_count": 0,
        "outflow_within_window_ratio": rng.uniform(0.1, 0.5),
        "closing_to_inflow_ratio": rng.uniform(0.25, 0.8),
        "cash_ratio": rng.uniform(0.0, 0.10),
        "expected_cash_ratio": 0.15,
        "observed_monthly_turnover": total,
        "expected_monthly_turnover": turnover,
        "account_age_days": rng.randint(200, 2_500),
        "days_since_prior_activity": rng.randint(1, 20),
        "worst_fatf_status": "compliant",
        "max_counterparty_secrecy": rng.randint(2, 4),
        "has_crypto_transaction": False,
        "has_gambling_counterparty": False,
        "closed_value_loop": False,
        "customer_type": "retail",
        "kyc_status": "complete",
        "sanctions_signal": "none",
        "pep_status": "none",
        "source_of_funds_evidence": "present",
        "adverse_media": "none",
        "declared_purpose": "consistent",
    }


# --------------------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------------------


def _ambiguous(rng: random.Random) -> tuple[Measurements, str | None]:
    """A case sitting exactly on the thresholds, where no answer is defensible.

    Added at M8 to close the gap recorded in the refinement log. Every other profile samples
    comfortably inside a band, which is why the generated corpus agreed with its own labels
    99.8% of the time - a figure that measured the generator and the rule base sharing
    assumptions, and nothing about the system's judgement.

    These cases sit *on* the boundaries: the credit count exactly at the elevated threshold, the
    largest credit exactly at the edge of the proximity band, turnover exactly at the deviation
    multiple. A reasonable analyst could go either way, so the label is ``None`` and only
    declining is correct.
    """
    m = _baseline(rng)
    count = T.frequency_elevated
    amount = T.internal_review_threshold * T.proximity_band_lower
    total = amount * count
    m.update(
        credit_count=count,
        max_single_credit=amount,
        aggregate_credits=total,
        observed_monthly_turnover=total,
        expected_monthly_turnover=total / T.turnover_above_multiple,
        cash_ratio=rng.uniform(0.4, 0.6),
        account_age_days=T.immaturity_days,
        days_since_prior_activity=T.dormancy_days,
        payer_hub_degree=T.concentration_degree,
        undeclared_payer_count=rng.choice([1, 2]),
        source_of_funds_evidence=rng.choice(["present", "absent"]))
    return m, None


def _clean(rng: random.Random) -> tuple[Measurements, str]:
    return _baseline(rng), "clear"


def _structuring(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    count = rng.randint(T.frequency_elevated, 20)
    amount = T.internal_review_threshold * rng.uniform(0.82, 0.995)
    total = amount * count
    m.update(
        credit_count=count,
        max_single_credit=amount,
        aggregate_credits=total,
        observed_monthly_turnover=total,
        cash_ratio=rng.uniform(0.7, 1.0),
        account_age_days=rng.randint(5,200),
        distinct_channels=rng.randint(1, 3),
        source_of_funds_evidence=rng.choice(["absent", "present"]))
    family = "refer_to_investigation" if m["source_of_funds_evidence"] == "present" else "request_evidence"
    return m, family


def _mule(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    payers = rng.randint(T.concentration_degree, 25)
    total = rng.uniform(4_000, 30_000)
    m.update(
        credit_count=payers,
        distinct_payers=payers,
        payer_hub_degree=payers,
        undeclared_payer_count=max(payers - rng.randint(0, 2), 2),
        max_single_credit=total / payers,
        aggregate_credits=total,
        observed_monthly_turnover=total,
        account_age_days=rng.randint(3, 80),
        outflow_within_window_ratio=rng.uniform(0.85, 1.0),
        closing_to_inflow_ratio=rng.uniform(0.0, 0.08),
        source_of_funds_evidence=rng.choice(["absent", "present"]))
    family = "refer_to_investigation" if m["source_of_funds_evidence"] == "present" else "request_evidence"
    return m, family


def _passthrough(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    total = rng.uniform(15_000, 120_000)
    m.update(
        credit_count=rng.randint(1, 4),
        max_single_credit=total / 2,
        aggregate_credits=total,
        observed_monthly_turnover=total,
        outflow_within_window_ratio=rng.uniform(0.92, 1.0),
        closing_to_inflow_ratio=rng.uniform(0.0, 0.05),
        customer_type="business",
        expected_monthly_turnover=rng.uniform(6_000, 20_000))
    return m, "refer_to_investigation"


def _dormant(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    total = rng.uniform(6_000, 40_000)
    m.update(
        days_since_prior_activity=rng.randint(T.dormancy_days, 900),
        aggregate_credits=total,
        max_single_credit=total / rng.randint(1, 3),
        observed_monthly_turnover=total,
        expected_monthly_turnover=rng.uniform(500, 2_000),
        account_age_days=rng.randint(1_000, 4_000),
        source_of_funds_evidence="absent")
    return m, "request_evidence"


def _cash_business(rng: random.Random) -> tuple[Measurements, str]:
    """A legitimate cash-intensive trader. Should not be penalised for being one."""
    m = _baseline(rng)
    turnover = rng.uniform(20_000, 60_000)
    m.update(
        customer_type="cash_intensive",
        expected_cash_ratio=0.60,
        cash_ratio=rng.uniform(0.40, 0.66),
        credit_count=rng.randint(4, 9),
        aggregate_credits=turnover,
        max_single_credit=turnover / rng.randint(5, 9),
        observed_monthly_turnover=turnover,
        expected_monthly_turnover=turnover * rng.uniform(0.9, 1.3))
    return m, "clear"


def _out_of_scope(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    if rng.random() < 0.5:
        m["has_crypto_transaction"] = True
    else:
        m["customer_type"] = "trust"
    return m, "refuse_to_decide"


def _unscreened(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    m[rng.choice(["sanctions_signal", "kyc_status"])] = rng.choice(["not_checked", "unknown"])
    # Only 'not_checked' is valid for sanctions and only 'unknown' for kyc; fix it up.
    if m["sanctions_signal"] == "unknown":
        m["sanctions_signal"] = "not_checked"
    if m["kyc_status"] == "not_checked":
        m["kyc_status"] = "unknown"
    return m, "refuse_to_decide"


def _designated(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    m["sanctions_signal"] = rng.choice(["possible", "confirmed"])
    return m, "refer_to_investigation"


def _incomplete_file(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    m["kyc_status"] = "partial"
    m["source_of_funds_evidence"] = rng.choice(["present", "absent"])
    return m, "request_evidence"


def _gambling(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    total = rng.uniform(8_000, 60_000)
    m.update(
        has_gambling_counterparty=True,
        aggregate_credits=total,
        max_single_credit=total / rng.randint(2, 6),
        observed_monthly_turnover=total,
        expected_monthly_turnover=rng.uniform(1_500, 4_000),
        outflow_within_window_ratio=rng.uniform(0.90, 1.0),
        closing_to_inflow_ratio=rng.uniform(0.0, 0.05))
    return m, "refer_to_investigation"


def _blacklisted(rng: random.Random) -> tuple[Measurements, str]:
    """Strong typology support plus a jurisdiction under countermeasures: severe posture."""
    m, _ = _structuring(rng)
    m.update(worst_fatf_status="black_list", max_counterparty_secrecy=9)
    family = (
        "refer_to_investigation"
        if m["source_of_funds_evidence"] == "present"
        else "request_evidence"
    )
    return m, family


def _expired_kyc(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    m["kyc_status"] = "expired"
    return m, "request_evidence"


def _adverse_media(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    total = rng.uniform(8_000, 30_000)
    m.update(
        # Sometimes uncorroborated: the system must record it without acting on it, and
        # that distinction needs a case or the rule for it is never exercised.
        adverse_media=rng.choice(["verified", "verified", "unverified"]),
        aggregate_credits=total,
        max_single_credit=total / rng.randint(2, 5),
        observed_monthly_turnover=total,
        expected_monthly_turnover=rng.uniform(2_000, 3_500))
    return m, "monitor"


def _pep(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    total = rng.uniform(40_000, 200_000)
    m.update(
        pep_status=rng.choice(["foreign", "associate", "domestic"]),
        aggregate_credits=total,
        max_single_credit=total / rng.randint(1, 3),
        observed_monthly_turnover=total,
        expected_monthly_turnover=rng.uniform(4_000, 9_000),
        worst_fatf_status=rng.choice(["compliant", "grey_list"]))
    return m, "refer_to_investigation"


def _cash_abuse(rng: random.Random) -> tuple[Measurements, str]:
    """A cash-intensive business well outside even its own generous expectation."""
    m = _baseline(rng)
    turnover = rng.uniform(80_000, 250_000)
    m.update(
        customer_type="cash_intensive",
        expected_cash_ratio=0.60,
        cash_ratio=rng.uniform(0.85, 1.0),
        credit_count=rng.randint(6, 14),
        aggregate_credits=turnover,
        max_single_credit=turnover / rng.randint(6, 14),
        observed_monthly_turnover=turnover,
        expected_monthly_turnover=rng.uniform(12_000, 20_000))
    return m, "refer_to_investigation"


def _boundary_suspicious(rng: random.Random) -> tuple[Measurements, str]:
    """Suspicious *and* partly unassessable: the case the boundary prohibition exists for."""
    m, _ = _structuring(rng)
    m.update(worst_fatf_status="unknown", source_of_funds_evidence="present")
    return m, "refer_to_investigation"


def _designated_geo(rng: random.Random) -> tuple[Measurements, str]:
    m = _baseline(rng)
    m.update(
        sanctions_signal="possible",
        worst_fatf_status=rng.choice(["grey_list", "black_list"]),
        max_counterparty_secrecy=8)
    return m, "refer_to_investigation"


def _dormant_hub(rng: random.Random) -> tuple[Measurements, str]:
    m, _ = _dormant(rng)
    payers = rng.randint(6, 14)
    m.update(payer_hub_degree=payers, distinct_payers=payers, undeclared_payer_count=payers - 1)
    return m, "request_evidence"


PROFILES: dict[str, Callable[[random.Random], tuple[Measurements, str | None]]] = {
    "clean": _clean,
    "structuring": _structuring,
    "mule": _mule,
    "passthrough": _passthrough,
    "dormant": _dormant,
    "cash_business": _cash_business,
    "out_of_scope": _out_of_scope,
    "unscreened": _unscreened,
    "designated": _designated,
    "incomplete_file": _incomplete_file,
    # Added at M7, after the rule-base audit found 20 rules that never fired across the whole
    # corpus. Each of these profiles exercises a family the corpus had no case for: gambling
    # flows, countermeasure jurisdictions, lapsed diligence, adverse media, political exposure,
    # cash-business abuse, partly-unassessable cases, designation plus geography, and dormancy
    # combined with a payer influx. Dead rules were a gap in the corpus, not in the knowledge.
    "gambling": _gambling,
    "blacklisted": _blacklisted,
    "expired_kyc": _expired_kyc,
    "adverse_media": _adverse_media,
    "pep": _pep,
    "cash_abuse": _cash_abuse,
    "boundary_suspicious": _boundary_suspicious,
    "designated_geo": _designated_geo,
    "dormant_hub": _dormant_hub,
    # No correct answer by construction. See _ambiguous.
    "ambiguous": _ambiguous,
}

DEFAULT_WEIGHTS: dict[str, float] = {
    # Weighted towards clean cases, because real alert queues are. A corpus of evenly
    # mixed profiles would flatter any system by removing the needle-in-a-haystack problem
    # that makes AML triage hard in the first place.
    "clean": 0.22,
    "cash_business": 0.08,
    "incomplete_file": 0.08,
    "structuring": 0.08,
    "mule": 0.06,
    "passthrough": 0.05,
    "dormant": 0.04,
    "out_of_scope": 0.06,
    "unscreened": 0.04,
    "designated": 0.02,
    # The rarer families. Individually uncommon, collectively the long tail that a corpus
    # built only from the obvious shapes leaves entirely untested.
    "gambling": 0.03,
    "blacklisted": 0.03,
    "expired_kyc": 0.04,
    "adverse_media": 0.03,
    "pep": 0.03,
    "cash_abuse": 0.03,
    "boundary_suspicious": 0.02,
    "designated_geo": 0.01,
    "dormant_hub": 0.01,
    "ambiguous": 0.04,
}


def generate(count: int, *, seed: int = 20260920, weights: dict[str, float] | None = None) -> list[GeneratedCase]:
    """Generate ``count`` cases reproducibly.

    The same seed always yields the same corpus, so an evaluation figure can be regenerated
    from the seed alone rather than from a committed data file.
    """
    rng = random.Random(seed)
    chosen = weights or DEFAULT_WEIGHTS
    names = list(chosen)
    cumulative = list(chosen.values())

    cases = []
    for index in range(count):
        profile = rng.choices(names, weights=cumulative, k=1)[0]
        measurements, family = PROFILES[profile](rng)
        cases.append(
            GeneratedCase(
                alert_id=f"GEN-{seed}-{index:05d}",
                intent=profile,
                expected_family=family,
                measurements=measurements)
        )
    return cases
