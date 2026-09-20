"""Command-line interface.

``argparse`` from the standard library, because the core of this project has no runtime
dependencies and a CLI framework is not worth breaking that for.

Every command answers a question somebody would actually ask:

* ``cases`` / ``rules``   what is in here?
* ``run``                 what does the system make of this case, and why?
* ``consult``             assess a case that has no file
* ``evidence``            what would have to change?
* ``graph``               where did the money go?
* ``dossier``             produce something to hand to someone
* ``audit``               is the knowledge base sound?
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from triagex.data.generator import generate
from triagex.data.loader import (
    CASE_DIR,
    Case,
    CaseFormatError,
    case_paths,
    factbase_for,
    load_case,
    load_library,
    measurements,
)
from triagex.explain.dossier import write_dossier
from triagex.explain.why import explain, how, why_not, why_not_all
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.predicates import DISPOSITIONS, FactValue
from triagex.pipeline import Assessment, assess, assess_measurements
from triagex.search.contrastive import analyse, cheapest_evidence
from triagex.search.network import graph_for_case
from triagex.terminal import configure_stdout
from triagex.verify.anomalies import audit

BANNER = "TriageX: Intelligent AML Alert Triage and Risk Prioritization"

DISCLAIMER = (
    "Illustrative system on synthetic data. Thresholds, jurisdictions and screening results\n"
    "are invented. Nothing here may be used to decide anything about a real person."
)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _resolve_case(reference: str) -> Case:
    """Accept a path, a file stem, or an alert id."""
    candidate = Path(reference)
    if candidate.is_file():
        return load_case(candidate)

    stem = CASE_DIR / f"{reference.removesuffix('.toml')}.toml"
    if stem.is_file():
        return load_case(stem)

    for case in load_library():
        if case.alert_id.lower() == reference.lower():
            return case

    available = ", ".join(sorted(p.stem for p in case_paths())[:6])
    raise SystemExit(
        f"no case matching {reference!r}. Try an alert id or a file stem, e.g. {available} ..."
    )


def _assess_case(case: Case) -> Assessment:
    return assess(factbase_for(case), case.alert_id)


def _rule(text: str) -> str:
    return text + "\n" + "-" * len(text)


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------


def cmd_cases(args: argparse.Namespace) -> int:
    library = load_library()
    print(_rule(f"{len(library)} cases in the library"))
    for case in library:
        expected = case.expectation.disposition or "-"
        tags = ", ".join(case.tags)
        name = case.source_path.stem if case.source_path else case.alert_id
        print(f"  {case.alert_id:<10} {expected:<22} {name:<44} {tags}")
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    rules = [r for r in KNOWLEDGE_BASE if args.layer is None or r.layer == args.layer]
    print(_rule(f"{len(rules)} rules" + (f" at layer {args.layer}" if args.layer else "")))
    for rule in sorted(rules, key=lambda r: (r.layer, r.id)):
        print(f"  {rule.id:<20} L{rule.layer}  {rule.provenance.value:<14} s={rule.strength:+.2f}")
        if args.verbose:
            print(f"      {rule.rationale}")
            print(f"      source: {rule.source}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    case = _resolve_case(args.case)
    result = _assess_case(case)

    if args.explain:
        print(explain(result).to_text())
    else:
        print(result.summary())

    if args.why_not:
        print()
        for outcome, verdict in why_not_all(result).items():
            if args.why_not != "all" and outcome != args.why_not:
                continue
            print(verdict.to_text())
            print()

    if args.how:
        print()
        print(how(result, args.how))

    if args.trace:
        print()
        print(result.trace.render(include_rejected=args.verbose))

    if case.expectation.disposition:
        agreement = "as expected" if result.outcome == case.expectation.disposition else "UNEXPECTED"
        print(f"\ncase file expected {case.expectation.disposition} ({agreement})")
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    case = _resolve_case(args.case)
    result = _assess_case(case)
    values = measurements(case)

    print(_rule(f"{case.alert_id} is currently {result.outcome}"))
    if args.target:
        print(cheapest_evidence(case.alert_id, values, args.target, max_interventions=args.depth).to_text())
    else:
        print(analyse(case.alert_id, values, result.outcome, max_interventions=args.depth).to_text())
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    case = _resolve_case(args.case)
    graph = graph_for_case(case)

    print(_rule(f"{case.alert_id}: {len(graph)} parties, {len(graph.flows)} flows"))
    for node in graph.nodes:
        inbound = graph.in_degree(node)
        if inbound:
            print(f"  {node:<16} {inbound:>3} distinct payers, {graph.inbound_value(node):>12.0f} in")

    cycles = graph.find_cycles()
    print(f"\ncircular flows: {len(cycles)}")
    for cycle in cycles:
        print("  " + " -> ".join((*cycle, cycle[0])))

    betweenness = {n: s for n, s in graph.betweenness().items() if s > 0}
    if betweenness:
        print("\nnodes every route passes through:")
        for node, score in sorted(betweenness.items(), key=lambda kv: -kv[1]):
            print(f"  {node:<16} {score:.1f}")
    return 0


def cmd_dossier(args: argparse.Namespace) -> int:
    targets = load_library() if args.case == "all" else [_resolve_case(args.case)]
    out = Path(args.output)
    written = []
    for case in targets:
        result = _assess_case(case)
        written.append(write_dossier(result, out, case_notes=case.expectation.notes))
    print(f"wrote {len(written)} dossier(s) to {out}")
    if len(written) == 1:
        print(f"  {written[0]}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    fired: list[str] = []
    stages: list[str] = []
    cases = 0

    if args.corpus:
        for case in load_library():
            result = _assess_case(case)
            fired.extend(result.trace.fired_rule_ids)
            stages.append(result.decision.stage.id)
            cases += 1
        for generated in generate(args.corpus, seed=args.seed):
            result = assess_measurements(generated.alert_id, generated.measurements)
            fired.extend(result.trace.fired_rule_ids)
            stages.append(result.decision.stage.id)
            cases += 1

    report = audit(
        fired_ids=fired if args.corpus else None,
        stage_ids=stages if args.corpus else None,
        cases_checked=cases)
    print(report.render())
    return 1 if report.errors else 0


def cmd_consult(args: argparse.Namespace) -> int:
    """Interactive assessment, asking only what the rules need."""
    import random

    from triagex.data.generator import _baseline

    print(_rule(BANNER))
    print(DISCLAIMER)
    print("\nPress enter to accept the default shown in brackets. Ctrl-C to stop.\n")

    values = _baseline(random.Random(0))
    for predicate in _consultation_order():
        default = values.get(predicate)
        try:
            raw = input(f"  {predicate} [{default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nstopped")
            return 130
        if raw:
            values[predicate] = _coerce(raw, default)

    result = assess_measurements("ALT-CONSULT", values)
    print()
    print(explain(result).to_text())
    print()
    print(why_not(result, "clear").to_text())
    return 0


def _consultation_order() -> list[str]:
    """Which questions to ask, and in what order.

    Mandatory premises first, because an unanswered one makes every other answer irrelevant -
    the system will refuse regardless. After that, measurements are ordered by how many rules
    read them, so the questions that unlock the most inference come first.

    This is a usage-frequency heuristic, not a true value-of-information ordering. A proper one
    would estimate each question's expected effect on the disposition, which needs a
    distribution over answers that this system does not have.
    """
    from collections import Counter

    usage: Counter[str] = Counter()
    for rule in KNOWLEDGE_BASE:
        if rule.layer != 1:
            continue
        for predicate in rule.premise_predicates():
            usage[predicate] += 1

    mandatory = ["sanctions_signal", "kyc_status", "customer_type"]
    rest = [p for p, _ in usage.most_common() if p not in mandatory]
    return mandatory + rest[:10]


def _coerce(raw: str, default: FactValue | None) -> FactValue:
    """Interpret typed input the way the default suggests.

    The default's type is the only schema available here, which is crude but honest: the
    measurement vocabulary declares numeric predicates as open, so there is nothing stricter to
    validate against until the fact base rejects the value.
    """
    if isinstance(default, bool):
        return raw.lower() in {"true", "yes", "y", "1"}
    if isinstance(default, int | float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


# --------------------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triagex", description=BANNER, epilog=DISCLAIMER)
    parser.add_argument("-v", "--verbose", action="store_true", help="more detail")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("cases", help="list the case library").set_defaults(func=cmd_cases)

    rules = sub.add_parser("rules", help="list the rule base")
    rules.add_argument("--layer", type=int, choices=[1, 2, 3, 4], help="only this layer")
    rules.set_defaults(func=cmd_rules)

    run = sub.add_parser("run", help="assess a case")
    run.add_argument("case", help="alert id, file stem, or path")
    run.add_argument("--explain", action="store_true", help="full reasoning")
    run.add_argument(
        "--why-not",
        nargs="?",
        const="all",
        choices=[*DISPOSITIONS, "all"],
        help="why some other outcome was not reached")
    run.add_argument("--how", metavar="PREDICATE", help="derivation of one conclusion")
    run.add_argument("--trace", action="store_true", help="inference trace")
    run.set_defaults(func=cmd_run)

    evidence = sub.add_parser("evidence", help="what would change the decision")
    evidence.add_argument("case")
    evidence.add_argument("--target", choices=DISPOSITIONS, help="outcome to aim for")
    evidence.add_argument("--depth", type=int, default=3, help="max interventions")
    evidence.set_defaults(func=cmd_evidence)

    graph = sub.add_parser("graph", help="counterparty network analysis")
    graph.add_argument("case")
    graph.set_defaults(func=cmd_graph)

    dossier = sub.add_parser("dossier", help="write a self-contained HTML dossier")
    dossier.add_argument("case", help="alert id, file stem, path, or 'all'")
    dossier.add_argument("-o", "--output", default="results/dossiers")
    dossier.set_defaults(func=cmd_dossier)

    audit_cmd = sub.add_parser("audit", help="verify the rule base")
    audit_cmd.add_argument(
        "--corpus",
        type=int,
        default=800,
        help="generated cases for the dynamic checks (0 for static only)")
    audit_cmd.add_argument("--seed", type=int, default=41)
    audit_cmd.set_defaults(func=cmd_audit)

    sub.add_parser("consult", help="assess a case interactively").set_defaults(func=cmd_consult)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
    except CaseFormatError as exc:
        print(f"invalid case: {exc}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
