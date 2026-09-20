"""The meta-layer: reasoning about what the knowledge base knows.

Everything here answers a question *about* the case assessment rather than about the case:
how strong is the strongest hypothesis, do the conclusions contradict each other, is a
required premise missing. These are what turn ``refuse_to_decide`` from a slogan into a
mechanism.

**Why these are functions rather than production rules.** Each one quantifies over the whole
fact base, "the strongest typology", "any two incompatible conclusions", "every mandatory
premise". Production rules match individual facts and cannot express aggregation or
universal quantification without either an explicit aggregate construct or a combinatorial
explosion of guard conditions. This is a well-known limitation of production systems rather
than a shortcut, and the alternative would be worse: encoding "no typology exceeds 0.75"
as rules means one rule per typology per band, all of which have to be kept in step by hand.

The *policy* remains data. Every threshold these functions use lives in ``kb/reference.py``,
so the abstention experiment can sweep them without touching this code.
"""

from __future__ import annotations

from dataclasses import dataclass

from triagex.engine import certainty
from triagex.engine.trace import Trace
from triagex.facts import Derived, Fact, FactBase
from triagex.kb.predicates import MANDATORY_PREDICATES
from triagex.kb.reference import CF

META_SUPPORT = "META-SUPPORT-01"
META_CONFLICT = "META-CONFLICT-01"
META_PREMISE = "META-PREMISE-01"


# --------------------------------------------------------------------------------------
# Typology support
# --------------------------------------------------------------------------------------


def assert_typology_support(fb: FactBase, alert: str) -> Fact | None:
    """Map the strongest believed typology onto a support band.

    Only positively believed typologies count. A typology driven negative by exculpatory
    evidence is not weak support for suspicion, it is evidence against it, and treating
    ``abs(cf)`` as support would invert the meaning of every exculpatory rule.
    """
    believed = [f for f in fb.facts_for("typology", alert) if f.cf > 0]

    premises: tuple[Fact, ...]
    if not believed:
        band, premises = "none", ()
    else:
        strongest = max(believed, key=lambda f: (f.cf, f.value))
        band, premises = certainty.support_band(strongest.cf), (strongest,)

    return fb.assert_fact(
        Fact(
            predicate="typology_support",
            subject=alert,
            value=band,
            cf=1.0,
            derivation=Derived(rule_id=META_SUPPORT, premises=premises))
    )


# --------------------------------------------------------------------------------------
# Conflict
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidentialConflict:
    """Support and opposition for the same hypothesis, both substantial."""

    typology: str
    supporting: float
    opposing: float

    @property
    def is_irreconcilable(self) -> bool:
        return certainty.irreconcilable(self.supporting, self.opposing)

    def describe(self) -> str:
        return (
            f"{self.typology}: supported at {self.supporting:+.2f} and opposed at "
            f"{self.opposing:+.2f}"
        )


def find_evidential_conflicts(trace: Trace, alert: str) -> list[EvidentialConflict]:
    """Find typologies argued both for and against with comparable weight.

    This is the conflict that matters. Structural incompatibility, two rules asserting
    different values of one single-valued predicate, is a bug in the knowledge base, and
    the verifier hunts those separately. What happens *here* is the knowledge base working
    correctly and still failing to reach a view: real evidence points both ways.

    A flat scorer would sum these into a confident number near the middle. The certainty
    algebra does cancel them to near zero, but a cf of 0.02 from strong opposing evidence
    and a cf of 0.02 from no evidence at all mean very different things, and only one of
    them should produce an answer. Reading the *activations* rather than the surviving fact
    is what preserves that distinction.
    """
    support: dict[str, float] = {}
    opposition: dict[str, float] = {}

    for activation in trace.fired:
        predicate, subject, value = activation.conclusion
        if predicate != "typology" or subject != alert or not isinstance(value, str):
            continue
        cf = activation.conclusion_cf
        target = support if cf > 0 else opposition
        current = target.get(value)
        if current is None or abs(cf) > abs(current):
            target[value] = cf

    conflicts = []
    floor = CF.support_moderate
    for typology, positive in support.items():
        negative = opposition.get(typology)
        if negative is None:
            continue
        if positive >= floor and abs(negative) >= floor:
            conflicts.append(EvidentialConflict(typology, positive, negative))
    return conflicts


def assert_conflict_state(fb: FactBase, alert: str, trace: Trace) -> Fact | None:
    """Record whether the assessment contradicts itself, and how badly."""
    evidential = find_evidential_conflicts(trace, alert)
    structural = [
        pair for pair in fb.incompatibilities() if pair[0].layer >= 3 and pair[0].subject == alert
    ]

    premises: tuple[Fact, ...] = tuple(f for pair in structural for f in pair)

    if any(c.is_irreconcilable for c in evidential) or any(
        certainty.irreconcilable(a.cf, b.cf) for a, b in structural
    ):
        state = "irreconcilable"
    elif evidential or structural:
        state = "soft"
    else:
        state = "none"

    return fb.assert_fact(
        Fact(
            predicate="conflict_state",
            subject=alert,
            value=state,
            cf=1.0,
            derivation=Derived(rule_id=META_CONFLICT, premises=premises))
    )


# --------------------------------------------------------------------------------------
# Missing premises
# --------------------------------------------------------------------------------------


def assert_missing_premises(fb: FactBase, alert: str) -> list[Fact]:
    """Record every mandatory premise the case fails to establish.

    ``is_known`` deliberately does not count a value of ``unknown`` or ``not_checked``. A
    case file stating ``sanctions_signal = not_checked`` has stated something true and
    important, that nobody screened, and the correct response is to refuse, not to
    proceed as though the answer were ``none``.
    """
    recorded = []
    for predicate in sorted(MANDATORY_PREDICATES):
        if fb.is_known(predicate, alert):
            continue
        fact = fb.assert_fact(
            Fact(
                predicate="missing_premise",
                subject=alert,
                value=predicate,
                cf=1.0,
                derivation=Derived(rule_id=META_PREMISE, premises=()))
        )
        if fact is not None:
            recorded.append(fact)
    return recorded


# --------------------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------------------


def run_meta_pass(fb: FactBase, alert: str, trace: Trace) -> None:
    """Run every meta-level assessment, in dependency order."""
    assert_typology_support(fb, alert)
    assert_missing_premises(fb, alert)
    assert_conflict_state(fb, alert, trace)


def support_margin(fb: FactBase, alert: str) -> float | None:
    """How far the strongest typology sits above the band floor that decided its support.

    ``None`` when no typology is believed, so there is no margin to speak of. A small margin
    means the support band - and therefore usually the disposition - would flip on a small
    change of evidence, which is what the selective-prediction layer acts on.
    """
    believed = [f for f in fb.facts_for("typology", alert) if f.cf > 0]
    if not believed:
        return None
    strongest = max(believed, key=lambda f: f.cf)
    band = certainty.support_band(strongest.cf)
    floors = {
        "strong": CF.support_strong,
        "moderate": CF.support_moderate,
        "weak": CF.support_weak,
        "none": 0.0,
    }
    return strongest.cf - floors[band]
