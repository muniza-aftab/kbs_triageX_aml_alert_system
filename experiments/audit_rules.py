"""Audit the rule base. Run with ``python experiments/audit_rules.py``.

Static checks read the rule base alone. Dynamic checks replay the curated library and a seeded
generated corpus, so "this rule never fires" is a measured claim rather than a guess.

Exit code is 1 if any finding has severity ``error``, so this is usable as a gate. Warnings and
notes do not fail the run: a dead rule is worth knowing about and is not a reason to refuse to
ship.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from triagex.data.generator import generate
from triagex.data.loader import factbase_for, load_library
from triagex.pipeline import assess, assess_measurements
from triagex.terminal import configure_stdout
from triagex.verify.anomalies import audit

CORPUS_SIZE = 800
SEED = 41


def main() -> int:
    configure_stdout()

    fired: list[str] = []
    stages: list[str] = []
    cases = 0

    for case in load_library():
        result = assess(factbase_for(case), case.alert_id)
        fired.extend(result.trace.fired_rule_ids)
        stages.append(result.decision.stage.id)
        cases += 1

    for generated in generate(CORPUS_SIZE, seed=SEED):
        result = assess_measurements(generated.alert_id, generated.measurements)
        fired.extend(result.trace.fired_rule_ids)
        stages.append(result.decision.stage.id)
        cases += 1

    report = audit(fired_ids=fired, stage_ids=stages, cases_checked=cases)
    print(report.render())

    if report.errors:
        print(f"\n{len(report.errors)} error(s): the knowledge base is wrong, not merely untidy.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
