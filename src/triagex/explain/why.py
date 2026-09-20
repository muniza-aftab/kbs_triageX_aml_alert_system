"""The explanation facility: why, why not, how.

An expert system that cannot explain itself is a black box with extra steps. The three
questions here are the classic ones, and each needs different machinery:

* **why**: why this outcome? Walk the proof tree behind the decision and render each rule's
  rationale. The rationale field exists precisely for this: it is written for an analyst, not
  a developer.
* **why not**: why not some *other* outcome? This cannot be answered from the proof tree,
  because the answer is about what is *absent*. It comes from evaluating the conditions of
  every stage that could have produced that outcome and reporting which ones failed, and what
  the fact base says instead.
* **how**: how was this intermediate conclusion reached? A proof tree for any fact, not just
  the final disposition, so an analyst who disbelieves one step can drill into it.

The "why not" answer is the one that matters most in practice and the one most systems skip.
"This was not cleared" is useless; "this was not cleared because evidence_sufficiency is
partial, not sufficient, and because a prohibition blocks closure while typology support is
strong" tells someone exactly what to do next.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from triagex.engine.backward import BackwardChainer, Goal, UnmetCondition, diagnose
from triagex.engine.trace import Activation, contributing_rules, proof_tree
from triagex.facts import Fact
from triagex.kb.disposition import DECISION_LIST, Stage
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.predicates import DISPOSITIONS
from triagex.kb.reference import CF
from triagex.pipeline import Assessment

POSTURE_ORDER = (
    "typology_support",
    "composite_risk",
    "evidence_sufficiency",
    "conflict_state",
    "scope_state",
    "mandatory_escalation")


# --------------------------------------------------------------------------------------
# Why
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reason:
    """One step of an explanation, in the analyst's language rather than the engine's."""

    rule_id: str
    statement: str
    rationale: str
    certainty: float | None = None

    def describe(self) -> str:
        suffix = f" (confidence {self.certainty:+.2f})" if self.certainty is not None else ""
        return f"{self.statement}{suffix}\n    {self.rationale}  [{self.rule_id}]"


@dataclass(frozen=True, slots=True)
class Explanation:
    alert: str
    outcome: str
    headline: str
    reasons: tuple[Reason, ...] = ()
    abstention_reasons: tuple[str, ...] = ()
    posture: tuple[tuple[str, str], ...] = ()
    typologies: tuple[tuple[str, float], ...] = ()
    dissent: tuple[str, ...] = ()
    """How close the call was. See :func:`near_misses`."""

    def to_text(self) -> str:
        lines = [f"{self.alert}: {self.outcome.upper()}", "", self.headline, ""]

        if self.abstention_reasons:
            lines.append("Could not decide because:")
            lines.extend(f"  - {reason}" for reason in self.abstention_reasons)
            lines.append("")

        if self.typologies:
            lines.append("Patterns matched:")
            lines.extend(f"  - {name} (confidence {cf:+.2f})" for name, cf in self.typologies)
            lines.append("")

        if self.posture:
            lines.append("Assessment:")
            lines.extend(f"  {name:<22} {value}" for name, value in self.posture)
            lines.append("")

        if self.reasons:
            lines.append("Reasoning:")
            lines.extend(f"  - {reason.describe()}" for reason in self.reasons)
            lines.append("")

        if self.dissent:
            lines.append("How close the call was:")
            lines.extend(f"  - {item}" for item in self.dissent)
        return "\n".join(lines).rstrip() + "\n"


def explain(assessment: Assessment) -> Explanation:
    """Build the full explanation for a decision."""
    alert = assessment.alert
    facts = assessment.facts
    stage = assessment.decision.stage

    posture = tuple(
        (name, str(value))
        for name in POSTURE_ORDER
        if (value := facts.value_of(name, alert)) is not None
    )
    typologies = tuple(
        (str(f.value), f.cf)
        for f in sorted(facts.facts_for("typology", alert), key=lambda f: -f.cf)
        if f.cf > 0
    )

    return Explanation(
        alert=alert,
        outcome=assessment.outcome,
        headline=stage.rationale,
        reasons=_reasons_for_decision(assessment),
        abstention_reasons=assessment.decision.reasons,
        posture=posture,
        typologies=typologies,
        dissent=tuple(near_misses(assessment)))


def _reasons_for_decision(assessment: Assessment) -> tuple[Reason, ...]:
    """The rules that actually contributed, deepest evidence first.

    Ordered by layer rather than by firing order: an analyst wants to read "these deposits
    cluster under the threshold, therefore this looks like structuring, therefore the risk is
    high", not the order the agenda happened to pick.
    """
    relevant: set[str] = set()
    for premise in assessment.decision.premises:
        relevant |= contributing_rules(premise)

    by_id = {rule.id: rule for rule in KNOWLEDGE_BASE}
    activations = {
        a.rule.id: a for a in assessment.trace.fired if a.rule.id in relevant
    }

    reasons = []
    for rule_id in sorted(relevant, key=lambda rid: (by_id[rid].layer if rid in by_id else 0, rid)):
        rule = by_id.get(rule_id)
        if rule is None:
            continue
        activation = activations.get(rule_id)
        reasons.append(
            Reason(
                rule_id=rule_id,
                statement=_state(activation) if activation else rule.then.predicate,
                rationale=rule.rationale,
                certainty=activation.conclusion_cf if activation else None)
        )
    return tuple(reasons)


def _state(activation: Activation) -> str:
    predicate, _subject, value = activation.conclusion
    return f"{predicate.replace('_', ' ')} is {value}"


# --------------------------------------------------------------------------------------
# Why not
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WhyNot:
    """Why a particular outcome was not reached."""

    outcome: str
    reachable: bool
    blocked_by_precedence: str | None = None
    unmet: tuple[UnmetCondition, ...] = ()
    prohibitions: tuple[str, ...] = ()
    stages_considered: tuple[str, ...] = field(default_factory=tuple)

    def to_text(self) -> str:
        if self.reachable:
            return f"{self.outcome} was in fact reached."
        lines = [f"{self.outcome} was not reached because:"]
        if self.blocked_by_precedence:
            lines.append(
                f"  - a higher-precedence stage fired first: {self.blocked_by_precedence}"
            )
        for item in self.unmet:
            lines.append(f"  - {item.describe()}")
        for prohibition in self.prohibitions:
            lines.append(f"  - a prohibition forbids it: {prohibition}")
        if len(lines) == 1:
            lines.append("  - no stage of the decision list produces this outcome")
        return "\n".join(lines)


def why_not(assessment: Assessment, outcome: str) -> WhyNot:
    """Explain the absence of an outcome.

    Answered from the decision list rather than from the trace, because the question is about
    what did *not* happen and a trace only records what did.
    """
    if outcome not in DISPOSITIONS:
        raise ValueError(f"{outcome!r} is not a disposition")

    if assessment.outcome == outcome:
        return WhyNot(outcome=outcome, reachable=True)

    alert = assessment.alert
    candidates = [stage for stage in DECISION_LIST if stage.outcome == outcome]
    fired_index = _stage_index(assessment.decision.stage)

    unmet: list[UnmetCondition] = []
    precedence: str | None = None

    for stage in candidates:
        failures = diagnose(stage.when, assessment.facts, alert)
        if not failures:
            # The stage would have matched; something earlier in the list won.
            if _stage_index(stage) > fired_index:
                precedence = f"{assessment.decision.stage.id} ({assessment.outcome})"
            continue
        unmet.extend(failures)

    prohibitions = tuple(
        f"{fact.value} is blocked"
        for fact in assessment.facts.facts_for("disposition_blocked", alert)
        if str(fact.value) == outcome
    )

    return WhyNot(
        outcome=outcome,
        reachable=False,
        blocked_by_precedence=precedence,
        unmet=tuple(_dedupe(unmet)),
        prohibitions=prohibitions,
        stages_considered=tuple(stage.id for stage in candidates))


def _stage_index(stage: Stage) -> int:
    for index, candidate in enumerate(DECISION_LIST):
        if candidate.id == stage.id:
            return index
    return len(DECISION_LIST)  # the fallthrough sits after every real stage


def _dedupe(items: list[UnmetCondition]) -> list[UnmetCondition]:
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for item in items:
        key = (item.predicate, item.expected, item.actual)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def why_not_all(assessment: Assessment) -> dict[str, WhyNot]:
    """Every outcome the case did not receive, explained."""
    return {
        outcome: why_not(assessment, outcome)
        for outcome in DISPOSITIONS
        if outcome != assessment.outcome
    }


# --------------------------------------------------------------------------------------
# How
# --------------------------------------------------------------------------------------


def how(assessment: Assessment, predicate: str, value: str | None = None) -> str:
    """The derivation of an intermediate conclusion, as a proof tree."""
    facts = assessment.facts.facts_for(predicate, assessment.alert)
    if value is not None:
        facts = [f for f in facts if str(f.value) == value]
    if not facts:
        return f"{predicate} was never established for {assessment.alert}."
    best = max(facts, key=lambda f: f.cf)
    return proof_tree(best)


def prove_hypothetically(assessment: Assessment, predicate: str, value: str) -> str:
    """Ask the backward chainer whether a conclusion is reachable at all.

    Useful when the forward pass never derived something: the answer distinguishes "the
    evidence rules this out" from "no rule in the knowledge base could ever conclude it",
    which are very different problems.
    """
    chainer = BackwardChainer(KNOWLEDGE_BASE)
    if not chainer.is_derivable(predicate):
        return f"{predicate} is a base measurement, it is observed, never derived."
    proof, stats = chainer.prove_with_stats(
        Goal(predicate, assessment.alert, value), assessment.facts
    )
    if proof is None:
        return f"{predicate} = {value} cannot be established from this case ({stats.describe()})."
    return f"{predicate} = {value} is supported:\n{proof.render()}\n({stats.describe()})"


# --------------------------------------------------------------------------------------
# Near misses
# --------------------------------------------------------------------------------------


def near_misses(assessment: Assessment, limit: int = 4) -> list[str]:
    """How close the call was.

    The first version of this function reported activations that matched but lost conflict
    resolution. Measured against the case library it returned nothing for every single case -
    the rules are mutually exclusive by construction, so nothing ever truly loses, and the
    feature was dead code dressed up as insight.

    What is genuinely informative is *margin*: how far the deciding certainty sits from the
    band boundary that would have changed the answer. A case at 0.76 and a case at 0.98 both
    read as "strong support" and are not remotely the same case, and an analyst reviewing a
    borderline decision needs to know which one is in front of them.

    Losing and suppressed activations are still reported when they occur, since a future rule
    set may well produce them.
    """
    out: list[str] = []
    alert = assessment.alert
    facts = assessment.facts

    band_floor = {
        "strong": CF.support_strong,
        "moderate": CF.support_moderate,
        "weak": CF.support_weak,
    }
    next_band_down = {"strong": "moderate", "moderate": "weak", "weak": "none"}

    support = facts.value_of("typology_support", alert)
    believed = [f for f in facts.facts_for("typology", alert) if f.cf > 0]
    if isinstance(support, str) and support in band_floor and believed:
        strongest = max(believed, key=lambda f: f.cf)
        floor = band_floor[support]
        out.append(
            f"typology support is {support} at {strongest.cf:+.2f}; it would drop to "
            f"{next_band_down[support]} below {floor:.2f} (margin {strongest.cf - floor:+.2f})"
        )

    for fact in sorted(believed, key=lambda f: -f.cf):
        for band, floor in band_floor.items():
            if 0 < abs(fact.cf - floor) <= 0.10:
                side = "above" if fact.cf > floor else "below"
                out.append(
                    f"{fact.value} at {fact.cf:+.2f} sits just {side} the {band} "
                    f"threshold of {floor:.2f}"
                )

    for event in assessment.trace.considered_but_not_fired():
        activation = event.activation
        predicate, _subject, value = activation.conclusion
        out.append(
            f"{predicate.replace('_', ' ')} could have been {value} "
            f"via {activation.rule.id} - {event.note or 'not selected'}"
        )

    return out[:limit]


def summarise_facts(assessment: Assessment) -> list[Fact]:
    """The facts an analyst would want on one screen: indicators and above."""
    return sorted(
        (f for f in assessment.facts if f.layer >= 1 and f.cf > 0),
        key=lambda f: (f.layer, f.predicate, str(f.value)))
