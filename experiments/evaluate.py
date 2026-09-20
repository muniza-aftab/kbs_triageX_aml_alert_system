"""Run the full evaluation. ``python experiments/evaluate.py``

Produces the risk-coverage curve, the four ablations and a confusion matrix, and writes the
tables to ``results/`` so the documentation quotes measured numbers rather than remembered ones.

The flat baseline is included because this project's documentation repeatedly claims a flat
scorer would do worse. That claim should be measured.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flat_baseline import flat_evaluation

from triagex.data.generator import generate
from triagex.engine.certainty import BAYESIAN_POLICY
from triagex.evaluate import (
    CAVEAT,
    Evaluation,
    coverage_curve,
    evaluate,
    format_confusion,
    format_curve,
    format_summary,
)
from triagex.kb.disposition import DECISION_LIST
from triagex.kb.knowledge_base import (
    ASSESSMENT_RULES,
    INDICATOR_RULES,
    POSTURE_RULES,
    TYPOLOGY_RULES,
)
from triagex.pipeline import FORCED_ANSWER_STAGE, Configuration
from triagex.terminal import configure_stdout

CORPUS = 500
SEED = 20260920
TAUS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
RESULTS = Path(__file__).resolve().parents[1] / "results"


def ablations() -> list[Configuration]:
    """Each one removes exactly one thing, so the difference is attributable."""
    no_abstention = tuple(s for s in DECISION_LIST if s.outcome != "refuse_to_decide")
    return [
        Configuration(name="full system"),
        # Deleting the refuse stages alone does not remove abstention: the freed cases fall
        # through, and the fallthrough abstains too. Both configurations are shown because the
        # difference between them is the finding.
        Configuration(name="refuse stages removed", stages=no_abstention),
        Configuration(
            name="forced to answer",
            stages=no_abstention,
            fallthrough=FORCED_ANSWER_STAGE),
        Configuration(
            name="no veto layer",
            rules=INDICATOR_RULES + TYPOLOGY_RULES + ASSESSMENT_RULES + POSTURE_RULES),
        Configuration(name="bayesian certainty", policy=BAYESIAN_POLICY),
        Configuration(name="no meta layer", enable_meta=False),
    ]


def section(title: str, body: str) -> str:
    bar = "=" * 86
    return f"\n{bar}\n{title}\n{bar}\n{body}\n"


def main() -> int:
    configure_stdout()
    RESULTS.mkdir(parents=True, exist_ok=True)

    cases = generate(CORPUS, seed=SEED)
    unanswerable = sum(1 for c in cases if c.expected_family is None)

    chunks: list[str] = []
    chunks.append(
        section(
            f"Corpus: {len(cases)} generated cases, seed {SEED}",
            f"{unanswerable} have no defensible answer by construction "
            f"({unanswerable / len(cases):.1%}).\n{CAVEAT}")
    )

    # ------------------------------------------------------------------ ablations
    evaluations: list[Evaluation] = [evaluate(cases, config) for config in ablations()]
    evaluations.append(flat_evaluation(cases))
    chunks.append(section("Ablations", format_summary(evaluations)))

    # ------------------------------------------------------------------ coverage curve
    points = coverage_curve(cases, TAUS)
    chunks.append(
        section(
            "Risk-coverage curve (sweeping the abstention margin)",
            format_curve(points)
            + "\n\nThe mechanism swept is the margin between the deciding certainty and the band"
            "\nboundary that produced it - the same quantity the explanation facility reports"
            "\nwhen it says how close a call was.")
    )

    # ------------------------------------------------------------------ confusion
    chunks.append(
        section("Confusion matrix, full system", format_confusion(evaluations[0]))
    )

    report = "".join(chunks)
    print(report)
    (RESULTS / "evaluation.txt").write_text(report, encoding="utf-8")
    print(f"written to {RESULTS / 'evaluation.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
