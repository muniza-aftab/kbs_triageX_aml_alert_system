"""Certainty factor arithmetic.

MYCIN-style certainty factors, implemented exactly as specified in
``docs/03-knowledge-model.md`` section 5.

**These are not probabilities.** The combination function is not derivable from
probability theory, it assumes an independence between premises that rarely holds, and
Heckerman's analysis showed the scheme is only coherent under restrictive conditions. It
is used here because a human reading ``strength=0.70`` off a rule can tell where that
number came from and argue with it, which in an auditable system matters more than formal
correctness.

That trade-off is a claim, so it is tested rather than asserted: a Bayesian aggregation
over the identical knowledge base runs as an ablation, and the comparison is reported in
``docs/07-evaluation.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from triagex.kb.reference import CF

CF_MIN = -1.0
CF_MAX = 1.0


class CertaintyRangeError(ValueError):
    """Raised when a certainty factor falls outside [-1, 1]."""


def check(cf: float) -> float:
    """Validate a certainty factor, returning it unchanged."""
    if not CF_MIN <= cf <= CF_MAX:
        raise CertaintyRangeError(f"certainty factor {cf} outside [{CF_MIN}, {CF_MAX}]")
    return cf


def conjunction(cfs: Sequence[float]) -> float:
    """Certainty of a conjunction of premises: the weakest link.

    An empty conjunction is vacuously certain, which matters for rules whose premises
    are all structural tests rather than facts.
    """
    if not cfs:
        return CF_MAX
    return min(check(cf) for cf in cfs)


def disjunction(cfs: Sequence[float]) -> float:
    """Certainty of a disjunction of premises: the strongest supporting one."""
    if not cfs:
        return 0.0
    return max(check(cf) for cf in cfs)


def attenuate(strength: float, premise_cf: float) -> float:
    """Certainty of a rule's conclusion.

    The rule's own strength caps how much belief it can contribute, and the premises
    scale it down further. A 0.7-strength rule firing on wholly certain premises yields
    0.7; the same rule on 0.5-certain premises yields 0.35.

    Strength may be negative, for rules that argue *against* a hypothesis. Exculpatory
    knowledge matters here: a system that can only accumulate suspicion will convict every
    customer eventually, and the mixed-sign branch of :func:`combine` is what lets an
    innocent explanation actually reduce a typology's certainty.
    """
    return check(strength) * check(premise_cf)


def combine(cf1: float, cf2: float) -> float:
    """Combine two independent certainty factors for the *same* conclusion.

    Two pieces of supporting evidence reinforce each other without ever reaching
    certainty; support and opposition partially cancel.
    """
    check(cf1)
    check(cf2)

    if cf1 >= 0 and cf2 >= 0:
        return cf1 + cf2 * (1.0 - cf1)
    if cf1 < 0 and cf2 < 0:
        return cf1 + cf2 * (1.0 + cf1)

    denominator = 1.0 - min(abs(cf1), abs(cf2))
    if denominator <= 0.0:
        # Directly contradictory evidence of equal weight cancels to no belief. The
        # conflict detector, not the arithmetic, is what notices this matters.
        return 0.0
    return (cf1 + cf2) / denominator


def combine_all(cfs: Iterable[float]) -> float:
    """Left-fold :func:`combine` over any number of certainty factors."""
    total = 0.0
    seen = False
    for cf in cfs:
        total = check(cf) if not seen else combine(total, cf)
        seen = True
    return total


def above_noise_floor(cf: float) -> bool:
    """Whether a conclusion is strong enough to be worth asserting at all.

    Without a floor, long inference chains accumulate a fog of 0.05-certainty facts that
    clutter every explanation and occasionally tip a threshold.
    """
    return abs(cf) >= CF.noise_floor


def support_band(cf: float) -> str:
    """Map the strongest typology certainty onto ``typology_support``.

    This is the only place a continuous certainty becomes a discrete symbol. Keeping the
    conversion in one function means the disposition rules stay symbolic and the bands can
    be swept in one place during the abstention-threshold experiment.
    """
    magnitude = abs(cf)
    if magnitude >= CF.support_strong:
        return "strong"
    if magnitude >= CF.support_moderate:
        return "moderate"
    if magnitude >= CF.support_weak:
        return "weak"
    return "none"


def irreconcilable(cf1: float, cf2: float) -> bool:
    """Whether two incompatible conclusions are too close to choose between.

    This is the arithmetic behind the most interesting abstention trigger: where a flat
    scorer would average two incompatible readings into a confident, meaningless middle,
    the system declines instead.
    """
    return abs(abs(cf1) - abs(cf2)) < CF.conflict_irreconcilable_delta

# --------------------------------------------------------------------------------------
# Swappable policy
# --------------------------------------------------------------------------------------


def combine_bayesian(cf1: float, cf2: float) -> float:
    """Combine two beliefs by multiplying odds instead of by the MYCIN formula.

    Treats a certainty factor as a rescaled probability, ``p = (cf + 1) / 2``, converts to
    odds, multiplies, and converts back. This is the probabilistically coherent way to pool
    independent evidence, and it is deliberately implemented here so the transparency claim
    made for certainty factors can be *measured* rather than asserted.

    Note what the comparison can and cannot show. Both schemes assume independence that the
    rule base does not have - several indicators derive from the same transactions - so
    neither is correct in the strict sense. What the ablation measures is whether the choice
    changes decisions, and by how much. If it barely does, the transparency is free.
    """
    check(cf1)
    check(cf2)
    p1 = (cf1 + 1.0) / 2.0
    p2 = (cf2 + 1.0) / 2.0
    p1 = min(max(p1, 1e-6), 1.0 - 1e-6)
    p2 = min(max(p2, 1e-6), 1.0 - 1e-6)
    odds = (p1 / (1.0 - p1)) * (p2 / (1.0 - p2))
    combined = odds / (1.0 + odds)
    return max(min(combined * 2.0 - 1.0, CF_MAX), CF_MIN)


def conjunction_product(cfs: Sequence[float]) -> float:
    """Conjunction as a product rather than a minimum.

    The probabilistic counterpart to taking the weakest link. It punishes long premise lists
    harder: three premises at 0.9 give 0.9 under ``min`` and 0.73 under a product, which is the
    behaviour a probabilist would want and which makes every multi-premise rule weaker.
    """
    if not cfs:
        return CF_MAX
    total = 1.0
    for cf in cfs:
        total *= check(cf)
    return total


@dataclass(frozen=True, slots=True)
class CertaintyPolicy:
    """How beliefs combine. Swappable so the arithmetic itself can be ablated."""

    name: str
    combine: Callable[[float, float], float]
    conjoin: Callable[[Sequence[float]], float]
    description: str = ""


MYCIN_POLICY = CertaintyPolicy(
    name="certainty-factors",
    combine=combine,
    conjoin=conjunction,
    description="MYCIN-style: weakest-link conjunction, MYCIN combination. The default.")

BAYESIAN_POLICY = CertaintyPolicy(
    name="bayesian",
    combine=combine_bayesian,
    conjoin=conjunction_product,
    description="Odds-multiplication combination with product conjunction.")

POLICIES = {policy.name: policy for policy in (MYCIN_POLICY, BAYESIAN_POLICY)}
