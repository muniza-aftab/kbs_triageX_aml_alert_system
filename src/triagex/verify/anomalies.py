"""Rule-base verification: what is wrong with the knowledge itself.

Tests check that the system behaves correctly on cases somebody thought of. Verification checks
the rule base for defects that no case would reveal, a rule that can never fire, a declared
value nothing can produce, two rules that will contradict each other on an input nobody has
written yet. The two are complementary and neither substitutes for the other.

The anomaly classes follow the rule-verification literature (Preece and Shinghal), adapted to
this knowledge base:

* **Redundancy**: two rules with identical premises and conclusion. Always a defect.
* **Subsumption**: one rule's premises are a subset of another's, same conclusion. *Usually*
  deliberate here: a refinement rule adds a premise and contributes extra certainty, which is
  how evidence accumulates. Only flagged when the strengths are equal, because then the extra
  premise buys nothing.
* **Unfirable rules**: premises that cannot be satisfied together, typically demanding two
  different values of one single-valued predicate.
* **Circularity**: a cycle in the predicate dependency graph. Should be impossible given the
  layer policy, which is exactly why it is worth checking: a guarantee nobody verifies is a
  hope.
* **Dangling premises**: a premise predicate that nothing produces, so the rule is dead in a
  way that reads as working.
* **Unreachable values**: a declared predicate value no rule, measurement or meta function can
  ever produce. Dead vocabulary. Harmless at runtime and actively misleading to a reader, who
  reasonably assumes a declared value means something.
* **Conflict**: two rules whose premises can hold together and whose conclusions are
  incompatible. In this knowledge base mutual exclusivity is engineered by hand, so any hit
  here is a hole in that hand work.
* **Dead rules**: rules that never fire across the whole corpus. Not necessarily defects, but
  each one is either untested or unnecessary, and the difference matters.

Severity is honest rather than uniform: ``error`` means the knowledge base is wrong,
``warning`` means something is probably wrong, ``note`` means a reader should know.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from triagex.dsl import (
    ANY,
    Cmp,
    Condition,
    Has,
    In,
    Missing,
    Ratio,
    Rule,
    RuleSet,
    Term,
    Var,
    Wildcard,
)
from triagex.kb.disposition import DECISION_LIST, FALLTHROUGH
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.meta import META_CONFLICT, META_PREMISE, META_SUPPORT
from triagex.kb.predicates import PREDICATES

SEVERITIES = ("error", "warning", "note")

_EPSILON = 1e-9
"""Nudge for strict inequalities, so `< 5` and `>= 5` are provably disjoint."""

META_PRODUCED: dict[str, frozenset[str]] = {
    "typology_support": frozenset({"none", "weak", "moderate", "strong"}),
    "conflict_state": frozenset({"none", "soft", "irreconcilable"}),
    "missing_premise": frozenset(),  # values are premise names, not a fixed set
}
"""Predicates produced by the meta functions rather than by rules.

The verifier has to be told about these explicitly. A static check that only reads the rule
set would otherwise report the entire meta layer as unproducible, which would be technically
correct and completely useless.
"""

META_RULE_IDS = frozenset({META_SUPPORT, META_CONFLICT, META_PREMISE})


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str
    severity: str
    message: str
    rule_ids: tuple[str, ...] = ()
    detail: str = ""

    def describe(self) -> str:
        where = f" [{', '.join(self.rule_ids)}]" if self.rule_ids else ""
        detail = f"\n      {self.detail}" if self.detail else ""
        return f"{self.severity.upper():<8} {self.kind:<20} {self.message}{where}{detail}"


@dataclass(slots=True)
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    rules_checked: int = 0
    cases_checked: int = 0

    def add(
        self,
        kind: str,
        severity: str,
        message: str,
        rule_ids: Iterable[str] = (),
        detail: str = "") -> None:
        self.findings.append(
            Finding(
                kind=kind,
                severity=severity,
                message=message,
                rule_ids=tuple(rule_ids),
                detail=detail)
        )

    def of_kind(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    def of_severity(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def errors(self) -> list[Finding]:
        return self.of_severity("error")

    @property
    def clean(self) -> bool:
        """No errors. Warnings and notes are information, not failure."""
        return not self.errors

    def render(self) -> str:
        lines = [
            f"rule-base audit: {self.rules_checked} rules"
            + (f", {self.cases_checked} cases replayed" if self.cases_checked else ""),
        ]
        counts = {s: len(self.of_severity(s)) for s in SEVERITIES}
        lines.append(
            "  " + ", ".join(f"{count} {severity}" for severity, count in counts.items())
        )
        lines.append("")
        for severity in SEVERITIES:
            for finding in self.of_severity(severity):
                lines.append("  " + finding.describe())
        if len(lines) == 3:
            lines.append("  nothing to report")
        return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Premise analysis
# --------------------------------------------------------------------------------------


def _term_values(term: Term) -> frozenset[object] | None:
    """The set of values a term admits, or ``None`` for 'anything'."""
    if isinstance(term, Wildcard | Var):
        return None
    if isinstance(term, In):
        return frozenset(term.options)
    return frozenset({term})


def _signature(condition: Condition) -> tuple[object, ...]:
    """A canonical, comparable form of a premise."""
    if isinstance(condition, Has):
        return ("has", condition.predicate, _term_values(condition.value), condition.min_cf, condition.max_cf)
    if isinstance(condition, Cmp):
        return ("cmp", condition.predicate, condition.op, condition.threshold)
    if isinstance(condition, Ratio):
        return ("ratio", condition.numerator, condition.denominator, condition.op, condition.multiple)
    if isinstance(condition, Missing):
        return ("missing", condition.predicate)
    return ("opaque", id(condition))


def _premise_set(rule: Rule) -> frozenset[tuple[object, ...]]:
    return frozenset(_signature(condition) for condition in rule.when)


def _value_demands(rule: Rule) -> dict[str, frozenset[object]]:
    """For each single-valued predicate, the values this rule's premises require."""
    demands: dict[str, frozenset[object]] = {}
    for condition in rule.when:
        if not isinstance(condition, Has):
            continue
        spec = PREDICATES.get(condition.predicate)
        if spec is None or spec.multi_valued:
            continue
        values = _term_values(condition.value)
        if values is None:
            continue
        existing = demands.get(condition.predicate)
        demands[condition.predicate] = values if existing is None else existing & values
    return demands


Interval = tuple[float, float]

_UNBOUNDED: Interval = (float("-inf"), float("inf"))


def _interval_demands(rule: Rule) -> dict[str, Interval]:
    """The numeric range each measurement must fall in for this rule to fire.

    Without this, every banded indicator looks like a possible conflict with its own siblings:
    ``credit_count >= 5`` and ``credit_count < 5`` are obviously exclusive to a reader and
    entirely opaque to a checker that only compares symbolic values. The first version of this
    verifier reported 23 such false positives, which is enough noise to make a real finding
    invisible.
    """
    demands: dict[str, Interval] = {}
    for condition in rule.when:
        if not isinstance(condition, Cmp):
            continue
        low, high = demands.get(condition.predicate, _UNBOUNDED)
        threshold = float(condition.threshold)
        if condition.op == ">=":
            low = max(low, threshold)
        elif condition.op == ">":
            low = max(low, threshold + _EPSILON)
        elif condition.op == "<=":
            high = min(high, threshold)
        elif condition.op == "<":
            high = min(high, threshold - _EPSILON)
        elif condition.op == "==":
            low, high = max(low, threshold), min(high, threshold)
        demands[condition.predicate] = (low, high)
    return demands


def _ratio_demands(rule: Rule) -> dict[tuple[str, str], Interval]:
    """The same, for ratio premises, keyed by the pair of predicates compared."""
    demands: dict[tuple[str, str], Interval] = {}
    for condition in rule.when:
        if not isinstance(condition, Ratio):
            continue
        key = (condition.numerator, condition.denominator)
        low, high = demands.get(key, _UNBOUNDED)
        multiple = float(condition.multiple)
        if condition.op == ">=":
            low = max(low, multiple)
        elif condition.op == ">":
            low = max(low, multiple + _EPSILON)
        elif condition.op == "<=":
            high = min(high, multiple)
        elif condition.op == "<":
            high = min(high, multiple - _EPSILON)
        demands[key] = (low, high)
    return demands


def _absence_demands(rule: Rule) -> set[str]:
    """Predicates this rule requires to be entirely absent."""
    return {c.predicate for c in rule.when if isinstance(c, Missing)}


def _presence_demands(rule: Rule) -> set[str]:
    """Predicates this rule requires to be present at some value."""
    return {c.predicate for c in rule.when if isinstance(c, Has)}


def _intervals_overlap(first: Interval, second: Interval) -> bool:
    return max(first[0], second[0]) <= min(first[1], second[1])


def _premises_compatible(first: Rule, second: Rule) -> bool:
    """Whether two rules could fire on the same case.

    Four grounds for provable exclusivity, in the order they matter here:

    1. Disjoint symbolic values of one single-valued predicate.
    2. Disjoint numeric intervals over one measurement.
    3. Disjoint ratio intervals over one pair of measurements.
    4. One rule requires a predicate absent while the other requires it present.

    Anything the checker cannot prove exclusive is treated as compatible, so it over-reports
    rather than under-reports - but the four grounds above cover every partition this rule base
    actually uses, which is what makes the output worth reading.
    """
    left, right = _value_demands(first), _value_demands(second)
    for predicate, values in left.items():
        other = right.get(predicate)
        if other is not None and not (values & other):
            return False

    left_intervals, right_intervals = _interval_demands(first), _interval_demands(second)
    for predicate, interval in left_intervals.items():
        other_interval = right_intervals.get(predicate)
        if other_interval is not None and not _intervals_overlap(interval, other_interval):
            return False

    left_ratios, right_ratios = _ratio_demands(first), _ratio_demands(second)
    for key, interval in left_ratios.items():
        other_ratio = right_ratios.get(key)
        if other_ratio is not None and not _intervals_overlap(interval, other_ratio):
            return False

    # One rule requiring a predicate absent while the other requires it present.
    return not (
        _absence_demands(first) & _presence_demands(second)
        or _absence_demands(second) & _presence_demands(first)
    )


# --------------------------------------------------------------------------------------
# Static checks
# --------------------------------------------------------------------------------------


def check_redundancy(rules: RuleSet, report: AuditReport) -> None:
    by_key: dict[tuple[object, ...], list[Rule]] = defaultdict(list)
    for rule in rules:
        key = (rule.then.predicate, _term_values(rule.then.value), _premise_set(rule))
        by_key[key].append(rule)

    for group in by_key.values():
        if len(group) > 1:
            report.add(
                "redundancy",
                "error",
                f"{len(group)} rules have identical premises and conclusion",
                [r.id for r in group])


def check_subsumption(rules: RuleSet, report: AuditReport) -> None:
    for general in rules:
        for specific in rules:
            if general.id == specific.id:
                continue
            if general.then.predicate != specific.then.predicate:
                continue
            if _term_values(general.then.value) != _term_values(specific.then.value):
                continue
            general_premises, specific_premises = _premise_set(general), _premise_set(specific)
            if not (general_premises < specific_premises):
                continue
            if general.strength == specific.strength:
                report.add(
                    "subsumption",
                    "warning",
                    f"{specific.id} adds premises to {general.id} but the same strength, "
                    f"so it can never change the outcome",
                    [general.id, specific.id])
            else:
                report.add(
                    "refinement",
                    "note",
                    f"{specific.id} refines {general.id} "
                    f"(strength {general.strength:+.2f} -> {specific.strength:+.2f})",
                    [general.id, specific.id])


def check_unfirable(rules: RuleSet, report: AuditReport) -> None:
    for rule in rules:
        demands: dict[str, frozenset[object]] = {}
        for condition in rule.when:
            if not isinstance(condition, Has):
                continue
            spec = PREDICATES.get(condition.predicate)
            if spec is None or spec.multi_valued:
                continue
            values = _term_values(condition.value)
            if values is None:
                continue
            if condition.predicate in demands:
                combined = demands[condition.predicate] & values
                if not combined:
                    report.add(
                        "unfirable",
                        "error",
                        f"{rule.id} requires incompatible values of "
                        f"{condition.predicate!r} and can never fire",
                        [rule.id])
                demands[condition.predicate] = combined
            else:
                demands[condition.predicate] = values

        # Presence is collected separately from `demands`, which only tracks single-valued
        # predicates. A multi-valued predicate required both present and absent is just as
        # unfirable, and checking only the single-valued ones missed exactly that case.
        required_present = _presence_demands(rule)
        for predicate in sorted(_absence_demands(rule) & required_present):
            report.add(
                "unfirable",
                "error",
                f"{rule.id} requires {predicate!r} to be both present and absent",
                [rule.id])


def check_circularity(rules: RuleSet, report: AuditReport) -> None:
    """Cycles in the predicate dependency graph."""
    edges: dict[str, set[str]] = defaultdict(set)
    for rule in rules:
        for predicate in rule.premise_predicates():
            edges[rule.then.predicate].add(predicate)

    colour: dict[str, int] = {}

    def visit(node: str, path: tuple[str, ...]) -> None:
        state = colour.get(node, 0)
        if state == 1:
            cycle = " -> ".join((*path, node))
            report.add("circularity", "error", f"dependency cycle: {cycle}")
            return
        if state == 2:
            return
        colour[node] = 1
        for nxt in sorted(edges.get(node, ())):
            visit(nxt, (*path, node))
        colour[node] = 2

    for node in sorted(edges):
        visit(node, ())


def producible_values(rules: RuleSet) -> dict[str, set[object]]:
    """Every value each predicate can actually take, from any source."""
    produced: dict[str, set[object]] = defaultdict(set)

    # Layer 0 measurements come from the loader, so every declared value is reachable.
    for name, spec in PREDICATES.items():
        if spec.layer == 0:
            produced[name] |= set(spec.values or ())

    for predicate, values in META_PRODUCED.items():
        produced[predicate] |= set(values)

    for rule in rules:
        target = rule.then.predicate
        value = rule.then.value
        if isinstance(value, Var):
            # The conclusion copies a value bound by a premise, so whatever that premise
            # admits is producible. IND-SEG-01 works this way.
            for condition in rule.when:
                if isinstance(condition, Has) and isinstance(condition.value, Var):
                    if condition.value.name == value.name:
                        produced[target] |= set(PREDICATES[condition.predicate].values or ())
                elif isinstance(condition, Has) and condition.value is ANY:
                    produced[target] |= set(PREDICATES[condition.predicate].values or ())
        else:
            admitted = _term_values(value)
            if admitted is not None:
                produced[target] |= set(admitted)

    for stage in (*DECISION_LIST, FALLTHROUGH):
        produced["disposition"].add(stage.outcome)

    return produced


def check_unreachable_values(rules: RuleSet, report: AuditReport) -> None:
    produced = producible_values(rules)
    for name, spec in sorted(PREDICATES.items()):
        if spec.values is None or spec.layer == 0:
            continue
        missing = sorted(str(v) for v in spec.values - {str(x) for x in produced.get(name, set())})
        if missing:
            report.add(
                "unreachable_value",
                "warning",
                f"{name}: declared value(s) nothing can produce: {', '.join(missing)}",
                detail=(
                    "Dead vocabulary. Harmless at runtime and misleading to read, because a "
                    "declared value implies something can mean it."
                ))


def check_dangling_premises(rules: RuleSet, report: AuditReport) -> None:
    produced = producible_values(rules)
    for rule in rules:
        for predicate in sorted(rule.premise_predicates()):
            spec = PREDICATES.get(predicate)
            if spec is None:
                report.add(
                    "dangling_premise",
                    "error",
                    f"{rule.id} reads unregistered predicate {predicate!r}",
                    [rule.id])
                continue
            if spec.layer == 0:
                continue
            if not produced.get(predicate):
                report.add(
                    "dangling_premise",
                    "error",
                    f"{rule.id} reads {predicate!r}, which nothing produces",
                    [rule.id])


def check_conflicts(rules: RuleSet, report: AuditReport) -> None:
    """Rules that could fire together and conclude incompatible values."""
    by_predicate: dict[str, list[Rule]] = defaultdict(list)
    for rule in rules:
        spec = PREDICATES.get(rule.then.predicate)
        if spec is not None and not spec.multi_valued:
            by_predicate[rule.then.predicate].append(rule)

    for predicate, group in sorted(by_predicate.items()):
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                first_values = _term_values(first.then.value)
                second_values = _term_values(second.then.value)
                if first_values is None or second_values is None:
                    continue
                if first_values & second_values:
                    continue  # same conclusion, not a conflict
                if _premises_compatible(first, second):
                    report.add(
                        "conflict",
                        "warning",
                        f"{first.id} and {second.id} may both fire and disagree on "
                        f"{predicate}",
                        [first.id, second.id],
                        detail=(
                            f"{first.id} concludes {sorted(str(v) for v in first_values)}, "
                            f"{second.id} concludes {sorted(str(v) for v in second_values)}. "
                            "Mutual exclusivity here is engineered by hand, so this is a hole "
                            "in that hand work unless the premises are exclusive for a reason "
                            "the verifier cannot see."
                        ))


# --------------------------------------------------------------------------------------
# Dynamic checks
# --------------------------------------------------------------------------------------


def check_dead_rules(
    rules: RuleSet,
    fired_ids: Iterable[str],
    report: AuditReport) -> None:
    fired = set(fired_ids)
    dead = sorted(rule.id for rule in rules if rule.id not in fired)
    if dead:
        report.add(
            "dead_rule",
            "warning",
            f"{len(dead)} rules never fired across the corpus",
            dead,
            detail=(
                "Each is either untested or unnecessary. The distinction matters: an untested "
                "rule is a gap in the corpus, an unnecessary one is a gap in the knowledge."
            ))


def check_stage_coverage(used_stage_ids: Iterable[str], report: AuditReport) -> None:
    used = set(used_stage_ids)
    unused = [stage.id for stage in DECISION_LIST if stage.id not in used]
    if unused:
        report.add(
            "stage_coverage",
            "note",
            f"{len(unused)} decision stages never fired across the corpus",
            unused)
    if FALLTHROUGH.id in used:
        report.add(
            "coverage_gap",
            "error",
            "a case reached the deficiency fallthrough",
            [FALLTHROUGH.id],
            detail="This is a hole in the decision list, not a property of the case.")


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def audit_static(rules: RuleSet = KNOWLEDGE_BASE) -> AuditReport:
    """Every check that needs only the rule base."""
    report = AuditReport(rules_checked=len(rules))
    check_redundancy(rules, report)
    check_subsumption(rules, report)
    check_unfirable(rules, report)
    check_circularity(rules, report)
    check_dangling_premises(rules, report)
    check_unreachable_values(rules, report)
    check_conflicts(rules, report)
    return report


def audit(
    rules: RuleSet = KNOWLEDGE_BASE,
    *,
    fired_ids: Sequence[str] | None = None,
    stage_ids: Sequence[str] | None = None,
    cases_checked: int = 0) -> AuditReport:
    """The full audit. Pass corpus results to enable the dynamic checks."""
    report = audit_static(rules)
    report.cases_checked = cases_checked
    if fired_ids is not None:
        check_dead_rules(rules, fired_ids, report)
    if stage_ids is not None:
        check_stage_coverage(stage_ids, report)
    return report
