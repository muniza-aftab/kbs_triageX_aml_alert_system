"""Execution traces and proof trees.

The trace is not debug output. It is the substrate the explanation facility is built on:
"why did this case get referred?" is answered by walking a proof tree, and "why *not*
cleared?" is answered by inspecting the activations that were considered and rejected.

That is why the engine records the rejected candidates at every cycle, not just the rule
that fired. A system that only remembers what it did cannot explain what it nearly did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from triagex.facts import Asserted, Combined, Derivation, Derived, Fact
from triagex.kb.predicates import FactValue

if TYPE_CHECKING:
    from triagex.dsl import Bindings, Rule


@dataclass(frozen=True, slots=True)
class Activation:
    """A rule matched against specific facts, ready to fire."""

    rule: Rule
    bindings: Bindings
    premises: tuple[Fact, ...]
    conclusion: tuple[str, str, FactValue]
    premise_cf: float
    conclusion_cf: float

    @property
    def fingerprint(self) -> tuple[str, frozenset[tuple[str, str, FactValue]], tuple[str, str, FactValue]]:
        """Identity for refraction, a rule fires once per distinct premise combination.

        Deliberately keyed on the *content* of the premises rather than on their assertion
        sequence. Certainty factors get revised as evidence accumulates, which changes a
        fact's sequence number; keying on sequence would let the same rule re-fire on the
        same evidence forever.
        """
        return (
            self.rule.id,
            frozenset((f.predicate, f.subject, f.value) for f in self.premises),
            self.conclusion)

    def describe(self) -> str:
        predicate, subject, value = self.conclusion
        return f"{self.rule.id}: {predicate}({subject}) = {value} [cf {self.conclusion_cf:+.2f}]"


class EventKind(StrEnum):
    FIRED = "fired"
    SUPPRESSED = "suppressed"
    """Conclusion fell below the noise floor and was discarded."""
    NOT_SELECTED = "not_selected"
    """Matched, but lost conflict resolution this cycle."""
    REFRACTED = "refracted"
    """Already fired on these premises; skipped to guarantee termination."""


@dataclass(frozen=True, slots=True)
class TraceEvent:
    cycle: int
    kind: EventKind
    activation: Activation
    note: str = ""


@dataclass
class Trace:
    """The full record of one inference run."""

    events: list[TraceEvent] = field(default_factory=list)
    cycles_run: int = 0
    halted_early: bool = False

    def record(self, cycle: int, kind: EventKind, activation: Activation, note: str = "") -> None:
        self.events.append(TraceEvent(cycle=cycle, kind=kind, activation=activation, note=note))

    def extend(self, other: Trace) -> Trace:
        """Append another run's events, continuing the cycle numbering.

        One assessment is several chaining runs with meta-level passes between them, and an
        explanation needs to read as a single narrative rather than as three disconnected
        fragments.
        """
        offset = self.cycles_run
        self.events.extend(
            TraceEvent(
                cycle=event.cycle + offset,
                kind=event.kind,
                activation=event.activation,
                note=event.note)
            for event in other.events
        )
        self.cycles_run += other.cycles_run
        self.halted_early = self.halted_early or other.halted_early
        return self

    # -- queries -----------------------------------------------------------------------

    @property
    def fired(self) -> list[Activation]:
        return [e.activation for e in self.events if e.kind is EventKind.FIRED]

    @property
    def fired_rule_ids(self) -> list[str]:
        return [a.rule.id for a in self.fired]

    def considered_but_not_fired(self) -> list[TraceEvent]:
        """Activations that matched but never fired, the raw material for "why not?"."""
        fired = {a.fingerprint for a in self.fired}
        return [e for e in self.events if e.kind is not EventKind.FIRED and e.activation.fingerprint not in fired]

    def activations_concluding(self, predicate: str, subject: str | None = None) -> list[Activation]:
        return [
            a
            for a in self.fired
            if a.conclusion[0] == predicate and (subject is None or a.conclusion[1] == subject)
        ]

    # -- rendering ---------------------------------------------------------------------

    def render(self, *, include_rejected: bool = False) -> str:
        lines = [f"inference run: {self.cycles_run} cycles, {len(self.fired)} rules fired"]
        if self.halted_early:
            lines.append("  ** halted early: cycle limit reached **")
        for event in self.events:
            if event.kind is not EventKind.FIRED and not include_rejected:
                continue
            marker = {
                EventKind.FIRED: "fire",
                EventKind.SUPPRESSED: "drop",
                EventKind.NOT_SELECTED: "wait",
                EventKind.REFRACTED: "skip",
            }[event.kind]
            suffix = f"  ({event.note})" if event.note else ""
            lines.append(f"  [{event.cycle:>3}] {marker}  {event.activation.describe()}{suffix}")
        return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Proof trees
# --------------------------------------------------------------------------------------


def proof_tree(fact: Fact, *, indent: int = 0, seen: frozenset[tuple[str, str, FactValue]] | None = None) -> str:
    """Render the full derivation of a fact as indented text.

    Recursion is guarded against cycles, which should be impossible given layer
    enforcement, but a proof tree that hangs is worse than one that says so.
    """
    seen = seen or frozenset()
    identity = (fact.predicate, fact.subject, fact.value)
    pad = "  " * indent

    if identity in seen:
        return f"{pad}{fact}  <- cycle detected, truncated"

    seen = seen | {identity}
    lines = [f"{pad}{fact}"]
    lines.extend(_render_derivation(fact.derivation, indent + 1, seen))
    return "\n".join(lines)


def _render_derivation(
    derivation: Derivation,
    indent: int,
    seen: frozenset[tuple[str, str, FactValue]]) -> list[str]:
    pad = "  " * indent

    if isinstance(derivation, Asserted):
        return [f"{pad}<- {derivation.describe()}"]

    if isinstance(derivation, Derived):
        lines = [f"{pad}<- {derivation.describe()}"]
        lines.extend(proof_tree(p, indent=indent + 1, seen=seen) for p in derivation.premises)
        return lines

    lines = [f"{pad}<- {derivation.describe()}"]
    for part in derivation.parts:
        lines.extend(_render_derivation(part, indent + 1, seen))
    return lines


def contributing_rules(fact: Fact) -> set[str]:
    """Every rule id anywhere in a fact's derivation."""
    rules: set[str] = set()
    _collect_rules(fact.derivation, rules)
    return rules


def _collect_rules(derivation: Derivation, into: set[str]) -> None:
    if isinstance(derivation, Derived):
        into.add(derivation.rule_id)
        for premise in derivation.premises:
            _collect_rules(premise.derivation, into)
    elif isinstance(derivation, Combined):
        for part in derivation.parts:
            _collect_rules(part, into)
