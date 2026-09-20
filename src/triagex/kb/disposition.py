"""Layer 5, the disposition decision list.

The one place in this system where knowledge is ordered rather than declarative-unordered,
and the deviation is deliberate.

**Why a decision list instead of production rules.** Outcome precedence is inherently
ordered: a confirmed designation match outranks an abstention, which outranks an ordinary
referral, which outranks closure. Encoding that order into unordered production rules means
giving every lower stage explicit guards against every higher one, each stage needing "and
not the conditions of stages 1..n-1", which roughly triples the premise count, adds no
knowledge, and creates a maintenance hazard where adding a stage silently invalidates the
guards below it.

A decision list *is* a knowledge representation formalism, not a retreat from one. Each stage
carries the same metadata as a rule (source, provenance, rationale), the conditions are the
same ``Condition`` objects evaluated by the same matcher, and the stage that fired is
recorded with its premises so the result is as explainable as any inferred fact. What changes
is only that the first match wins.

**Three properties of the ordering, each a design claim rather than an accident:**

1. *Mandatory escalation outranks abstention.* A confirmed designation match on an
   out-of-scope case still escalates, because abstaining on it would itself be a failure to
   act. The veto layer may push a case through an abstention, but only upwards.
2. *Silence is a refusal, not a pass.* If no stage matches, the outcome is
   ``refuse_to_decide`` with reason ``deficiency``. Most engines fail open or fail silent.
3. *Closure is the most heavily guarded outcome.* It is the only stage requiring an explicit
   absence of prohibitions, and it sits last.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from triagex.dsl import Condition, Has, In, Missing, Provenance, Var, match_all
from triagex.facts import Derived, Fact, FactBase

A = Var("a")


@dataclass(frozen=True, slots=True)
class Stage:
    """One entry in the decision list."""

    id: str
    outcome: str
    when: tuple[Condition, ...]
    source: str
    provenance: Provenance
    rationale: str
    reason: str = ""
    """For abstentions: the machine-readable reason category."""

    tags: frozenset[str] = field(default_factory=frozenset)


_OFSI = "Sanctions and Anti-Money Laundering Act 2018; OFSI reporting obligations"
_POCA = "Proceeds of Crime Act 2002 s.330; JMLSG Part I ch.3 (the MLRO role)"
_SCOPE = "Project scope decision (docs/02-knowledge-acquisition.md)"
_MLR = "MLR 2017 Part 3; JMLSG Part I"


DECISION_LIST: tuple[Stage, ...] = (
    # -- 1. Mandatory escalation -------------------------------------------------------
    Stage(
        id="DISP-MAND-01",
        outcome="refer_to_investigation",
        when=(Has("mandatory_escalation", A, "present"),),
        source=_OFSI,
        provenance=Provenance.STATUTORY,
        rationale=(
            "A designation match requires a human with reporting authority, regardless of "
            "anything else the assessment found. This stage sits first so that it also "
            "overrides abstention: declining to decide on a confirmed match would itself be "
            "a failure to act."
        )),
    # -- 2-4. Epistemic boundaries -----------------------------------------------------
    Stage(
        id="DISP-REFUSE-01",
        outcome="refuse_to_decide",
        reason="out_of_scope",
        when=(Has("scope_state", A, "out_of_scope"),),
        source=_SCOPE,
        provenance=Provenance.RECONSTRUCTED,
        rationale=(
            "The case contains something this knowledge base has no model of. Any "
            "disposition would be a judgement on the part of the case that is understood, "
            "presented as a judgement on the whole."
        )),
    Stage(
        id="DISP-REFUSE-02",
        outcome="refuse_to_decide",
        reason="missing_premise",
        when=(Has("missing_premise", A),),
        source=_MLR,
        provenance=Provenance.STATUTORY,
        rationale=(
            "A premise the assessment requires was never established. The commonest case is "
            "sanctions screening that never ran, where proceeding would mean treating an "
            "unasked question as a clean answer."
        )),
    Stage(
        id="DISP-REFUSE-03",
        outcome="refuse_to_decide",
        reason="irreconcilable_conflict",
        when=(Has("conflict_state", A, "irreconcilable"),),
        source="Chow (1970); El-Yaniv and Wiener (2010) on the reject option",
        provenance=Provenance.RECONSTRUCTED,
        rationale=(
            "Substantial evidence points both ways and neither side dominates. Averaging "
            "two incompatible readings into a confident middle is what a scorer would do "
            "here, and it is the failure this outcome exists to prevent."
        )),
    # -- 5. Authority boundary ---------------------------------------------------------
    Stage(
        id="DISP-REFER-01",
        outcome="refer_to_investigation",
        when=(
            Has("typology_support", A, In("moderate", "strong")),
            Has("evidence_sufficiency", A, "sufficient")),
        source=_POCA,
        provenance=Provenance.STATUTORY,
        rationale=(
            "The evidence is complete and supports a recognised typology. The system knows "
            "what it is looking at - but only the MLRO can authorise a report, so this is a "
            "confident deferral rather than an admission of uncertainty."
        )),
    # -- 6. Evidence gathering ---------------------------------------------------------
    Stage(
        id="DISP-EVID-01",
        outcome="request_evidence",
        when=(
            Has("typology_support", A, In("moderate", "strong")),
            Has("evidence_sufficiency", A, In("partial", "insufficient"))),
        source=_MLR,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "A typology is supported but a nameable piece of evidence is missing. Asking is "
            "cheaper than escalating on an incomplete picture, and an escalation made after "
            "the answer arrives carries a far stronger narrative."
        )),
    Stage(
        id="DISP-EVID-02",
        outcome="request_evidence",
        when=(
            Has("typology_support", A, In("none", "weak")),
            Has("evidence_sufficiency", A, In("partial", "insufficient"))),
        source=_MLR,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Nothing about the activity is suspicious, but the customer file is incomplete. "
            "Closing would rest on records the firm itself considers inadequate, and "
            "escalating would waste an investigator on a paperwork gap - so ask."
        )),
    Stage(
        id="DISP-MON-02",
        outcome="monitor",
        when=(
            Has("scope_state", A, "boundary"),
            Has("typology_support", A, In("none", "weak")),
            Has("evidence_sufficiency", A, "sufficient"),
            Missing("disposition_blocked", A)),
        source="FATF Recommendation 1 (risk-based approach)",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Part of the case could not be assessed, and what was assessed looks unremarkable. "
            "Full closure would rest on the untested part, so the case closes with monitoring "
            "instead."
        )),
    # -- 7. Watchful close -------------------------------------------------------------
    Stage(
        id="DISP-MON-01",
        outcome="monitor",
        when=(
            Has("composite_risk", A, "moderate"),
            Has("typology_support", A, "weak"),
            Missing("disposition_blocked", A)),
        source="JMLSG Part I (ongoing monitoring); FCA Financial Crime Guide (April 2025)",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Something is faintly there but does not support escalation. Closing with "
            "enhanced monitoring keeps the case visible without consuming investigator time."
        )),
    # -- 8. Close ----------------------------------------------------------------------
    Stage(
        id="DISP-CLEAR-01",
        outcome="clear",
        when=(
            Has("composite_risk", A, "low"),
            Has("typology_support", A, "none"),
            Has("evidence_sufficiency", A, "sufficient"),
            Has("scope_state", A, "in_scope"),
            Has("conflict_state", A, In("none", "soft")),
            Missing("disposition_blocked", A)),
        source=_MLR,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Nothing is supported, the evidence is complete, the whole case was assessable "
            "and no prohibition applies. Closure is the most heavily guarded outcome in the "
            "list because it is the only one that ends the firm's attention entirely."
        )))


FALLTHROUGH = Stage(
    id="DISP-DEFICIENT-01",
    outcome="refuse_to_decide",
    reason="deficiency",
    when=(),
    source="Knowledge base coverage policy (docs/03-knowledge-model.md s.6)",
    provenance=Provenance.RECONSTRUCTED,
    rationale=(
        "No stage of the decision list matched this case. That is a gap in the knowledge "
        "base rather than a property of the case, so the system says so instead of falling "
        "back on a default. The verifier treats any case reaching this stage as a coverage "
        "defect to be fixed."
    ))


@dataclass(frozen=True, slots=True)
class Decision:
    """The outcome, and everything needed to explain it."""

    alert: str
    outcome: str
    stage: Stage
    premises: tuple[Fact, ...]
    reasons: tuple[str, ...] = ()

    @property
    def is_abstention(self) -> bool:
        return self.outcome == "refuse_to_decide"

    def describe(self) -> str:
        detail = f" ({', '.join(self.reasons)})" if self.reasons else ""
        return f"{self.outcome}{detail} [{self.stage.id}]"


def decide(
    fb: FactBase,
    alert: str,
    stages: tuple[Stage, ...] = DECISION_LIST,
    fallthrough: Stage | None = None) -> Decision:
    """Evaluate the decision list against the fact base; first match wins.

    ``stages`` and ``fallthrough`` are parameters so an ablation can vary the knowledge at the
    call site rather than through a hidden setting: the decision list *is* the knowledge.

    Both are needed to ablate abstention, which is not obvious. Deleting the refuse stages does
    not stop the system abstaining - the cases simply fall through, and the fallthrough abstains
    too, because silence is a refusal by design. Forcing the system to answer everything means
    substituting the fallthrough as well.
    """
    for stage in stages:
        for _bindings, premises in match_all(stage.when, fb, {"a": alert}):
            decision = Decision(
                alert=alert,
                outcome=stage.outcome,
                stage=stage,
                premises=premises,
                reasons=_reasons_for(fb, alert, stage))
            _assert_disposition(fb, decision)
            return decision

    final = fallthrough or FALLTHROUGH
    decision = Decision(
        alert=alert,
        outcome=final.outcome,
        stage=final,
        premises=(),
        reasons=(final.reason,) if final.reason else (),
    )
    _assert_disposition(fb, decision)
    return decision


def _reasons_for(fb: FactBase, alert: str, stage: Stage) -> tuple[str, ...]:
    """Name *why* an abstention happened, specifically enough to be actionable."""
    if stage.outcome != "refuse_to_decide":
        return ()

    if stage.reason == "out_of_scope":
        named = [str(f.value) for f in fb.facts_for("out_of_scope_reason", alert)]
        return tuple(named) or ("out of scope",)

    if stage.reason == "missing_premise":
        missing = sorted(str(f.value) for f in fb.facts_for("missing_premise", alert))
        return tuple(f"missing premise: {name}" for name in missing)

    return (stage.reason,)


def _assert_disposition(fb: FactBase, decision: Decision) -> None:
    fb.assert_fact(
        Fact(
            predicate="disposition",
            subject=decision.alert,
            value=decision.outcome,
            cf=1.0,
            derivation=Derived(rule_id=decision.stage.id, premises=decision.premises))
    )
