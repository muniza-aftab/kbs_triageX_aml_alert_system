"""Layers 3 and 4, assessment and posture.

Layer 3 (assessment) answers questions about the case that do not depend on each other:
is the evidence sufficient, is this case in scope, does a statutory trigger apply.

Layer 4 (posture) answers the one question that depends on the rest: how risky is this,
overall. ``composite_risk`` reads ``typology_support``, which is why the two cannot share a
layer, discovered while writing these rules, and the reason the layer model runs to 5.

**Why mutual exclusivity is engineered in, rather than resolved afterwards.** Every graded
predicate here is single-valued, so two rules concluding different values for the same case
would produce an incompatibility, which the conflict detector would then read as genuine
disagreement in the knowledge base and possibly abstain over. That would be a bug dressed up
as epistemic humility. So the premises partition the input space exactly: where one rule
takes ``geographic_risk(high)``, its sibling takes ``In("low", "elevated", "unknown")``,
covering the remainder rather than relying on rule ordering. This is why the indicator layer
asserts a definite value for every graded indicator, including the unremarkable ones.
"""

from __future__ import annotations

from triagex.dsl import Conclude, Has, In, Missing, Provenance, Rule, RuleSet, Var

A = Var("a")

_MLR_CDD = "MLR 2017 Part 3 (customer due diligence); JMLSG Part I"
_FATF_RBA = "FATF Recommendation 1 and its Interpretive Note (risk-based approach)"
_SCOPE = "Project scope decision (docs/02-knowledge-acquisition.md)"


def _a(
    id: str,  # noqa: A002
    *,
    when: tuple[object, ...],
    then: Conclude,
    source: str,
    rationale: str,
    layer: int = 3,
    provenance: Provenance = Provenance.RECONSTRUCTED,
    strength: float = 1.0,
    priority: int = 0) -> Rule:
    return Rule(
        id=id,
        layer=layer,
        when=when,  # type: ignore[arg-type]
        then=then,
        source=source,
        provenance=provenance,
        rationale=rationale,
        strength=strength,
        priority=priority)


# --------------------------------------------------------------------------------------
# Evidence sufficiency  (layer 3)
# --------------------------------------------------------------------------------------

_EVIDENCE = (
    _a(
        "POS-EVID-01",
        when=(Has("kyc_currency", A, "expired"),),
        then=Conclude("evidence_sufficiency", A, "insufficient"),
        source=_MLR_CDD,
        provenance=Provenance.STATUTORY,
        rationale=(
            "Due diligence has lapsed, so nothing about this customer can be relied on until "
            "it is refreshed. No amount of transaction analysis substitutes for knowing who "
            "the customer is."
        )),
    _a(
        "POS-EVID-02",
        when=(
            Has("kyc_currency", A, In("current", "stale")),
            Has("documentation_gap", A, In("source_of_funds", "purpose", "identity"))),
        then=Conclude("evidence_sufficiency", A, "partial"),
        source=_MLR_CDD,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "A specific, nameable piece of evidence is missing. This is the state that makes "
            "asking the customer worthwhile rather than escalating on incomplete information."
        )),
    _a(
        "POS-EVID-03",
        when=(
            Has("kyc_currency", A, "current"),
            Missing("documentation_gap", A)),
        then=Conclude("evidence_sufficiency", A, "sufficient"),
        source=_MLR_CDD,
        provenance=Provenance.GUIDANCE,
        rationale="Due diligence is current and no documentary gap is outstanding."),
    _a(
        "POS-EVID-04",
        when=(
            Has("kyc_currency", A, "stale"),
            Missing("documentation_gap", A)),
        then=Conclude("evidence_sufficiency", A, "partial"),
        source=_MLR_CDD,
        provenance=Provenance.GUIDANCE,
        rationale="Due diligence is incomplete even though no specific document is missing."))

# --------------------------------------------------------------------------------------
# Scope  (layer 3)
# --------------------------------------------------------------------------------------

_SCOPE_RULES = (
    _a(
        "POS-SCOPE-01",
        when=(Has("unsupported_instrument", A, "present"),),
        then=Conclude("scope_state", A, "out_of_scope"),
        source=_SCOPE,
        rationale=(
            "An instrument appears that this knowledge base has no model of. Producing a "
            "disposition anyway would mean deciding a case on the part of it that is "
            "understood."
        )),
    _a(
        "POS-SCOPE-02",
        when=(Has("unsupported_structure", A, "present"),),
        then=Conclude("scope_state", A, "out_of_scope"),
        source=_SCOPE,
        rationale="The customer structure requires beneficial-ownership reasoning this system lacks."),
    _a(
        "POS-SCOPE-03",
        when=(
            # The binding premise comes first: negation as failure over an unbound subject
            # is not well defined, and the matcher refuses it rather than guessing.
            Has("geographic_risk", A, "unknown"),
            Missing("unsupported_instrument", A),
            Missing("unsupported_structure", A)),
        then=Conclude("scope_state", A, "boundary"),
        source=_FATF_RBA,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "The case is assessable, but a counterparty jurisdiction could not be resolved. "
            "Boundary cases proceed with the caveat recorded rather than being refused "
            "outright - otherwise one unrecognised country code would disable the system."
        )),
    _a(
        "POS-SCOPE-04",
        when=(
            Has("geographic_risk", A, In("low", "elevated", "high")),
            Missing("unsupported_instrument", A),
            Missing("unsupported_structure", A)),
        then=Conclude("scope_state", A, "in_scope"),
        source=_SCOPE,
        rationale="Every element of this case is something the knowledge base models."),
    _a(
        "POS-REASON-01",
        when=(Has("unsupported_instrument", A, "present"),),
        then=Conclude("out_of_scope_reason", A, "cryptoasset transfer: requires chain analytics"),
        source=_SCOPE,
        rationale=(
            "Names the specific gap. An abstention that does not say what it could not handle "
            "is useless to the analyst who receives it."
        )),
    _a(
        "POS-REASON-02",
        when=(Has("unsupported_structure", A, "present"),),
        then=Conclude(
            "out_of_scope_reason", A, "trust structure: requires beneficial-ownership tracing"
        ),
        source=_SCOPE,
        rationale="Names the specific gap for a trust customer."))

# --------------------------------------------------------------------------------------
# Mandatory escalation  (layer 3)
# --------------------------------------------------------------------------------------

_MANDATORY = (
    _a(
        "POS-MAND-01",
        when=(Has("designation_signal", A, "confirmed"),),
        then=Conclude("mandatory_escalation", A, "present"),
        source="Sanctions and Anti-Money Laundering Act 2018; OFSI reporting obligations",
        provenance=Provenance.STATUTORY,
        rationale=(
            "A confirmed designation match must reach a human with reporting authority. This "
            "is not a risk judgement and is not subject to one."
        )),
    _a(
        "POS-MAND-02",
        when=(Has("designation_signal", A, "possible"),),
        then=Conclude("mandatory_escalation", A, "present"),
        source="OFSI guidance on screening and possible matches",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "A possible match is for a human to adjudicate. Automated dismissal of a possible "
            "designation match is precisely the decision a machine should not be making."
        )),
    _a(
        "POS-MAND-03",
        when=(Has("designation_signal", A, "none"),),
        then=Conclude("mandatory_escalation", A, "absent"),
        source="OFSI guidance on screening",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Screening ran and returned no match. Note this requires a positive 'none': if "
            "screening never ran there is no designation fact, no mandatory_escalation fact, "
            "and the meta-layer records a missing premise instead."
        )))

# --------------------------------------------------------------------------------------
# Composite risk  (layer 4)
# --------------------------------------------------------------------------------------

_RISK = (
    _a(
        "POS-RISK-01",
        layer=4,
        when=(
            Has("typology_support", A, "strong"),
            Has("geographic_risk", A, "high")),
        then=Conclude("composite_risk", A, "severe"),
        source=_FATF_RBA,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Strong typology support with exposure to a jurisdiction subject to a call for "
            "countermeasures is the highest posture this system assigns."
        )),
    _a(
        "POS-RISK-02",
        layer=4,
        when=(
            Has("typology_support", A, "strong"),
            Has("geographic_risk", A, In("low", "elevated", "unknown"))),
        then=Conclude("composite_risk", A, "high"),
        source=_FATF_RBA,
        provenance=Provenance.GUIDANCE,
        rationale="Strong typology support without the aggravating geography."),
    _a(
        "POS-RISK-03",
        layer=4,
        when=(
            Has("typology_support", A, "moderate"),
            Has("turnover_deviation", A, "far_above")),
        then=Conclude("composite_risk", A, "high"),
        source=_FATF_RBA,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Moderate support becomes a high posture when the value involved is far outside "
            "anything the customer's profile explains."
        )),
    _a(
        "POS-RISK-04",
        layer=4,
        when=(
            Has("typology_support", A, "moderate"),
            Has("turnover_deviation", A, In("within", "above"))),
        then=Conclude("composite_risk", A, "moderate"),
        source=_FATF_RBA,
        provenance=Provenance.GUIDANCE,
        rationale="Moderate typology support at a value consistent with the profile."),
    _a(
        "POS-RISK-05",
        layer=4,
        when=(Has("typology_support", A, "weak"),),
        then=Conclude("composite_risk", A, "moderate"),
        source=_FATF_RBA,
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Weak support still warrants watching. Mapping weak support to a moderate posture "
            "is what makes the 'monitor' disposition reachable at all - without it, anything "
            "not worth escalating would be cleared outright."
        )),
    _a(
        "POS-RISK-06",
        layer=4,
        when=(Has("typology_support", A, "none"),),
        then=Conclude("composite_risk", A, "low"),
        source=_FATF_RBA,
        provenance=Provenance.GUIDANCE,
        rationale="No typology reaches the noise floor; nothing here needs explaining."))


ASSESSMENT_RULES = RuleSet((*_EVIDENCE, *_SCOPE_RULES, *_MANDATORY), name="assessment")
POSTURE_RULES = RuleSet(_RISK, name="posture")
