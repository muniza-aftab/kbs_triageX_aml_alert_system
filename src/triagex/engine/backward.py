"""Backward chaining: goal-directed inference with unification.

Forward chaining derives everything that follows from a case. Backward chaining answers one
question, *can this conclusion be established, and how?*, without deriving the rest.

Both are needed, for different jobs:

* Forward chaining produces the assessment. The input is fixed and everything derivable from
  it is wanted.
* Backward chaining answers questions *about* an assessment, including hypothetical ones:
  "could this case have been cleared?", "what would have to hold for the evidence to count as
  sufficient?". Those questions are asked against a fact base that does *not* contain the
  conclusion, so there is nothing for a forward pass to find, and saturating the whole rule
  base to test one hypothesis would be wasteful besides.

This is also the substrate the contrastive search runs on: "what minimal change would flip
this decision" is a series of backward-chaining queries over modified fact bases.

**The meta layer is invisible to this chainer, and that is a real boundary.**
``typology_support``, ``conflict_state`` and ``missing_premise`` are computed by functions
rather than rules (``kb/meta.py`` explains why), so no rule concludes them and backward
chaining cannot derive them. Goals *above* the meta layer - ``composite_risk``,
``disposition_blocked`` - are therefore provable only when those meta facts are already
believed, which they are after a normal assessment but not from raw measurements alone. This
is why the contrastive search re-runs the whole pipeline over a modified case rather than
backward-chaining through it: the honest way to cross a procedural step is to execute it.

**Two further deliberate restrictions.** A goal's subject must be ground, every real question is
about a specific alert, and supporting unbound subjects would mean joining across cases for
no benefit. And only predicates appearing in some rule's conclusion are treated as derivable;
everything else is a base measurement that can be checked but never proved. Both restrictions
are enforced rather than assumed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from triagex.dsl import (
    ANY,
    Bindings,
    Condition,
    Has,
    In,
    Missing,
    Rule,
    RuleSet,
    Term,
    Var,
    Wildcard,
    unify,
)
from triagex.facts import Fact, FactBase
from triagex.kb.predicates import FactValue

DEFAULT_MAX_DEPTH = 12


class GoalError(ValueError):
    """Raised when a goal is not well formed."""


@dataclass(frozen=True, slots=True)
class Goal:
    """A question: does ``predicate(subject)`` hold, optionally at a particular value?"""

    predicate: str
    subject: str
    value: Term = ANY

    def __post_init__(self) -> None:
        if isinstance(self.subject, Var | Wildcard):
            raise GoalError(
                "a goal's subject must be ground, every question this system answers is "
                "about one specific alert"
            )

    def describe(self) -> str:
        if isinstance(self.value, Wildcard):
            return f"{self.predicate}({self.subject})"
        return f"{self.predicate}({self.subject}) = {self.value}"


@dataclass(frozen=True, slots=True)
class ProofStep:
    """One node of a proof: a goal, and how it was established."""

    goal: Goal
    bindings: Bindings
    fact: Fact | None = None
    """Set when the goal was satisfied directly by a believed fact."""

    rule: Rule | None = None
    """Set when the goal was established by firing a rule in reverse."""

    subproofs: tuple[ProofStep, ...] = ()
    checks: tuple[Fact, ...] = ()
    """Facts consumed by non-derivable premises (comparisons, ratios, absence tests)."""

    @property
    def is_leaf(self) -> bool:
        return self.fact is not None

    def rules_used(self) -> set[str]:
        used = {self.rule.id} if self.rule else set()
        for sub in self.subproofs:
            used |= sub.rules_used()
        return used

    def render(self, indent: int = 0) -> str:
        pad = "  " * indent
        if self.fact is not None:
            return f"{pad}{self.goal.describe()}  <- believed ({self.fact.cf:+.2f})"
        assert self.rule is not None
        lines = [f"{pad}{self.goal.describe()}  <- {self.rule.id}"]
        lines.extend(sub.render(indent + 1) for sub in self.subproofs)
        lines.extend(f"{pad}  checked: {c}" for c in self.checks)
        return "\n".join(lines)


@dataclass
class ProofSearchStats:
    """What the search did. Reported alongside results so cost is never invisible."""

    goals_attempted: int = 0
    rules_tried: int = 0
    facts_matched: int = 0
    depth_limit_hits: int = 0
    cycles_pruned: int = 0

    def describe(self) -> str:
        return (
            f"{self.goals_attempted} goals, {self.rules_tried} rules tried, "
            f"{self.facts_matched} facts matched"
        )


class BackwardChainer:
    """Proves goals against a fact base and rule set."""

    def __init__(self, rules: RuleSet, *, max_depth: int = DEFAULT_MAX_DEPTH) -> None:
        self.rules = rules
        self.max_depth = max_depth
        self._derivable: frozenset[str] = frozenset(r.then.predicate for r in rules)

    # -- public API --------------------------------------------------------------------

    def is_derivable(self, predicate: str) -> bool:
        """Whether any rule concludes this predicate. Everything else is a base fact."""
        return predicate in self._derivable

    def prove(self, goal: Goal, fb: FactBase) -> Iterator[ProofStep]:
        """Yield every proof of ``goal``, cheapest first (believed facts before rules)."""
        stats = ProofSearchStats()
        yield from self._prove(goal, fb, depth=0, seen=frozenset(), stats=stats)

    def first_proof(self, goal: Goal, fb: FactBase) -> ProofStep | None:
        """The first proof found, or ``None`` if the goal cannot be established."""
        return next(self.prove(goal, fb), None)

    def can_prove(self, goal: Goal, fb: FactBase) -> bool:
        return self.first_proof(goal, fb) is not None

    def prove_with_stats(self, goal: Goal, fb: FactBase) -> tuple[ProofStep | None, ProofSearchStats]:
        """A proof plus the cost of finding it."""
        stats = ProofSearchStats()
        proof = next(self._prove(goal, fb, depth=0, seen=frozenset(), stats=stats), None)
        return proof, stats

    # -- search ------------------------------------------------------------------------

    def _prove(
        self,
        goal: Goal,
        fb: FactBase,
        *,
        depth: int,
        seen: frozenset[tuple[str, str, object]],
        stats: ProofSearchStats,
        bindings: Bindings | None = None) -> Iterator[ProofStep]:
        stats.goals_attempted += 1
        bindings = bindings if bindings is not None else {}

        if depth > self.max_depth:
            stats.depth_limit_hits += 1
            return

        identity = (goal.predicate, goal.subject, _term_key(goal.value))
        if identity in seen:
            stats.cycles_pruned += 1
            return
        seen = seen | {identity}

        # 1. Already believed. Cheapest possible proof, so it comes first.
        for fact in fb.facts_for(goal.predicate, goal.subject):
            if fact.cf <= 0 or fact.states_unknown:
                continue
            extended = unify(goal.value, fact.value, bindings)
            if extended is None:
                continue
            stats.facts_matched += 1
            yield ProofStep(goal=goal, bindings=extended, fact=fact)

        # 2. Derive it. Only predicates some rule concludes are worth trying.
        if not self.is_derivable(goal.predicate):
            return

        for rule in self.rules:
            if rule.then.predicate != goal.predicate:
                continue
            stats.rules_tried += 1
            head = _unify_conclusion(rule, goal, bindings)
            if head is None:
                continue
            yield from self._prove_premises(
                rule, goal, tuple(rule.when), 0, fb, head, (), (), depth, seen, stats
            )

    def _prove_premises(
        self,
        rule: Rule,
        goal: Goal,
        premises: tuple[Condition, ...],
        index: int,
        fb: FactBase,
        bindings: Bindings,
        subproofs: tuple[ProofStep, ...],
        checks: tuple[Fact, ...],
        depth: int,
        seen: frozenset[tuple[str, str, object]],
        stats: ProofSearchStats) -> Iterator[ProofStep]:
        if index == len(premises):
            yield ProofStep(
                goal=goal,
                bindings=bindings,
                rule=rule,
                subproofs=subproofs,
                checks=checks)
            return

        condition = premises[index]

        # A Has premise on a derivable predicate becomes a subgoal; everything else is a
        # check against the fact base, because it bottoms out at an asserted measurement.
        if isinstance(condition, Has) and self.is_derivable(condition.predicate):
            subject = _ground(condition.subject, bindings)
            if subject is None:
                return
            subgoal = Goal(condition.predicate, subject, condition.value)
            for proof in self._prove(
                subgoal, fb, depth=depth + 1, seen=seen, stats=stats, bindings=bindings
            ):
                yield from self._prove_premises(
                    rule,
                    goal,
                    premises,
                    index + 1,
                    fb,
                    proof.bindings,
                    (*subproofs, proof),
                    checks,
                    depth,
                    seen,
                    stats)
            return

        for extended, matched in condition.matches(fb, bindings):
            yield from self._prove_premises(
                rule,
                goal,
                premises,
                index + 1,
                fb,
                extended,
                subproofs,
                (*checks, *matched),
                depth,
                seen,
                stats)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _unify_conclusion(rule: Rule, goal: Goal, bindings: Bindings) -> Bindings | None:
    """Unify a rule's conclusion with a goal, returning bindings for the rule's variables."""
    after_subject = unify(rule.then.subject, goal.subject, bindings)
    if after_subject is None:
        return None
    if isinstance(goal.value, Wildcard):
        return after_subject
    if isinstance(goal.value, Var):
        raise GoalError("a goal's value may be a literal, a set, or ANY, not a variable")
    if isinstance(goal.value, In):
        # The goal admits several values. If the rule concludes a literal it must be one of
        # them; if it concludes a variable, nothing can be decided here and the premises are
        # left to narrow it.
        conclusion = rule.then.value
        if isinstance(conclusion, Var | Wildcard):
            return after_subject
        return after_subject if conclusion in goal.value.options else None
    return unify(rule.then.value, goal.value, after_subject)


def _ground(term: Term, bindings: Bindings) -> str | None:
    """Resolve a term to a concrete subject, or ``None`` if it is not yet bound."""
    if isinstance(term, Var):
        bound = bindings.get(term.name)
        return str(bound) if bound is not None else None
    if isinstance(term, Wildcard):
        return None
    return str(term)


def _term_key(term: Term) -> object:
    """A hashable identity for a term, for cycle detection."""
    if isinstance(term, Wildcard):
        return "*"
    if isinstance(term, Var):
        return f"${term.name}"
    return term


@dataclass(frozen=True, slots=True)
class UnmetCondition:
    """A premise that did not hold, described in terms a human can act on."""

    condition: Condition
    predicate: str
    expected: str
    actual: str

    def describe(self) -> str:
        if self.expected == "nothing recorded":
            return f"{self.predicate} is recorded as {self.actual}, and must not be"
        if self.actual == "unknown":
            return f"{self.predicate} is not established (needs {self.expected})"
        return f"{self.predicate} is {self.actual}, not {self.expected}"


def diagnose(
    conditions: tuple[Condition, ...],
    fb: FactBase,
    subject: str,
    bindings: Bindings | None = None) -> list[UnmetCondition]:
    """Report which of a set of conditions fail, and what the fact base says instead.

    This is what makes a "why not?" answer actionable. Knowing that closure was unavailable
    is nearly useless; knowing that ``evidence_sufficiency`` is ``partial`` rather than
    ``sufficient`` tells an analyst exactly what to go and change.
    """
    base: dict[str, FactValue] = dict(bindings or {})
    base.setdefault("a", subject)

    unmet = []
    for condition in conditions:
        if next(condition.matches(fb, base), None) is not None:
            continue
        predicate = next(iter(condition.predicates()), "?")

        if isinstance(condition, Missing):
            # The premise required *nothing* to be believed, and something is. Reporting the
            # present values is the useful form; "not any value" is not.
            present = ", ".join(str(f.value) for f in fb.facts_for(predicate, subject))
            unmet.append(
                UnmetCondition(
                    condition=condition,
                    predicate=predicate,
                    expected="nothing recorded",
                    actual=present or "unknown")
            )
            continue

        actual = fb.value_of(predicate, subject)
        unmet.append(
            UnmetCondition(
                condition=condition,
                predicate=predicate,
                expected=_expected_of(condition),
                actual=str(actual) if actual is not None else "unknown")
        )
    return unmet


def _expected_of(condition: Condition) -> str:
    value = getattr(condition, "value", None)
    if value is None or isinstance(value, Wildcard):
        threshold = getattr(condition, "threshold", None)
        if threshold is not None:
            return f"{getattr(condition, 'op', '')} {threshold}"
        return "any value"
    options = getattr(value, "options", None)
    if options is not None:
        return " or ".join(str(option) for option in options)
    return str(value)


__all__ = [
    "BackwardChainer",
    "Goal",
    "GoalError",
    "ProofSearchStats",
    "ProofStep",
    "UnmetCondition",
    "diagnose",
]
