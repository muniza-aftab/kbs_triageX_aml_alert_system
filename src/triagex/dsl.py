"""The rule definition language.

Rules are declarative data, not Python control flow. The engine knows nothing about money
laundering, and the knowledge base contains no ``if`` statements, which is what makes the
knowledge auditable, and what lets the verifier reason about the rule set as a whole.

A rule reads close to how the corresponding sentence of guidance reads::

    Rule(
        id="TYP-STRUCT-01",
        layer=2,
        when=[
            Has("deposit_frequency", Var("a"), In("elevated", "extreme")),
            Has("threshold_proximity", Var("a"), "high"),
        ],
        then=Conclude("typology", Var("a"), "structuring"),
        strength=0.70,
        source="FATF structuring typology; JMLSG Part I risk factors",
        provenance=Provenance.RECONSTRUCTED,
        rationale="Deposits clustered below a review threshold, repeated within a short "
                  "window, are consistent with deliberate splitting of a larger sum.")
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeAlias, runtime_checkable

from triagex.facts import Fact, FactBase
from triagex.kb.predicates import FactValue, spec_for

Bindings: TypeAlias = Mapping[str, FactValue]
MatchResult: TypeAlias = tuple[Bindings, tuple[Fact, ...]]


# --------------------------------------------------------------------------------------
# Terms
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Var:
    """A variable. Binds on first use, must agree on every later use."""

    name: str


@dataclass(frozen=True, slots=True)
class In:
    """Matches any one of several values."""

    options: tuple[FactValue, ...]

    def __init__(self, *options: FactValue) -> None:
        object.__setattr__(self, "options", options)


@dataclass(frozen=True, slots=True)
class Wildcard:
    """Matches anything without binding it."""


ANY = Wildcard()

Term: TypeAlias = FactValue | Var | In | Wildcard


def unify(term: Term, value: FactValue, bindings: Bindings) -> Bindings | None:
    """Match one term against a concrete value, returning extended bindings or None.

    Public because the backward chainer unifies goals against rule conclusions and is a
    legitimate consumer of the same operation; a private name reached across modules
    would be worse than naming the contract.
    """
    if isinstance(term, Wildcard):
        return bindings
    if isinstance(term, Var):
        bound = bindings.get(term.name)
        if bound is None:
            return {**bindings, term.name: value}
        return bindings if bound == value else None
    if isinstance(term, In):
        return bindings if value in term.options else None
    return bindings if term == value else None


def resolve(term: Term, bindings: Bindings) -> FactValue:
    """Resolve a term to a concrete value, for use in a conclusion."""
    if isinstance(term, Var):
        try:
            return bindings[term.name]
        except KeyError as exc:
            raise UnboundVariableError(
                f"${term.name} is used in a conclusion but never bound by a premise"
            ) from exc
    if isinstance(term, Wildcard | In):
        raise UnboundVariableError(f"{term!r} cannot appear in a conclusion")
    return term


class UnboundVariableError(ValueError):
    """Raised when a conclusion references a variable no premise binds."""


# --------------------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------------------


@runtime_checkable
class Condition(Protocol):
    """A premise. Yields one result per way it can be satisfied."""

    def matches(self, fb: FactBase, bindings: Bindings) -> Iterator[MatchResult]: ...

    def predicates(self) -> frozenset[str]:
        """Predicates this condition reads, for layer validation and dependency analysis."""
        ...


@dataclass(frozen=True, slots=True)
class Has:
    """The fact base believes ``predicate(subject) = value`` with at least ``min_cf``."""

    predicate: str
    subject: Term
    value: Term = ANY
    min_cf: float = 0.0
    max_cf: float = 1.0
    """Certainty window. An upper bound is what makes graded conclusions mutually
    exclusive: without it, a 0.9-certainty typology would satisfy the rules for strong,
    moderate *and* weak support at once, and three incompatible values of a single-valued
    predicate would be asserted together."""

    def matches(self, fb: FactBase, bindings: Bindings) -> Iterator[MatchResult]:
        for fact in fb:
            if fact.predicate != self.predicate:
                continue
            if not self.min_cf <= fact.cf <= self.max_cf:
                continue
            after_subject = unify(self.subject, fact.subject, bindings)
            if after_subject is None:
                continue
            after_value = unify(self.value, fact.value, after_subject)
            if after_value is None:
                continue
            yield after_value, (fact,)

    def predicates(self) -> frozenset[str]:
        return frozenset({self.predicate})


@dataclass(frozen=True, slots=True)
class Missing:
    """Negation as failure: nothing at all is believed about ``predicate(subject)``.

    Refused for mandatory predicates, :class:`triagex.facts.MandatoryPremiseError`
    explains why. Use this for genuine conveniences ("no declared relationship exists"),
    never for anything whose absence could be a failure to check.
    """

    predicate: str
    subject: Term

    def matches(self, fb: FactBase, bindings: Bindings) -> Iterator[MatchResult]:
        subject = self.subject
        if isinstance(subject, Var):
            bound = bindings.get(subject.name)
            if bound is None:
                raise UnboundVariableError(
                    f"Missing() needs ${subject.name} already bound by an earlier premise; "
                    f"negation as failure over an unbound subject is not well defined."
                )
            subject_value = str(bound)
        elif isinstance(subject, Wildcard | In):
            raise UnboundVariableError("Missing() requires a concrete subject")
        else:
            subject_value = str(subject)

        if fb.absent(self.predicate, subject_value):
            yield bindings, ()

    def predicates(self) -> frozenset[str]:
        return frozenset({self.predicate})


_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass(frozen=True, slots=True)
class Cmp:
    """Numeric comparison against a threshold.

    Keeps indicator rules readable::

        Cmp("credit_count", Var("a"), ">=", THRESHOLDS.frequency_extreme)
    """

    predicate: str
    subject: Term
    op: str
    threshold: float

    def matches(self, fb: FactBase, bindings: Bindings) -> Iterator[MatchResult]:
        compare = _OPERATORS.get(self.op)
        if compare is None:
            raise ValueError(f"unknown comparison operator {self.op!r}")
        for fact in fb:
            if fact.predicate != self.predicate:
                continue
            if not isinstance(fact.value, int | float) or isinstance(fact.value, bool):
                continue
            after_subject = unify(self.subject, fact.subject, bindings)
            if after_subject is None:
                continue
            if compare(float(fact.value), self.threshold):
                yield after_subject, (fact,)

    def predicates(self) -> frozenset[str]:
        return frozenset({self.predicate})


@dataclass(frozen=True, slots=True)
class Ratio:
    """Compare two numeric facts about the same subject, as a multiple.

    ``Ratio("observed_monthly_turnover", "expected_monthly_turnover", Var("a"), ">=", 5.0)``
    reads as "observed turnover is at least five times expected".
    """

    numerator: str
    denominator: str
    subject: Term
    op: str
    multiple: float

    def matches(self, fb: FactBase, bindings: Bindings) -> Iterator[MatchResult]:
        compare = _OPERATORS[self.op]
        for num in fb:
            if num.predicate != self.numerator or not isinstance(num.value, int | float):
                continue
            after_subject = unify(self.subject, num.subject, bindings)
            if after_subject is None:
                continue
            den = fb.get_numeric(self.denominator, num.subject)
            if den is None or den.value in (0, 0.0):
                continue
            if compare(float(num.value) / float(den.value), self.multiple):
                yield after_subject, (num, den)

    def predicates(self) -> frozenset[str]:
        return frozenset({self.numerator, self.denominator})


@dataclass(frozen=True, slots=True)
class Test:
    """An arbitrary check over already-bound variables.

    An escape hatch, used sparingly. Anything expressible as :class:`Has`, :class:`Cmp`
    or :class:`Ratio` belongs there instead, because those are inspectable by the verifier
    and a Python lambda is not.
    """

    fn: Callable[[Bindings], bool]
    description: str = ""

    def matches(self, fb: FactBase, bindings: Bindings) -> Iterator[MatchResult]:
        if self.fn(bindings):
            yield bindings, ()

    def predicates(self) -> frozenset[str]:
        return frozenset()


def match_all(
    conditions: Sequence[Condition],
    fb: FactBase,
    bindings: Bindings | None = None) -> Iterator[MatchResult]:
    """Join a sequence of conditions against the fact base.

    Shared by the forward chainer and the disposition decision list, so both evaluate
    premises by exactly the same rules. Conditions are evaluated left to right, which makes
    a rule's premise order an ordering hint: bind subjects early, then narrow.
    """
    yield from _join(tuple(conditions), 0, fb, bindings if bindings is not None else {}, ())


def _join(
    conditions: tuple[Condition, ...],
    index: int,
    fb: FactBase,
    bindings: Bindings,
    premises: tuple[Fact, ...]) -> Iterator[MatchResult]:
    if index == len(conditions):
        yield bindings, premises
        return
    for extended, matched in conditions[index].matches(fb, bindings):
        yield from _join(conditions, index + 1, fb, extended, premises + matched)


# --------------------------------------------------------------------------------------
# Conclusions
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Conclude:
    """What a rule asserts when it fires."""

    predicate: str
    subject: Term
    value: Term

    def instantiate(self, bindings: Bindings) -> tuple[str, str, FactValue]:
        return (
            self.predicate,
            str(resolve(self.subject, bindings)),
            resolve(self.value, bindings))


# --------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------


PERMITTED_PREMISE_LAYERS: dict[int, frozenset[int]] = {
    1: frozenset({0}),
    2: frozenset({1}),
    3: frozenset({1, 2}),
    4: frozenset({1, 2, 3}),
    5: frozenset({3, 4}),
}
"""Which layers a rule at each layer may read from.

Strictly-lower alone is not a strong enough discipline. It would permit a layer 4 rule to
read a raw measurement and emit a disposition, which is precisely the flat lookup table the
layering exists to prevent. So the policy is explicit per layer:

* **L1 indicators read only measurements.** An indicator names an observation about raw data.
* **L2 typologies read only indicators.** A hypothesis is built from named observations, never
  from a bare number, that is what the indicator layer is for.
* **L3 assessment reads indicators and typologies.** Evidence sufficiency legitimately depends
  on an indicator (a documentation gap) without any typology being involved, so this layer is
  allowed to skip.
* **L4 posture reads everything below it.** ``composite_risk`` is downstream of
  ``typology_support``, which is why the two cannot share a layer.
* **L5 disposition reads assessment and posture only.** Nothing decides an outcome from raw
  data, from a bare indicator, or from another disposition.
"""


class Provenance(StrEnum):
    """Where a rule's knowledge came from. Required, and enforced by the test suite."""

    STATUTORY = "statutory"
    GUIDANCE = "guidance"
    RECONSTRUCTED = "reconstructed"


class RuleValidationError(ValueError):
    """Raised when a rule violates the knowledge model."""


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    layer: int
    when: tuple[Condition, ...]
    then: Conclude
    source: str
    provenance: Provenance
    rationale: str
    strength: float = 1.0
    priority: int = 0
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Forgiving constructor, strict storage: rules may be written with a list of
        # premises, but a Rule is frozen and hashable once built.
        object.__setattr__(self, "when", tuple(self.when))

    @property
    def specificity(self) -> int:
        """Number of premises. More specific rules win conflict resolution."""
        return len(self.when)

    def premise_predicates(self) -> frozenset[str]:
        return frozenset().union(*(c.predicates() for c in self.when)) if self.when else frozenset()

    def validate(self) -> None:
        """Check the rule against the knowledge model. Raises on any violation."""
        if not self.source.strip():
            raise RuleValidationError(f"{self.id}: source is required")
        if not self.rationale.strip():
            raise RuleValidationError(
                f"{self.id}: rationale is required, it is the sentence shown to an analyst"
            )
        if not -1.0 <= self.strength <= 1.0 or self.strength == 0.0:
            raise RuleValidationError(
                f"{self.id}: strength {self.strength} must be in [-1, 1] and non-zero"
            )

        conclusion_spec = spec_for(self.then.predicate)
        if conclusion_spec.layer != self.layer:
            raise RuleValidationError(
                f"{self.id}: declared layer {self.layer} but concludes "
                f"{self.then.predicate!r} which is layer {conclusion_spec.layer}"
            )
        if isinstance(self.then.value, str | int | float | bool) and not conclusion_spec.permits(
            self.then.value
        ):
            raise RuleValidationError(
                f"{self.id}: {self.then.value!r} is not a permitted value for "
                f"{self.then.predicate!r}"
            )

        permitted = PERMITTED_PREMISE_LAYERS.get(self.layer)
        if permitted is None:
            raise RuleValidationError(
                f"{self.id}: layer {self.layer} has no premise policy; rules may only "
                f"conclude at layers {sorted(PERMITTED_PREMISE_LAYERS)}"
            )

        for predicate in self.premise_predicates():
            premise_layer = spec_for(predicate).layer
            if premise_layer not in permitted:
                raise RuleValidationError(
                    f"{self.id}: premise {predicate!r} is layer {premise_layer}, which is "
                    f"not below the conclusion's layer {self.layer} in a permitted way "
                    f"(layer {self.layer} may read {sorted(permitted)}). Rules must chain "
                    f"upwards through derived concepts, never sideways and never straight "
                    f"from raw input to a disposition."
                )


class RuleSet:
    """A validated collection of rules."""

    def __init__(self, rules: Sequence[Rule], *, name: str = "rules") -> None:
        self.name = name
        self._rules = tuple(rules)
        self._validate_all()

    def _validate_all(self) -> None:
        seen: dict[str, Rule] = {}
        for rule in self._rules:
            rule.validate()
            if rule.id in seen:
                raise RuleValidationError(f"duplicate rule id {rule.id!r}")
            seen[rule.id] = rule

    def __iter__(self) -> Iterator[Rule]:
        return iter(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    def by_layer(self, layer: int) -> tuple[Rule, ...]:
        return tuple(r for r in self._rules if r.layer == layer)

    def get(self, rule_id: str) -> Rule:
        for rule in self._rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(rule_id)

    def __add__(self, other: RuleSet) -> RuleSet:
        return RuleSet((*self._rules, *other._rules), name=f"{self.name}+{other.name}")
