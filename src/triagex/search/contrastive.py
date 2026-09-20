"""Contrastive explanation search: what would have to change.

Given a decision, find the cheapest set of evidence to obtain that would change it. The
output is not a demonstration of search, it *is* the `request_evidence` message. When the
system says "ask the customer for source-of-funds documentation", this is what chose that
question, and chose it over the six more intrusive questions it could have asked instead.

**The state space.** A state is the set of interventions applied so far. An intervention is a
piece of evidence a bank could actually go and obtain, paired with the measurement it would
change. Step cost is the cost of obtaining that evidence, from ``EVIDENCE_COSTS`` - analyst
effort combined with how intrusive the request is for the customer. So the search does not
merely find *a* way to change the answer; it finds the least burdensome one.

**Why this re-runs the pipeline rather than backward-chaining.** The meta layer is computed by
functions, not rules, so backward chaining cannot cross it (see ``engine/backward.py``). The
honest way to cross a procedural step is to execute it, so each goal test re-assesses the
modified case end to end. That makes the goal test expensive, which in turn makes the
node-expansion comparison between algorithms actually matter rather than being academic.

**What this does and does not claim.** It finds what evidence would change *the system's*
answer. It says nothing about what is true. An intervention labelled
``source_of_funds_evidence -> present`` means "if documentation were produced", not "the
documentation would exonerate them". Confusing those two would turn an explanation facility
into a machine for justifying a predetermined conclusion, so the distinction is kept explicit
in the naming and in the rendered output.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

from triagex.kb.predicates import FactValue
from triagex.kb.reference import EVIDENCE_COSTS, MIN_EVIDENCE_COST
from triagex.pipeline import assess_measurements

Measurements = dict[str, FactValue]


@dataclass(frozen=True, slots=True)
class Intervention:
    """One piece of evidence a bank could obtain, and what it would establish."""

    name: str
    """Key into ``EVIDENCE_COSTS``."""

    changes: tuple[tuple[str, FactValue], ...]
    description: str

    @property
    def cost(self) -> float:
        return EVIDENCE_COSTS.get(self.name, MIN_EVIDENCE_COST)

    def apply(self, measurements: Measurements) -> Measurements:
        patched = dict(measurements)
        patched.update(self.changes)
        return patched

    def would_change_anything(self, measurements: Measurements) -> bool:
        """Whether this intervention is informative for this case.

        Asking for evidence the file already holds is not a step, it is noise. Excluding
        no-ops keeps the branching factor honest, which matters because the node counts in the
        algorithm comparison are only meaningful if the successors are real.
        """
        return any(measurements.get(key) != value for key, value in self.changes)


CATALOGUE: tuple[Intervention, ...] = (
    Intervention(
        "sanctions_screen",
        (("sanctions_signal", "none"),),
        "Run sanctions screening and record the result"),
    Intervention(
        "internal_transaction_history",
        (("days_since_prior_activity", 5),),
        "Pull longer account history to contextualise the dormancy break"),
    Intervention(
        "kyc_refresh",
        (("kyc_status", "complete"),),
        "Complete or refresh customer due diligence"),
    Intervention(
        "counterparty_relationship_declaration",
        (("undeclared_payer_count", 0),),
        "Obtain declarations for the unexplained payers"),
    Intervention(
        "source_of_funds_evidence",
        (("source_of_funds_evidence", "present"),),
        "Obtain source-of-funds documentation"),
    Intervention(
        "employer_confirmation",
        (("expected_monthly_turnover", 1_000_000.0),),
        "Confirm declared income so the expected profile reflects it"),
    Intervention(
        "adverse_media_review",
        (("adverse_media", "none"),),
        "Review and resolve the adverse media hit"),
    Intervention(
        "customer_interview",
        (("declared_purpose", "consistent"),),
        "Interview the customer about the purpose of the activity"))
"""The interventions available.

Note what is *absent*: nothing here resolves an out-of-scope case. No amount of evidence
gathering gives this knowledge base a model of cryptoasset flows or trust ownership chains, so
those abstentions are correctly unfixable and the search will report no solution for them.
That is the intended behaviour, not a gap - a search that always found an answer would be
lying about the system's limits.
"""


State = frozenset[str]
"""The set of intervention names applied so far."""


class ContrastiveProblem:
    """Find the cheapest evidence that flips a decision to ``target``."""

    def __init__(
        self,
        alert: str,
        measurements: Measurements,
        target: str,
        *,
        catalogue: Iterable[Intervention] = CATALOGUE,
        max_interventions: int = 4) -> None:
        self.alert = alert
        self.base = dict(measurements)
        self.target = target
        self.max_interventions = max_interventions
        self.catalogue = tuple(
            item for item in catalogue if item.would_change_anything(self.base)
        )
        self._by_name = {item.name: item for item in self.catalogue}
        self.goal_tests = 0

    # -- SearchProblem ------------------------------------------------------------------

    def initial(self) -> State:
        return frozenset()

    def is_goal(self, state: State) -> bool:
        if not state:
            return False  # the base case already has its outcome; zero changes changes nothing
        self.goal_tests += 1
        return self.outcome_for(state) == self.target

    def successors(self, state: State) -> Iterable[tuple[State, str, float]]:
        if len(state) >= self.max_interventions:
            return
        for item in self.catalogue:
            if item.name in state:
                continue
            yield state | {item.name}, item.name, item.cost

    def heuristic(self, state: State) -> float:
        """Admissible: any state that is not the goal needs at least one more intervention.

        Deliberately weak rather than clever. A tighter heuristic would need to predict which
        interventions matter, which means predicting the rule base - and a heuristic that
        silently overestimates would cost A* its optimality guarantee, which is the only reason
        to prefer it over uniform cost here.
        """
        if len(state) >= self.max_interventions:
            return 0.0
        return MIN_EVIDENCE_COST

    # -- evaluation ---------------------------------------------------------------------

    def measurements_for(self, state: State) -> Measurements:
        patched = dict(self.base)
        for name in sorted(state):
            patched = self._by_name[name].apply(patched)
        return patched

    def outcome_for(self, state: State) -> str:
        return _cached_outcome(self.alert, _freeze(self.measurements_for(state)))

    def intervention(self, name: str) -> Intervention:
        return self._by_name[name]

    def describe(self, state: State) -> list[str]:
        return [self._by_name[name].description for name in sorted(state)]


def _freeze(measurements: Measurements) -> tuple[tuple[str, FactValue], ...]:
    return tuple(sorted(measurements.items()))


@lru_cache(maxsize=4096)
def _cached_outcome(alert: str, frozen: tuple[tuple[str, FactValue], ...]) -> str:
    """Assess a measurement set, memoised.

    The search revisits the same measurement sets often, because different orders of the same
    interventions produce identical states. Caching on the frozen measurements rather than on
    the intervention set collapses those automatically.
    """
    return assess_measurements(alert, dict(frozen)).outcome


def reset_cache() -> None:
    """Clear the memoised assessments.

    Passed to the comparison harness so each algorithm pays the full cost of its own goal
    tests; otherwise the first algorithm to run subsidises every later one and the timing
    column measures nothing but run order.
    """
    _cached_outcome.cache_clear()


# --------------------------------------------------------------------------------------
# The product-facing answer
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceRequest:
    """What to ask for, why, and what it is expected to change."""

    target: str
    interventions: tuple[Intervention, ...]
    total_cost: float
    nodes_expanded: int
    algorithm: str
    found: bool = True

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.interventions)

    def to_text(self) -> str:
        if not self.found:
            return (
                f"No combination of available evidence would change this to {self.target}. "
                f"Some limits cannot be bought out of."
            )
        lines = [f"To reach {self.target}, obtain (total effort {self.total_cost:.0f}):"]
        lines.extend(
            f"  {index}. {item.description} (effort {item.cost:.0f})"
            for index, item in enumerate(self.interventions, start=1)
        )
        lines.append(
            "\nThis is what would change the system's assessment. It is not a prediction "
            "that the evidence will be favourable."
        )
        return "\n".join(lines)


def cheapest_evidence(
    alert: str,
    measurements: Measurements,
    target: str,
    *,
    max_interventions: int = 3,
    algorithm: str = "a-star") -> EvidenceRequest:
    """The least burdensome evidence that would move this case to ``target``."""
    from triagex.search.algorithms import ALGORITHMS

    problem = ContrastiveProblem(
        alert, measurements, target, max_interventions=max_interventions
    )
    result = ALGORITHMS[algorithm](problem)

    if not result.found or result.final_state is None:
        return EvidenceRequest(
            target=target,
            interventions=(),
            total_cost=0.0,
            nodes_expanded=result.nodes_expanded,
            algorithm=result.algorithm,
            found=False)

    chosen = tuple(problem.intervention(name) for name in result.actions)
    return EvidenceRequest(
        target=target,
        interventions=chosen,
        total_cost=result.cost,
        nodes_expanded=result.nodes_expanded,
        algorithm=result.algorithm)


@dataclass(frozen=True, slots=True)
class ContrastiveReport:
    """Every outcome this case could be moved to, and what it would take."""

    alert: str
    current: str
    requests: tuple[EvidenceRequest, ...] = field(default_factory=tuple)

    def reachable(self) -> tuple[EvidenceRequest, ...]:
        return tuple(r for r in self.requests if r.found)

    def to_text(self) -> str:
        lines = [f"{self.alert} is currently {self.current}."]
        for request in self.requests:
            lines.append("")
            lines.append(request.to_text())
        return "\n".join(lines)


def analyse(
    alert: str,
    measurements: Measurements,
    current: str,
    targets: Iterable[str] | None = None,
    *,
    max_interventions: int = 3) -> ContrastiveReport:
    """Run the contrastive search towards several outcomes at once."""
    from triagex.kb.predicates import DISPOSITIONS

    wanted = list(targets) if targets is not None else [d for d in DISPOSITIONS if d != current]
    requests = tuple(
        cheapest_evidence(alert, measurements, target, max_interventions=max_interventions)
        for target in wanted
    )
    return ContrastiveReport(alert=alert, current=current, requests=requests)
