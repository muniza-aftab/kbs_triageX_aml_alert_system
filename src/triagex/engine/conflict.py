"""Conflict resolution: choosing which of several eligible rules fires next.

Any forward chainer needs a policy for this, and the policy is a knowledge-engineering
decision rather than an implementation detail, it decides which of two competing readings
of a case wins. The strategy here is applied in strict order:

1. **Specificity.** The rule with more premises wins. A rule that accounts for more of the
   evidence should beat one that accounts for less, which is the classic justification and
   holds up well in a layered rule base: refinement rules carry the extra premises.
2. **Priority.** Explicit numeric priority, used where specificity is genuinely tied but
   the domain has an opinion, veto rules sit above ordinary disposition rules.
3. **Recency.** The activation resting on the most recently asserted fact. This keeps
   inference moving forwards through the layers instead of revisiting settled ground.
4. **Rule id.** A deterministic tiebreak, so two runs over identical input fire rules in
   identical order. Reproducibility matters more here than any cleverer heuristic: an
   auditable system whose trace differs between runs is not auditable.
"""

from __future__ import annotations

from collections.abc import Sequence

from triagex.engine.trace import Activation


def recency(activation: Activation) -> int:
    """Assertion sequence of the most recently asserted premise."""
    return max((f.seq for f in activation.premises), default=-1)


def sort_key(activation: Activation) -> tuple[int, int, int, str]:
    return (
        -activation.rule.specificity,
        -activation.rule.priority,
        -recency(activation),
        activation.rule.id)


def resolve(candidates: Sequence[Activation]) -> tuple[Activation, tuple[Activation, ...]]:
    """Pick the winning activation, returning it with the ones it beat.

    The losers are returned rather than discarded so the trace can record them: "this rule
    also matched but lost" is exactly what an analyst asking *why not* needs to see.
    """
    if not candidates:
        raise ValueError("resolve() called with no candidates")
    ordered = sorted(candidates, key=sort_key)
    return ordered[0], tuple(ordered[1:])


def explain_choice(winner: Activation, loser: Activation) -> str:
    """One line on why one activation beat another. Used in explanations and tests."""
    if winner.rule.specificity != loser.rule.specificity:
        return (
            f"{winner.rule.id} is more specific than {loser.rule.id} "
            f"({winner.rule.specificity} premises vs {loser.rule.specificity})"
        )
    if winner.rule.priority != loser.rule.priority:
        return (
            f"{winner.rule.id} has higher priority than {loser.rule.id} "
            f"({winner.rule.priority} vs {loser.rule.priority})"
        )
    if recency(winner) != recency(loser):
        return f"{winner.rule.id} rests on more recently established facts than {loser.rule.id}"
    return f"{winner.rule.id} precedes {loser.rule.id} in the deterministic tiebreak"
