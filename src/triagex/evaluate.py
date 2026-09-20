"""Evaluation: what the system costs when it is wrong.

**Accuracy is the wrong metric here and the code says so.** Clearing a case that should have
been referred lets laundering through; referring a clean customer consumes an investigator and
can freeze an innocent person's account. Those are not the same error and no single accuracy
figure can distinguish them. So the primary measure is *risk-weighted cost*, using the
asymmetric matrix in ``kb/reference.py``.

**Abstention is priced, not free.** Declining costs less than a serious error and more than
nothing, because a system that abstains on everything is useless. The one place abstention is
free is on cases that have no defensible answer, and those cases exist in the corpus precisely
so the reject option can be shown to pay for itself rather than assumed to.

**What these numbers are not.** The corpus is synthetic and its labels are true by construction.
Everything here measures internal consistency, the shape of the coverage trade-off, and the
effect of the ablations. None of it is evidence about real-world accuracy, which would need
outcome data from filed reports that no public dataset provides. The evaluation writes this
caveat into its own output so a number cannot be quoted without it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from triagex.data.generator import GeneratedCase
from triagex.kb.predicates import DISPOSITIONS
from triagex.kb.reference import ABSTENTION_COST, AMBIGUOUS_DECISION_COST, MISCLASSIFICATION_COSTS
from triagex.pipeline import Configuration, assess_measurements

ABSTAIN = "refuse_to_decide"

CAVEAT = (
    "Synthetic corpus with labels true by construction. These figures measure internal "
    "consistency and the shape of the coverage trade-off, not real-world accuracy."
)


def cost_of(expected: str | None, predicted: str) -> float:
    """The risk-weighted cost of one decision.

    Four cases, and the asymmetry between them is the whole point:

    * no defensible answer, system declined -> free, this is the right call
    * no defensible answer, system decided  -> penalised, it answered what it should not
    * a correct answer exists, system declined -> the abstention cost
    * a correct answer exists, system decided  -> zero if right, the matrix if wrong
    """
    if expected is None:
        return 0.0 if predicted == ABSTAIN else AMBIGUOUS_DECISION_COST
    if predicted == expected:
        # Includes abstaining on a case that should be abstained on. The first version of this
        # function checked for abstention *before* checking correctness, so declining an
        # out-of-scope case was charged the abstention cost while answering it wrongly fell
        # through to a default of 1.0 - making the correct action cost twice the incorrect one.
        # The abstention ablation looked like it beat the full system because of this.
        return 0.0
    if predicted == ABSTAIN:
        return ABSTENTION_COST
    return MISCLASSIFICATION_COSTS.get((expected, predicted), 1.0)


@dataclass(frozen=True, slots=True)
class CaseResult:
    alert: str
    intent: str
    expected: str | None
    predicted: str
    cost: float
    margin: float | None = None

    @property
    def abstained(self) -> bool:
        return self.predicted == ABSTAIN

    @property
    def correct(self) -> bool:
        return self.expected is not None and self.predicted == self.expected


@dataclass(slots=True)
class Evaluation:
    """Aggregate results for one configuration over one corpus."""

    config_name: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def total_cost(self) -> float:
        return sum(r.cost for r in self.results)

    @property
    def mean_cost(self) -> float:
        return self.total_cost / self.total if self.total else 0.0

    @property
    def abstentions(self) -> int:
        return sum(1 for r in self.results if r.abstained)

    @property
    def coverage(self) -> float:
        """Share of cases the system was willing to decide."""
        return 1.0 - (self.abstentions / self.total) if self.total else 0.0

    @property
    def decided(self) -> list[CaseResult]:
        return [r for r in self.results if not r.abstained]

    @property
    def selective_accuracy(self) -> float:
        """Accuracy on the cases it chose to answer, ignoring unlabelled ones.

        Reported alongside coverage and never alone: a selective classifier can reach any
        accuracy at all by answering less, so the pair is the only honest reading.
        """
        labelled = [r for r in self.decided if r.expected is not None]
        if not labelled:
            return 0.0
        return sum(1 for r in labelled if r.correct) / len(labelled)

    @property
    def unanswerable_answered(self) -> int:
        """Cases with no defensible answer that the system answered anyway."""
        return sum(1 for r in self.results if r.expected is None and not r.abstained)

    @property
    def dangerous_errors(self) -> int:
        """Cases that should have been referred and were cleared or merely monitored.

        Tracked separately because it is the error class the domain actually fears, and a
        mean-cost figure can hide a handful of them behind many cheap successes.
        """
        return sum(
            1
            for r in self.results
            if r.expected == "refer_to_investigation" and r.predicted in {"clear", "monitor"}
        )

    def confusion(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for result in self.results:
            key = (result.expected or "unanswerable", result.predicted)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def summary_row(self) -> str:
        return (
            f"{self.config_name:<22} {self.mean_cost:>9.3f} {self.coverage:>9.1%} "
            f"{self.selective_accuracy:>9.1%} {self.abstentions:>7} "
            f"{self.unanswerable_answered:>9} {self.dangerous_errors:>8}"
        )


SUMMARY_HEADER = (
    f"{'configuration':<22} {'cost/case':>9} {'coverage':>9} {'sel.acc':>9} "
    f"{'abstain':>7} {'answered?':>9} {'missed':>8}"
)


def evaluate(
    cases: Sequence[GeneratedCase],
    config: Configuration) -> Evaluation:
    """Run one configuration over a corpus."""
    evaluation = Evaluation(config_name=config.name)
    for case in cases:
        assessment = assess_measurements(case.alert_id, case.measurements, config=config)
        evaluation.results.append(
            CaseResult(
                alert=case.alert_id,
                intent=case.intent,
                expected=case.expected_family,
                predicted=assessment.outcome,
                cost=cost_of(case.expected_family, assessment.outcome),
                margin=assessment.margin)
        )
    return evaluation


# --------------------------------------------------------------------------------------
# Coverage curve
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoveragePoint:
    tau: float
    coverage: float
    mean_cost: float
    selective_accuracy: float
    unanswerable_answered: int
    dangerous_errors: int


def coverage_curve(
    cases: Sequence[GeneratedCase],
    taus: Iterable[float],
    *,
    base: Configuration | None = None) -> list[CoveragePoint]:
    """Sweep the abstention margin and record the trade-off at each setting.

    This is the risk-coverage curve from the selective-classification literature, applied to a
    symbolic system. The mechanism being swept is not a probability threshold but the margin
    between the deciding certainty and the band boundary that produced it - the same quantity
    the explanation facility reports when it says how close a call was.
    """
    template = base or Configuration()
    points = []
    for tau in taus:
        config = Configuration(
            name=f"tau={tau:.2f}",
            rules=template.rules,
            stages=template.stages,
            policy=template.policy,
            enable_meta=template.enable_meta,
            margin_tau=tau)
        evaluation = evaluate(cases, config)
        points.append(
            CoveragePoint(
                tau=tau,
                coverage=evaluation.coverage,
                mean_cost=evaluation.mean_cost,
                selective_accuracy=evaluation.selective_accuracy,
                unanswerable_answered=evaluation.unanswerable_answered,
                dangerous_errors=evaluation.dangerous_errors)
        )
    return points


def format_curve(points: Sequence[CoveragePoint]) -> str:
    header = (
        f"{'tau':>6} {'coverage':>9} {'cost/case':>10} {'sel.acc':>9} "
        f"{'answered?':>10} {'missed':>7}"
    )
    lines = [header, "-" * len(header)]
    best = min(points, key=lambda p: p.mean_cost) if points else None
    for point in points:
        marker = "  <- lowest cost" if best is not None and point is best else ""
        lines.append(
            f"{point.tau:>6.2f} {point.coverage:>9.1%} {point.mean_cost:>10.3f} "
            f"{point.selective_accuracy:>9.1%} {point.unanswerable_answered:>10} "
            f"{point.dangerous_errors:>7}{marker}"
        )
    return "\n".join(lines)


def format_confusion(evaluation: Evaluation) -> str:
    labels = [*DISPOSITIONS, "unanswerable"]
    predicted_labels = list(DISPOSITIONS)
    counts = evaluation.confusion()
    width = max(len(label) for label in labels) + 2

    header = " " * width + "".join(f"{p[:9]:>11}" for p in predicted_labels)
    lines = ["expected \\ predicted", header, "-" * len(header)]
    for expected in labels:
        row = f"{expected:<{width}}"
        for predicted in predicted_labels:
            value = counts.get((expected, predicted), 0)
            row += f"{value if value else '.':>11}"
        lines.append(row)
    return "\n".join(lines)


def format_summary(evaluations: Sequence[Evaluation]) -> str:
    lines = [SUMMARY_HEADER, "-" * len(SUMMARY_HEADER)]
    lines.extend(e.summary_row() for e in evaluations)
    lines.append("")
    lines.append(
        "cost/case  risk-weighted, lower is better    coverage   share of cases decided\n"
        "sel.acc    accuracy on decided, labelled cases only\n"
        "answered?  cases with no defensible answer that were answered anyway\n"
        "missed     should have been referred, was cleared or monitored"
    )
    return "\n".join(lines)
