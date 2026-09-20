"""Layer 1, indicator rules.

Indicators turn measurements into named observations. They carry no opinion about what the
behaviour means, which is what allows a single indicator to support several different
typologies: ``threshold_proximity`` contributes to structuring *and* to third-party funding,
and it would not if it had "structuring" baked into its name.

Every rule here reads only Layer 0 measurements, enforced by the premise policy in
``dsl.PERMITTED_PREMISE_LAYERS``.

Provenance note: the *shape* of each indicator comes from published typology and guidance
material, but the numeric cut-offs were set for this project (see ``kb/reference.py``). Those
rules are
tagged ``reconstructed`` accordingly, and honesty about that split matters more than the
appearance of authority.
"""

from __future__ import annotations

from triagex.dsl import Cmp, Conclude, Has, In, Provenance, Ratio, Rule, RuleSet, Var
from triagex.kb.reference import THRESHOLDS as T

A = Var("a")

_JMLSG = "JMLSG Guidance Part I (risk factors); FATF typology material"
_FATF_STRUCT = "FATF structuring/smurfing typology"
_WOLFSBERG = "Wolfsberg Group, Statement on Effective Monitoring for Suspicious Activity (2024)"


def _r(
    id: str,  # noqa: A002 - mirrors the Rule field name deliberately
    *,
    when: tuple[object, ...],
    then: Conclude,
    source: str,
    rationale: str,
    provenance: Provenance = Provenance.RECONSTRUCTED,
    strength: float = 1.0,
    priority: int = 0) -> Rule:
    return Rule(
        id=id,
        layer=1,
        when=when,  # type: ignore[arg-type]
        then=then,
        source=source,
        provenance=provenance,
        rationale=rationale,
        strength=strength,
        priority=priority)


# --------------------------------------------------------------------------------------
# Cash and deposit patterning
# --------------------------------------------------------------------------------------

_CASH = (
    _r(
        "IND-FREQ-01",
        when=(
            Cmp("credit_count", A, ">=", T.frequency_elevated),
            Cmp("credit_count", A, "<", T.frequency_extreme)),
        then=Conclude("deposit_frequency", A, "elevated"),
        source=_FATF_STRUCT,
        rationale=(
            f"{T.frequency_elevated} or more credits within the review window is more "
            f"activity than an ordinary personal account generates."
        )),
    _r(
        "IND-FREQ-02",
        when=(Cmp("credit_count", A, ">=", T.frequency_extreme),),
        then=Conclude("deposit_frequency", A, "extreme"),
        source=_FATF_STRUCT,
        rationale=(
            f"{T.frequency_extreme} or more credits in the window is a rate that needs a "
            f"positive explanation rather than the benefit of the doubt."
        )),
    _r(
        "IND-FREQ-03",
        when=(Cmp("credit_count", A, "<", T.frequency_elevated),),
        then=Conclude("deposit_frequency", A, "normal"),
        source=_FATF_STRUCT,
        rationale="Credit volume is unremarkable for the window."),
    _r(
        "IND-PROX-01",
        when=(
            Cmp("max_single_credit", A, ">=", T.internal_review_threshold * T.proximity_band_lower),
            Cmp("max_single_credit", A, "<", T.internal_review_threshold)),
        then=Conclude("threshold_proximity", A, "high"),
        source=_FATF_STRUCT,
        rationale=(
            f"The largest credit sits between {T.proximity_band_lower:.0%} and 100% of the "
            f"GBP {T.internal_review_threshold: .0f} review threshold. Amounts cluster just "
            f"under a threshold when the threshold is known and being avoided."
        )),
    _r(
        "IND-PROX-02",
        when=(
            Cmp("max_single_credit", A, ">=", T.internal_review_threshold * 0.6),
            Cmp("max_single_credit", A, "<", T.internal_review_threshold * T.proximity_band_lower)),
        then=Conclude("threshold_proximity", A, "moderate"),
        source=_FATF_STRUCT,
        rationale="Credits approach the review threshold without hugging it."),
    _r(
        "IND-PROX-03",
        when=(Cmp("max_single_credit", A, "<", T.internal_review_threshold * 0.6),),
        then=Conclude("threshold_proximity", A, "none"),
        source=_FATF_STRUCT,
        rationale=(
            "Credits are nowhere near the review threshold, so threshold avoidance is not a "
            "plausible reading of their size."
        )),
    _r(
        "IND-AGG-01",
        when=(
            Ratio("aggregate_credits", "max_single_credit", A, ">=", T.aggregation_gap_multiple),),
        then=Conclude("aggregation_gap", A, "present"),
        source=_FATF_STRUCT,
        rationale=(
            f"Total credited value is at least {T.aggregation_gap_multiple:.0f}x the largest "
            f"single credit, so a substantial sum arrived in pieces rather than at once."
        )),
    _r(
        "IND-CHAN-01",
        when=(Cmp("distinct_channels", A, ">=", 3),),
        then=Conclude("channel_dispersion", A, "present"),
        source=_JMLSG,
        rationale=(
            "Credits spread across three or more channels is consistent with an attempt to "
            "avoid any single channel's monitoring picking up the whole picture."
        )))

# --------------------------------------------------------------------------------------
# Velocity and retention
# --------------------------------------------------------------------------------------

_FLOW = (
    _r(
        "IND-VEL-01",
        when=(Cmp("outflow_within_window_ratio", A, ">=", 0.90),),
        then=Conclude("velocity", A, "extreme"),
        source=_JMLSG,
        rationale=(
            f"Nine tenths or more of what arrived left again within "
            f"{T.passthrough_hours} hours. The account is being used as a conduit, not held."
        )),
    _r(
        "IND-VEL-02",
        when=(
            Cmp("outflow_within_window_ratio", A, ">=", 0.70),
            Cmp("outflow_within_window_ratio", A, "<", 0.90)),
        then=Conclude("velocity", A, "high"),
        source=_JMLSG,
        rationale="Most of the inflow left again very quickly."),
    _r(
        "IND-VEL-03",
        when=(Cmp("outflow_within_window_ratio", A, "<", 0.70),),
        then=Conclude("velocity", A, "normal"),
        source=_JMLSG,
        rationale="A normal proportion of funds remained in the account."),
    _r(
        "IND-RET-01",
        when=(Cmp("closing_to_inflow_ratio", A, "<", T.retention_ratio_low),),
        then=Conclude("balance_retention", A, "low"),
        source=_JMLSG,
        rationale=(
            f"The closing balance is under {T.retention_ratio_low:.0%} of everything that "
            f"came in, so the money did not stay."
        )),
    _r(
        "IND-RET-02",
        when=(Cmp("closing_to_inflow_ratio", A, ">=", T.retention_ratio_low),),
        then=Conclude("balance_retention", A, "normal"),
        source=_JMLSG,
        rationale="A meaningful share of the inflow remained in the account."))

# --------------------------------------------------------------------------------------
# Turnover and profile deviation
# --------------------------------------------------------------------------------------

_PROFILE = (
    _r(
        "IND-TURN-01",
        when=(
            Ratio(
                "observed_monthly_turnover",
                "expected_monthly_turnover",
                A,
                ">=",
                T.turnover_far_above_multiple),),
        then=Conclude("turnover_deviation", A, "far_above"),
        source=_JMLSG,
        rationale=(
            f"Observed turnover is at least {T.turnover_far_above_multiple:.0f}x what the "
            f"customer's profile predicts. Activity has outgrown the account's stated purpose."
        )),
    _r(
        "IND-TURN-02",
        when=(
            Ratio(
                "observed_monthly_turnover",
                "expected_monthly_turnover",
                A,
                ">=",
                T.turnover_above_multiple),
            Ratio(
                "observed_monthly_turnover",
                "expected_monthly_turnover",
                A,
                "<",
                T.turnover_far_above_multiple)),
        then=Conclude("turnover_deviation", A, "above"),
        source=_JMLSG,
        rationale="Turnover materially exceeds the expected profile without dwarfing it."),
    _r(
        "IND-TURN-03",
        when=(
            Ratio(
                "observed_monthly_turnover",
                "expected_monthly_turnover",
                A,
                "<",
                T.turnover_above_multiple),),
        then=Conclude("turnover_deviation", A, "within"),
        source=_JMLSG,
        rationale="Turnover is consistent with the expected profile."),
    _r(
        "IND-CASH-RATIO-01",
        when=(
            Ratio("cash_ratio", "expected_cash_ratio", A, ">=", 1.0 + T.cash_ratio_tolerance),),
        then=Conclude("cash_ratio_deviation", A, "above"),
        source=_JMLSG,
        rationale=(
            "Cash makes up more of the credits than this customer type is expected to "
            "generate. Note that the expectation itself is inherited from the customer "
            "frame, so a cash-intensive business is not penalised for being cash-intensive."
        )),
    _r(
        "IND-CASH-RATIO-02",
        when=(
            Ratio("cash_ratio", "expected_cash_ratio", A, "<", 1.0 + T.cash_ratio_tolerance),),
        then=Conclude("cash_ratio_deviation", A, "within"),
        source=_JMLSG,
        rationale="Cash usage is in line with the expectation for this customer type."))

# --------------------------------------------------------------------------------------
# Account lifecycle
# --------------------------------------------------------------------------------------

_LIFECYCLE = (
    _r(
        "IND-ACCT-01",
        when=(Cmp("account_age_days", A, "<", T.immaturity_days),),
        then=Conclude("account_immaturity", A, "true"),
        source=_JMLSG,
        rationale=(
            f"The account is under {T.immaturity_days} days old. There is no established "
            f"pattern of behaviour to compare this activity against."
        )),
    _r(
        "IND-ACCT-02",
        when=(Cmp("account_age_days", A, ">=", T.immaturity_days),),
        then=Conclude("account_immaturity", A, "false"),
        source=_JMLSG,
        rationale="The account has enough history to establish a baseline."),
    _r(
        "IND-DORM-01",
        when=(Cmp("days_since_prior_activity", A, ">=", T.dormancy_days),),
        then=Conclude("dormancy_break", A, "true"),
        source=_JMLSG,
        rationale=(
            f"The account was inactive for at least {T.dormancy_days} days before this "
            f"activity. Sudden reactivation is a recognised way to use an account whose "
            f"history looks harmless."
        )),
    _r(
        "IND-DORM-02",
        when=(Cmp("days_since_prior_activity", A, "<", T.dormancy_days),),
        then=Conclude("dormancy_break", A, "false"),
        source=_JMLSG,
        rationale="Activity is continuous with the account's recent use."))

# --------------------------------------------------------------------------------------
# Counterparties and geography
# --------------------------------------------------------------------------------------

_COUNTERPARTY = (
    _r(
        "IND-CONC-01",
        when=(Cmp("payer_hub_degree", A, ">=", T.hub_degree),),
        then=Conclude("counterparty_concentration", A, "hub"),
        source=_WOLFSBERG,
        rationale=(
            f"At least {T.hub_degree} distinct parties paid into this account. A collection "
            f"point with many unrelated payers is the classic mule-network shape."
        )),
    _r(
        "IND-CONC-02",
        when=(
            Cmp("payer_hub_degree", A, ">=", T.concentration_degree),
            Cmp("payer_hub_degree", A, "<", T.hub_degree)),
        then=Conclude("counterparty_concentration", A, "concentrated"),
        source=_WOLFSBERG,
        rationale="More distinct payers than an ordinary account attracts, short of a hub."),
    _r(
        "IND-CONC-03",
        when=(Cmp("payer_hub_degree", A, "<", T.concentration_degree),),
        then=Conclude("counterparty_concentration", A, "diffuse"),
        source=_WOLFSBERG,
        rationale="Few enough distinct payers to be consistent with ordinary personal use."),
    _r(
        "IND-THIRD-01",
        when=(Cmp("undeclared_payer_count", A, ">=", 2),),
        then=Conclude("third_party_pattern", A, "present"),
        source=_JMLSG,
        rationale=(
            "Two or more payers have no declared relationship to the customer. Funds "
            "arriving from parties the customer has not accounted for need an explanation."
        )),
    _r(
        "IND-THIRD-02",
        when=(Cmp("undeclared_payer_count", A, "<", 2),),
        then=Conclude("third_party_pattern", A, "absent"),
        source=_JMLSG,
        rationale="Payers are accounted for by the declared relationships."),
    _r(
        "IND-GEO-01",
        when=(Has("worst_fatf_status", A, "black_list"),),
        then=Conclude("geographic_risk", A, "high"),
        source="FATF public statements on high-risk jurisdictions",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "A counterparty sits in a jurisdiction subject to a call for countermeasures. "
            "This is a listed status, not a judgement made by this system."
        )),
    _r(
        "IND-GEO-02",
        when=(Has("worst_fatf_status", A, "grey_list"),),
        then=Conclude("geographic_risk", A, "elevated"),
        source="FATF jurisdictions under increased monitoring",
        provenance=Provenance.GUIDANCE,
        rationale="A counterparty sits in a jurisdiction under increased monitoring."),
    _r(
        "IND-GEO-03",
        when=(Has("worst_fatf_status", A, "unknown"),),
        then=Conclude("geographic_risk", A, "unknown"),
        source="FATF Recommendation 1 (risk-based approach)",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "A counterparty jurisdiction could not be resolved. Unresolvable geography is "
            "an absence of knowledge, and is deliberately not treated as low risk."
        )),
    _r(
        "IND-GEO-04",
        when=(Has("worst_fatf_status", A, "compliant"),),
        then=Conclude("geographic_risk", A, "low"),
        source="FATF Recommendation 1 (risk-based approach)",
        provenance=Provenance.GUIDANCE,
        rationale="All counterparty jurisdictions are compliant."),
    _r(
        "IND-LOOP-01",
        when=(Has("closed_value_loop", A, True),),
        then=Conclude("round_trip_signature", A, "present"),
        source="FATF trade and round-tripping typology material",
        rationale=(
            "Value left the account and returned to it through intermediaries. Circularity "
            "creates the appearance of trade without the substance of it."
        )),
    _r(
        "IND-GAMB-01",
        when=(Has("has_gambling_counterparty", A, True),),
        then=Conclude("gambling_cycling_pattern", A, "present"),
        source="UK Gambling Commission / JMLSG sectoral guidance",
        rationale=(
            "Funds moved through a gambling operator, which can be used to manufacture a "
            "plausible source for money that already existed."
        )))

# --------------------------------------------------------------------------------------
# Documentation, screening and scope observations
# --------------------------------------------------------------------------------------

_RECORDS = (
    _r(
        "IND-DOC-01",
        when=(Has("source_of_funds_evidence", A, In("absent", "unknown")),),
        then=Conclude("documentation_gap", A, "source_of_funds"),
        source="MLR 2017 Part 3 (customer due diligence)",
        provenance=Provenance.STATUTORY,
        rationale="No source-of-funds evidence is held for the customer."),
    _r(
        "IND-DOC-02",
        when=(Has("declared_purpose", A, In("absent", "unknown")),),
        then=Conclude("documentation_gap", A, "purpose"),
        source="MLR 2017 Part 3 (purpose and intended nature of the relationship)",
        provenance=Provenance.STATUTORY,
        rationale="The intended purpose of the relationship is not recorded."),
    _r(
        "IND-SEG-01",
        when=(Has("customer_type", A, Var("t")),),
        then=Conclude("customer_segment", A, Var("t")),
        source="MLR 2017 Part 3 (customer risk assessment)",
        provenance=Provenance.STATUTORY,
        rationale=(
            "Restates the customer type as an indicator. Typology rules read layer 1 only, "
            "so without this they cannot tell a takeaway from a salaried individual - and a "
            "typology about business cash handling should not fire on a retail customer."
        )),
    _r(
        "IND-KYC-01",
        when=(Has("kyc_status", A, "expired"),),
        then=Conclude("kyc_currency", A, "expired"),
        source="MLR 2017 reg. 27 (ongoing monitoring); JMLSG Part I",
        provenance=Provenance.STATUTORY,
        rationale="Customer due diligence has lapsed and needs refreshing."),
    _r(
        "IND-KYC-02",
        when=(Has("kyc_status", A, "partial"),),
        then=Conclude("kyc_currency", A, "stale"),
        source="MLR 2017 reg. 27 (ongoing monitoring)",
        provenance=Provenance.STATUTORY,
        rationale=(
            "Customer due diligence was started but never completed, so parts of the "
            "customer profile this assessment relies on are unverified."
        )),
    _r(
        "IND-KYC-03",
        when=(Has("kyc_status", A, "complete"),),
        then=Conclude("kyc_currency", A, "current"),
        source="MLR 2017 reg. 27 (ongoing monitoring)",
        provenance=Provenance.STATUTORY,
        rationale="Due diligence is complete and current."),
    _r(
        "IND-PEP-01",
        when=(Has("pep_status", A, "foreign"),),
        then=Conclude("pep_exposure", A, "foreign"),
        source="MLR 2017 reg. 35 (politically exposed persons)",
        provenance=Provenance.STATUTORY,
        rationale=(
            "The customer is a foreign politically exposed person, which requires enhanced "
            "due diligence as a matter of regulation rather than of suspicion."
        )),
    _r(
        "IND-PEP-04",
        when=(Has("pep_status", A, "domestic"),),
        then=Conclude("pep_exposure", A, "domestic"),
        source="MLR 2017 reg. 35 (politically exposed persons)",
        provenance=Provenance.STATUTORY,
        rationale=(
            "The customer is a domestic politically exposed person. Kept distinct from foreign "
            "exposure because the risk is not the same, and because the original rule mapped "
            "domestic PEPs to the foreign value - making the domestic value unreachable and "
            "quietly overstating the exposure of every domestic PEP."
        )),
    _r(
        "IND-PEP-02",
        when=(Has("pep_status", A, "associate"),),
        then=Conclude("pep_exposure", A, "associate"),
        source="MLR 2017 reg. 35 (family members and known close associates)",
        provenance=Provenance.STATUTORY,
        rationale="The customer is a family member or known close associate of a PEP."),
    _r(
        "IND-PEP-03",
        when=(Has("pep_status", A, "none"),),
        then=Conclude("pep_exposure", A, "none"),
        source="MLR 2017 reg. 35",
        provenance=Provenance.STATUTORY,
        rationale="No political exposure is recorded."),
    _r(
        "IND-MEDIA-01",
        when=(Has("adverse_media", A, "verified"),),
        then=Conclude("adverse_media_signal", A, "verified"),
        source="FCA Financial Crime Guide (April 2025), customer risk assessment",
        provenance=Provenance.GUIDANCE,
        rationale="Corroborated adverse media exists about the customer."),
    _r(
        "IND-MEDIA-02",
        when=(Has("adverse_media", A, "unverified"),),
        then=Conclude("adverse_media_signal", A, "unverified"),
        source="FCA Financial Crime Guide (April 2025)",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Adverse media exists but is uncorroborated. Recorded as unverified rather "
            "than promoted to a finding, because acting on unchecked reporting about a "
            "named individual is its own kind of harm."
        )),
    _r(
        "IND-MEDIA-03",
        when=(Has("adverse_media", A, "none"),),
        then=Conclude("adverse_media_signal", A, "none"),
        source="FCA Financial Crime Guide (April 2025)",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "An adverse media check was performed and found nothing. Distinct from no check "
            "having been run, which produces no signal at all."
        )),
    _r(
        "IND-DESIG-01",
        when=(Has("sanctions_signal", A, "confirmed"),),
        then=Conclude("designation_signal", A, "confirmed"),
        source="Sanctions and Anti-Money Laundering Act 2018; OFSI reporting obligations",
        provenance=Provenance.STATUTORY,
        rationale="A confirmed match against a designated party."),
    _r(
        "IND-DESIG-02",
        when=(Has("sanctions_signal", A, "possible"),),
        then=Conclude("designation_signal", A, "possible"),
        source="OFSI guidance on screening and possible matches",
        provenance=Provenance.GUIDANCE,
        rationale="A possible match requires human adjudication, not an automated verdict."),
    _r(
        "IND-DESIG-03",
        when=(Has("sanctions_signal", A, "none"),),
        then=Conclude("designation_signal", A, "none"),
        source="OFSI guidance on screening",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Screening was performed and returned no match. Note this fires only on an "
            "explicit 'none' - a case where screening never ran produces no designation "
            "fact at all, and the meta-layer treats that as a missing premise."
        )),
    _r(
        "IND-SCOPE-01",
        when=(Has("has_crypto_transaction", A, True),),
        then=Conclude("unsupported_instrument", A, "present"),
        source="Project scope decision (docs/02-knowledge-acquisition.md)",
        rationale=(
            "A cryptoasset transfer appears in the window. Assessing it would need chain "
            "analytics this knowledge base does not have."
        )),
    _r(
        "IND-SCOPE-02",
        when=(Has("customer_type", A, "trust"),),
        then=Conclude("unsupported_structure", A, "present"),
        source="Project scope decision (docs/02-knowledge-acquisition.md)",
        rationale=(
            "The customer is a trust. Beneficial-ownership chain reasoning is out of scope, "
            "so the knowledge base cannot assess this structure."
        )))


INDICATOR_RULES = RuleSet(
    (*_CASH, *_FLOW, *_PROFILE, *_LIFECYCLE, *_COUNTERPARTY, *_RECORDS),
    name="indicators")
