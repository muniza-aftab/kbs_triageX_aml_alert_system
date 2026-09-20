"""Forward chaining: the recognise, act cycle.

Data-driven inference. Each cycle finds every rule that could fire given what is currently
believed, picks one by the conflict-resolution strategy, asserts its conclusion, and repeats
until nothing new can be concluded.

Forward chaining is the right choice for the bulk of this system because the input is a
fixed case file and the useful work is deriving everything that follows from it, indicators
from measurements, typologies from indicators, posture from typologies. Backward chaining
(``backward.py``) handles the opposite need: answering a specific question about a case
without deriving the whole picture.

Termination is guaranteed by refraction on premise *content*: a rule fires at most once per
distinct combination of premises. The cycle limit is a diagnostic backstop, not the
mechanism, if it ever trips, the rule base has a problem the verifier should have caught.
"""

from __future__ import annotations

from collections.abc import Iterator

from triagex.dsl import Rule, RuleSet, match_all
from triagex.engine import certainty, conflict
from triagex.engine.trace import Activation, EventKind, Trace
from triagex.facts import Derived, Fact, FactBase

DEFAULT_MAX_CYCLES = 500


class CycleLimitExceededError(RuntimeError):
    """Raised when inference does not settle, if the engine is run in strict mode."""


class ForwardChainer:
    """An agenda-based forward chainer over a validated rule set."""

    def __init__(
        self,
        rules: RuleSet,
        *,
        max_cycles: int = DEFAULT_MAX_CYCLES,
        strict: bool = False,
        policy: certainty.CertaintyPolicy | None = None) -> None:
        self.rules = rules
        self.max_cycles = max_cycles
        self.strict = strict
        self.policy = policy or certainty.MYCIN_POLICY

    # -- public API --------------------------------------------------------------------

    def run(self, fb: FactBase, fired: set[object] | None = None) -> Trace:
        """Infer everything derivable from ``fb``, mutating it in place.

        ``fired`` carries refraction state across successive runs over the same case. The
        pipeline needs this: it chains, pauses for the meta-layer to assess what was
        concluded, then chains again. Without shared refraction the second run would re-fire
        every rule from the first, and because repeated conclusions *combine* certainty, a
        rule firing twice on the same evidence would inflate its own conclusion. Evidence
        counted twice is not stronger evidence.
        """
        trace = Trace()
        fired_fingerprints: set[object] = fired if fired is not None else set()

        for cycle in range(1, self.max_cycles + 1):
            trace.cycles_run = cycle
            candidates = [
                activation
                for activation in self._all_activations(fb)
                if activation.fingerprint not in fired_fingerprints
            ]

            if not candidates:
                trace.cycles_run = cycle - 1
                return trace

            winner, losers = conflict.resolve(candidates)

            for loser in losers:
                trace.record(
                    cycle,
                    EventKind.NOT_SELECTED,
                    loser,
                    note=conflict.explain_choice(winner, loser))

            fired_fingerprints.add(winner.fingerprint)
            self._fire(winner, fb, trace, cycle)

        trace.halted_early = True
        if self.strict:
            raise CycleLimitExceededError(
                f"inference did not settle within {self.max_cycles} cycles; "
                f"last fired: {trace.fired_rule_ids[-5:]}"
            )
        return trace

    def saturate(self, fb: FactBase) -> tuple[FactBase, Trace]:
        """Run to completion and return both the fact base and the trace."""
        return fb, self.run(fb)

    # -- matching ----------------------------------------------------------------------

    def _all_activations(self, fb: FactBase) -> Iterator[Activation]:
        for rule in self.rules:
            yield from self._activations_for(rule, fb)

    def _activations_for(self, rule: Rule, fb: FactBase) -> Iterator[Activation]:
        for bindings, matched in match_all(rule.when, fb):
            premises = _distinct(matched)
            premise_cf = self.policy.conjoin([f.cf for f in premises])
            conclusion_cf = certainty.attenuate(rule.strength, premise_cf)
            yield Activation(
                rule=rule,
                bindings=bindings,
                premises=premises,
                conclusion=rule.then.instantiate(bindings),
                premise_cf=premise_cf,
                conclusion_cf=conclusion_cf)

    # -- firing ------------------------------------------------------------------------

    def _fire(self, activation: Activation, fb: FactBase, trace: Trace, cycle: int) -> None:
        predicate, subject, value = activation.conclusion

        if not certainty.above_noise_floor(activation.conclusion_cf):
            trace.record(
                cycle,
                EventKind.SUPPRESSED,
                activation,
                note=f"cf {activation.conclusion_cf:+.2f} below noise floor")
            return

        stored = fb.assert_fact(
            Fact(
                predicate=predicate,
                subject=subject,
                value=value,
                cf=activation.conclusion_cf,
                derivation=Derived(rule_id=activation.rule.id, premises=activation.premises))
        )

        if stored is None:
            trace.record(
                cycle,
                EventKind.SUPPRESSED,
                activation,
                note="combined certainty fell below the noise floor")
            return

        trace.record(cycle, EventKind.FIRED, activation)


def _distinct(facts: tuple[Fact, ...]) -> tuple[Fact, ...]:
    """Drop duplicate premises, preserving order.

    Several conditions can legitimately match the same fact, a band test comparing one
    measurement against both an upper and a lower bound is the common case. Without this,
    the fact appears twice in every proof tree, which makes explanations read as though the
    system counted the same evidence twice.
    """
    seen: set[Fact] = set()
    unique: list[Fact] = []
    for fact in facts:
        if fact not in seen:
            seen.add(fact)
            unique.append(fact)
    return tuple(unique)
