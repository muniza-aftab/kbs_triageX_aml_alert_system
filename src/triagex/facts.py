"""Facts and the working memory that holds them.

Two properties of this module carry most of the system's safety:

1. **Three-valued semantics.** A fact can be believed, disbelieved, or simply unknown.
   Most rule engines conflate the last two, which in this domain is the difference between
   "no sanctions match was found" and "nobody ran the check".

2. **Negation as failure is restricted.** Rules may reason from the absence of ordinary
   facts, but predicates registered as ``mandatory`` refuse to be queried that way. The
   engine raises rather than quietly letting a missing check read as clean.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from enum import Enum
from typing import TypeAlias

from triagex.engine import certainty
from triagex.kb.predicates import UNKNOWN_VALUES, FactValue, PredicateSpec, spec_for

Subject: TypeAlias = str


class Truth(Enum):
    """Three-valued truth."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    def __bool__(self) -> bool:  # pragma: no cover - guard against accidental use
        raise TypeError(
            "Truth values must be compared explicitly (`is Truth.TRUE`). Implicit "
            "boolean coercion would make UNKNOWN behave as FALSE, which is the exact "
            "conflation this type exists to prevent."
        )


# --------------------------------------------------------------------------------------
# Derivations
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Asserted:
    """A fact read directly from the case file."""

    field: str

    def describe(self) -> str:
        return f"asserted from {self.field}"


@dataclass(frozen=True, slots=True)
class Derived:
    """A fact concluded by a rule from named premises."""

    rule_id: str
    premises: tuple[Fact, ...]

    def describe(self) -> str:
        return f"derived by {self.rule_id}"


@dataclass(frozen=True, slots=True)
class Combined:
    """A fact whose certainty is the combination of two independent derivations."""

    parts: tuple[Derivation, ...]

    def describe(self) -> str:
        return f"combined from {len(self.parts)} independent derivations"


Derivation: TypeAlias = Asserted | Derived | Combined


# --------------------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fact:
    """A single belief: ``predicate(subject) = value`` held with certainty ``cf``."""

    predicate: str
    subject: Subject
    value: FactValue
    cf: float
    derivation: Derivation
    seq: int = -1
    """Assertion order, assigned by the fact base. Used for recency in conflict
    resolution, and to make every run reproducible."""

    @property
    def key(self) -> tuple[str, Subject]:
        return (self.predicate, self.subject)

    @property
    def spec(self) -> PredicateSpec:
        return spec_for(self.predicate)

    @property
    def layer(self) -> int:
        return self.spec.layer

    @property
    def states_unknown(self) -> bool:
        """Whether this fact records an absence of knowledge rather than a finding."""
        return isinstance(self.value, str) and self.value in UNKNOWN_VALUES

    def __str__(self) -> str:
        return f"{self.predicate}({self.subject}) = {self.value}  [cf {self.cf:+.2f}]"


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class FactValidationError(ValueError):
    """Raised when a fact violates its predicate's declaration."""


class MandatoryPremiseError(RuntimeError):
    """Raised when a mandatory predicate is queried under negation as failure.

    Reasoning from the *absence* of a mandatory premise is exactly the unsafe inference
    this system exists to avoid: it would let a case with no sanctions check reach the
    same conclusion as a case that was checked and came back clean.
    """


# --------------------------------------------------------------------------------------
# Working memory
# --------------------------------------------------------------------------------------


class FactBase:
    """Working memory: the set of facts currently believed about one case.

    Indexed by ``(predicate, subject)`` and then by value, because several values of the
    same predicate may hold at once when the predicate is declared multi-valued.
    """

    def __init__(self, policy: certainty.CertaintyPolicy | None = None) -> None:
        self._store: dict[tuple[str, Subject], dict[FactValue, Fact]] = {}
        self._seq = 0
        self.policy = policy or certainty.MYCIN_POLICY
        """How repeated beliefs about the same value combine. Swappable for the ablation."""

    # -- assertion ---------------------------------------------------------------------

    def assert_fact(self, fact: Fact) -> Fact | None:
        """Add a fact, combining certainty if the same value is already believed.

        Returns the stored fact, or ``None`` when the conclusion fell below the noise
        floor and was discarded.
        """
        spec = spec_for(fact.predicate)
        if not spec.permits(fact.value):
            raise FactValidationError(
                f"{fact.value!r} is not an allowed value for {fact.predicate!r} "
                f"(allowed: {sorted(spec.values) if spec.values else 'open'})"
            )
        certainty.check(fact.cf)

        if not certainty.above_noise_floor(fact.cf):
            return None

        bucket = self._store.setdefault(fact.key, {})
        existing = bucket.get(fact.value)

        if existing is None:
            self._seq += 1
            stored = replace(fact, seq=self._seq)
            bucket[fact.value] = stored
            return stored

        merged_cf = self.policy.combine(existing.cf, fact.cf)
        if not certainty.above_noise_floor(merged_cf):
            del bucket[fact.value]
            return None

        self._seq += 1
        stored = replace(
            existing,
            cf=merged_cf,
            derivation=Combined(parts=_flatten(existing.derivation, fact.derivation)),
            seq=self._seq)
        bucket[fact.value] = stored
        return stored

    def assert_raw(
        self,
        predicate: str,
        subject: Subject,
        value: FactValue,
        *,
        field: str,
        cf: float = 1.0) -> Fact | None:
        """Convenience for L0 assertions straight from a case file."""
        return self.assert_fact(
            Fact(
                predicate=predicate,
                subject=subject,
                value=value,
                cf=cf,
                derivation=Asserted(field=field))
        )

    # -- querying ----------------------------------------------------------------------

    def facts_for(self, predicate: str, subject: Subject) -> list[Fact]:
        return list(self._store.get((predicate, subject), {}).values())

    def get(self, predicate: str, subject: Subject, value: FactValue) -> Fact | None:
        return self._store.get((predicate, subject), {}).get(value)

    def value_of(self, predicate: str, subject: Subject) -> FactValue | None:
        """The believed value of a single-valued predicate, or ``None`` if unknown.

        Where several values are believed, the most certain wins; ties break on assertion
        order so the result is deterministic.
        """
        candidates = self.facts_for(predicate, subject)
        if not candidates:
            return None
        best = max(candidates, key=lambda f: (f.cf, -f.seq))
        return best.value

    def truth(self, predicate: str, subject: Subject, value: FactValue) -> Truth:
        fact = self.get(predicate, subject, value)
        if fact is None:
            spec = spec_for(predicate)
            if spec.multi_valued:
                # Other values of a multi-valued predicate say nothing about this one.
                return Truth.UNKNOWN
            known_values = self.facts_for(predicate, subject)
            if any(f.cf > 0 for f in known_values):
                return Truth.FALSE
            return Truth.UNKNOWN
        if fact.states_unknown:
            return Truth.UNKNOWN
        return Truth.TRUE if fact.cf > 0 else Truth.FALSE

    def is_known(self, predicate: str, subject: Subject) -> bool:
        """Whether any usable belief exists. Explicit 'unknown' values do not count."""
        facts = self.facts_for(predicate, subject)
        return any(not f.states_unknown for f in facts)

    def absent(self, predicate: str, subject: Subject) -> bool:
        """Negation as failure, refused for mandatory predicates.

        See :class:`MandatoryPremiseError` for why.
        """
        spec = spec_for(predicate)
        if spec.mandatory:
            raise MandatoryPremiseError(
                f"{predicate!r} is a mandatory premise and cannot be reasoned about by "
                f"absence. Test its value explicitly, or let the meta-layer abstain."
            )
        return not self.facts_for(predicate, subject)

    def get_numeric(self, predicate: str, subject: Subject) -> Fact | None:
        """The single numeric fact for a measurement predicate, if one is believed.

        Layer 0 measurements are single-valued numbers, so the most certain match is the
        only sensible answer. Booleans are excluded: ``True`` is not a measurement.
        """
        numeric = [
            f
            for f in self.facts_for(predicate, subject)
            if isinstance(f.value, int | float) and not isinstance(f.value, bool)
        ]
        if not numeric:
            return None
        return max(numeric, key=lambda f: (f.cf, -f.seq))

    def certainty_of(self, predicate: str, subject: Subject, value: FactValue) -> float:
        fact = self.get(predicate, subject, value)
        return fact.cf if fact is not None else 0.0

    # -- inspection --------------------------------------------------------------------

    def __iter__(self) -> Iterator[Fact]:
        for bucket in self._store.values():
            yield from bucket.values()

    def __len__(self) -> int:
        return sum(len(bucket) for bucket in self._store.values())

    def by_layer(self, layer: int) -> list[Fact]:
        return sorted(
            (f for f in self if f.layer == layer),
            key=lambda f: (f.predicate, str(f.value)))

    def subjects(self) -> set[Subject]:
        return {subject for _, subject in self._store}

    def incompatibilities(self) -> list[tuple[Fact, Fact]]:
        """Pairs of facts asserting different values of the same single-valued predicate.

        This is raw material for the conflict detector, not a verdict: whether an
        incompatibility is a soft conflict or an irreconcilable one depends on how close
        the two certainties are.
        """
        clashes: list[tuple[Fact, Fact]] = []
        for (predicate, _), bucket in self._store.items():
            if spec_for(predicate).multi_valued or len(bucket) < 2:
                continue
            believed = sorted(
                (f for f in bucket.values() if f.cf > 0),
                key=lambda f: (-f.cf, f.seq))
            for i, first in enumerate(believed):
                clashes.extend((first, second) for second in believed[i + 1 :])
        return clashes

    def snapshot(self) -> tuple[Fact, ...]:
        """An immutable view, used by the trace to record engine state per cycle."""
        return tuple(sorted(self, key=lambda f: f.seq))


def _flatten(*derivations: Derivation) -> tuple[Derivation, ...]:
    """Flatten nested combinations so a repeatedly reinforced fact keeps a flat history."""
    parts: list[Derivation] = []
    for derivation in derivations:
        if isinstance(derivation, Combined):
            parts.extend(derivation.parts)
        else:
            parts.append(derivation)
    return tuple(parts)
