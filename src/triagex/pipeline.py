"""The assessment pipeline: case in, disposition out.

One assessment is deliberately not one pass. It alternates between inference and
meta-level assessment, because the meta-layer has to look at what the domain rules
concluded before the disposition layer can act:

```
  measurements
       |
   [ chain ]      indicators, typologies, assessment (layers 1-3)
       |
   [ meta  ]      strongest typology -> support band
                  mandatory premises established?
                  does the evidence contradict itself?
       |
   [ chain ]      composite risk, prohibitions (layer 4)
       |
  [ decide ]      the decision list (layer 5)
```

Refraction state is shared across both chaining runs. Repeated conclusions *combine*
certainty, so a rule re-firing on evidence it has already used would inflate its own
conclusion, evidence counted twice is not stronger evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from triagex.engine.certainty import MYCIN_POLICY, CertaintyPolicy
from triagex.engine.forward import ForwardChainer
from triagex.engine.trace import Trace
from triagex.facts import Derived, Fact, FactBase
from triagex.kb.disposition import DECISION_LIST, Decision, Stage, decide
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.meta import run_meta_pass, support_margin
from triagex.kb.predicates import FactValue


@dataclass(frozen=True, slots=True)
class Configuration:
    """Everything an ablation can vary.

    Each field exists because one ablation needs it, and the defaults are the real system. A
    configuration object is the honest way to run ablations: the alternative is a second code
    path that nobody maintains and that stops resembling the system it is meant to be compared
    against.
    """

    name: str = "default"
    rules: object = None
    """Rule set to run. ``None`` means the full knowledge base."""

    stages: tuple[Stage, ...] = DECISION_LIST
    fallthrough: Stage | None = None
    """Substituted when nothing matches. ``None`` keeps the deficiency abstention. An ablation
    that wants the system to answer everything must replace this as well as removing the refuse
    stages, because otherwise the cases it frees up simply fall through to an abstention."""

    policy: CertaintyPolicy = MYCIN_POLICY
    enable_meta: bool = True
    """When false, the meta layer is skipped entirely: no support band, no missing-premise
    detection, no conflict detection. Measures what the abstention machinery is worth."""

    margin_tau: float = 0.0
    """Selective prediction. Abstain when the deciding typology sits within this margin of the
    band floor, because such a decision would flip on a small change of evidence. Zero disables
    it, which is the default: the mechanism is a tunable overlay, not part of the knowledge."""

    def rule_set(self) -> object:
        return self.rules if self.rules is not None else KNOWLEDGE_BASE


DEFAULT_CONFIG = Configuration()

BORDERLINE_STAGE = Stage(
    id="DISP-BORDERLINE-01",
    outcome="refuse_to_decide",
    reason="borderline_margin",
    when=(),
    source="Chow (1970); El-Yaniv and Wiener (2010) on selective classification",
    provenance=DECISION_LIST[0].provenance,
    rationale=(
        "The deciding certainty sits so close to a band boundary that the answer would flip on "
        "a small change of evidence. Declining a decision this marginal is what the reject "
        "option is for, and the threshold is tunable rather than baked into the knowledge."
    ))


@dataclass(frozen=True, slots=True)
class Assessment:
    """Everything one case produced: the answer, and the means to justify it."""

    alert: str
    facts: FactBase
    trace: Trace
    decision: Decision
    config_name: str = "default"
    margin: float | None = None
    """How far the deciding certainty sat from the band floor, when a typology was believed."""

    @property
    def outcome(self) -> str:
        return self.decision.outcome

    def summary(self) -> str:
        lines = [f"{self.alert}: {self.decision.describe()}"]
        for predicate in (
            "typology_support",
            "composite_risk",
            "evidence_sufficiency",
            "conflict_state",
            "scope_state"):
            value = self.facts.value_of(predicate, self.alert)
            if value is not None:
                lines.append(f"  {predicate:<22} {value}")
        typologies = sorted(
            (f for f in self.facts.facts_for("typology", self.alert) if f.cf > 0),
            key=lambda f: -f.cf)
        for fact in typologies:
            lines.append(f"  typology               {fact.value} (cf {fact.cf:+.2f})")
        return "\n".join(lines)


def factbase_from_measurements(
    alert: str,
    measurements: dict[str, FactValue],
    *,
    field_prefix: str = "case",
    policy: CertaintyPolicy = MYCIN_POLICY) -> FactBase:
    """Seed a fact base with layer 0 measurements.

    This is the seam the case-file loader will sit behind. Keeping it separate means the
    rule base is exercised through exactly the same interface whether measurements come
    from a file, a generator or a test.
    """
    fb = FactBase(policy)
    for predicate, value in measurements.items():
        fb.assert_raw(predicate, alert, value, field=f"{field_prefix}.{predicate}")
    return fb


def assess(
    fb: FactBase,
    alert: str,
    *,
    max_cycles: int = 500,
    config: Configuration = DEFAULT_CONFIG) -> Assessment:
    """Run the full pipeline over a seeded fact base."""
    chainer = ForwardChainer(
        config.rule_set(),  # type: ignore[arg-type]
        max_cycles=max_cycles,
        policy=config.policy)
    fired: set[object] = set()

    trace = chainer.run(fb, fired)
    if config.enable_meta:
        run_meta_pass(fb, alert, trace)
    trace.extend(chainer.run(fb, fired))

    decision = decide(fb, alert, config.stages, config.fallthrough)
    margin = support_margin(fb, alert)

    if (
        config.margin_tau > 0.0
        and not decision.is_abstention
        and margin is not None
        and margin < config.margin_tau
    ):
        decision = Decision(
            alert=alert,
            outcome=BORDERLINE_STAGE.outcome,
            stage=BORDERLINE_STAGE,
            premises=decision.premises,
            reasons=(
                f"decision margin {margin:+.2f} is inside the {config.margin_tau:.2f} "
                f"abstention band",
            ),
        )
        fb.assert_fact(
            Fact(
                predicate="disposition",
                subject=alert,
                value=decision.outcome,
                cf=1.0,
                derivation=Derived(rule_id=BORDERLINE_STAGE.id, premises=decision.premises))
        )

    return Assessment(
        alert=alert,
        facts=fb,
        trace=trace,
        decision=decision,
        config_name=config.name,
        margin=margin)


def assess_measurements(
    alert: str,
    measurements: dict[str, FactValue],
    *,
    config: Configuration = DEFAULT_CONFIG) -> Assessment:
    """Convenience: seed from measurements and assess in one call."""
    fb = factbase_from_measurements(alert, measurements, policy=config.policy)
    return assess(fb, alert, config=config)


FORCED_ANSWER_STAGE = Stage(
    id="ABL-FORCED-01",
    outcome="monitor",
    when=(),
    source="Ablation harness, not knowledge",
    provenance=DECISION_LIST[0].provenance,
    rationale=(
        "Ablation only: answer rather than decline when nothing else matches. Monitor is the "
        "least-committal available answer, so this is the most charitable possible version of "
        "a system with no reject option."
    ))
