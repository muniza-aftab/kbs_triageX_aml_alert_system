"""Layer 2, typology rules.

Where indicators observe, typologies interpret. Each rule proposes that a combination of
observations is consistent with a recognised laundering pattern, and attaches a certainty
factor to that hypothesis.

Three properties of this layer are deliberate:

**Hypotheses, never intent.** A rule concludes ``typology(structuring)``, meaning "this
behaviour matches the structuring pattern". It never concludes that anyone intended to
structure. Intent is not observable from transaction data, and a system claiming to detect it
would be lying about what it can see.

**Several typologies can hold at once.** ``typology`` is multi-valued, because a case really
can be consistent with both structuring and a mule account. Forcing a single label would
discard information the analyst needs.

**Exculpatory rules exist.** Several rules carry *negative* strength, arguing against a
hypothesis. A system that can only accumulate suspicion will convict every customer
eventually, given enough rules. Negative evidence is also what generates genuine
irreconcilable conflict, which is the most interesting reason this system abstains.
"""

from __future__ import annotations

from triagex.dsl import Conclude, Has, In, Provenance, Rule, RuleSet, Var

A = Var("a")

_FATF_STRUCT = "FATF structuring/smurfing typology"
_FATF_LAYER = "FATF layering and placement typology material"
_JMLSG = "JMLSG Guidance Part I (risk factors)"
_WOLFSBERG = "Wolfsberg Group, Statement on Effective Monitoring for Suspicious Activity (2024)"
_MULE = "UK Finance / JMLSG money-mule typology material"


def _t(
    id: str,  # noqa: A002
    *,
    when: tuple[object, ...],
    typology: str,
    strength: float,
    source: str,
    rationale: str,
    provenance: Provenance = Provenance.RECONSTRUCTED,
    priority: int = 0) -> Rule:
    return Rule(
        id=id,
        layer=2,
        when=when,  # type: ignore[arg-type]
        then=Conclude("typology", A, typology),
        strength=strength,
        source=source,
        provenance=provenance,
        rationale=rationale,
        priority=priority)


# --------------------------------------------------------------------------------------
# Structuring
# --------------------------------------------------------------------------------------

_STRUCTURING = (
    _t(
        "TYP-STRUCT-01",
        when=(
            Has("deposit_frequency", A, In("elevated", "extreme")),
            Has("threshold_proximity", A, "high")),
        typology="structuring",
        strength=0.70,
        source=_FATF_STRUCT,
        rationale=(
            "Repeated credits clustered just below the review threshold are the core "
            "structuring signature: the pattern only makes sense if the threshold is known."
        )),
    _t(
        "TYP-STRUCT-02",
        when=(
            Has("deposit_frequency", A, In("elevated", "extreme")),
            Has("threshold_proximity", A, "high"),
            Has("aggregation_gap", A, "present")),
        typology="structuring",
        strength=0.55,
        source=_FATF_STRUCT,
        rationale=(
            "A large total assembled from much smaller parts, each just under the threshold, "
            "strengthens the reading considerably: the splitting achieved something."
        )),
    _t(
        "TYP-STRUCT-03",
        when=(
            Has("threshold_proximity", A, "high"),
            Has("channel_dispersion", A, "present")),
        typology="structuring",
        strength=0.40,
        source=_FATF_STRUCT,
        rationale=(
            "Spreading threshold-hugging credits across channels suggests avoiding any one "
            "channel's view of the whole."
        )),
    _t(
        "TYP-STRUCT-NEG-01",
        when=(
            Has("deposit_frequency", A, "normal"),
            Has("turnover_deviation", A, "within")),
        typology="structuring",
        strength=-0.60,
        source=_FATF_STRUCT,
        rationale=(
            "Ordinary credit volume, in line with the expected profile, argues against "
            "splitting. Without rules like this the system could only ever grow more "
            "suspicious."
        )))

# --------------------------------------------------------------------------------------
# Rapid pass-through and round-tripping
# --------------------------------------------------------------------------------------

_FLOW = (
    _t(
        "TYP-PASS-01",
        when=(
            Has("velocity", A, "extreme"),
            Has("balance_retention", A, "low")),
        typology="rapid_pass_through",
        strength=0.75,
        source=_FATF_LAYER,
        rationale=(
            "Funds arrived and left almost immediately, leaving nothing behind. The account "
            "is functioning as a conduit rather than as a place to keep money."
        )),
    _t(
        "TYP-PASS-02",
        when=(
            Has("velocity", A, "high"),
            Has("balance_retention", A, "low")),
        typology="rapid_pass_through",
        strength=0.50,
        source=_FATF_LAYER,
        rationale="Most funds moved on quickly and little was retained."),
    _t(
        "TYP-PASS-NEG-01",
        when=(Has("balance_retention", A, "normal"),),
        typology="rapid_pass_through",
        strength=-0.50,
        source=_FATF_LAYER,
        rationale=(
            "A meaningful balance remained, which is inconsistent with using the account "
            "purely as a conduit."
        )),
    _t(
        "TYP-ROUND-01",
        when=(Has("round_trip_signature", A, "present"),),
        typology="round_tripping",
        strength=0.70,
        source="FATF round-tripping and trade typology material",
        rationale=(
            "Value left and returned through intermediaries. Circular flow creates the "
            "appearance of commercial activity without its substance."
        )),
    _t(
        "TYP-ROUND-02",
        when=(
            Has("round_trip_signature", A, "present"),
            Has("geographic_risk", A, In("elevated", "high"))),
        typology="round_tripping",
        strength=0.40,
        source="FATF round-tripping typology material",
        rationale="The circular route passes through a higher-risk jurisdiction."))

# --------------------------------------------------------------------------------------
# Mule accounts and third-party funding
# --------------------------------------------------------------------------------------

_NETWORK = (
    _t(
        "TYP-MULE-01",
        when=(
            Has("counterparty_concentration", A, "hub"),
            Has("account_immaturity", A, "true")),
        typology="mule_account",
        strength=0.75,
        source=_MULE,
        rationale=(
            "A recently opened account collecting payments from many unrelated parties is "
            "the standard mule shape: new, because previous accounts get closed."
        )),
    _t(
        "TYP-MULE-02",
        when=(
            Has("counterparty_concentration", A, In("concentrated", "hub")),
            Has("third_party_pattern", A, "present")),
        typology="mule_account",
        strength=0.50,
        source=_MULE,
        rationale="Multiple undeclared payers are funding the account."),
    _t(
        "TYP-MULE-03",
        when=(
            Has("counterparty_concentration", A, In("concentrated", "hub")),
            Has("velocity", A, In("high", "extreme")),
            Has("balance_retention", A, "low")),
        typology="mule_account",
        strength=0.45,
        source=_MULE,
        rationale=(
            "Money from many payers is passed straight on, which is collection and "
            "forwarding rather than personal use."
        )),
    _t(
        "TYP-MULE-NEG-01",
        when=(
            Has("account_immaturity", A, "false"),
            Has("counterparty_concentration", A, "diffuse")),
        typology="mule_account",
        strength=-0.55,
        source=_MULE,
        rationale=(
            "An established account with few payers does not fit the mule pattern, whatever "
            "else may be true of the case."
        )),
    _t(
        "TYP-THIRD-01",
        when=(
            Has("third_party_pattern", A, "present"),
            Has("documentation_gap", A, "source_of_funds")),
        typology="third_party_funding",
        strength=0.60,
        source="MLR 2017 Part 3; JMLSG Part I on source of funds",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Funds are arriving from parties the customer has not accounted for, and no "
            "source-of-funds evidence is held to explain them."
        )),
    _t(
        "TYP-THIRD-02",
        when=(
            Has("third_party_pattern", A, "present"),
            Has("threshold_proximity", A, In("moderate", "high"))),
        typology="third_party_funding",
        strength=0.35,
        source=_JMLSG,
        rationale="Third-party credits are also sized to stay under review thresholds."))

# --------------------------------------------------------------------------------------
# Business and profile typologies
# --------------------------------------------------------------------------------------

_BUSINESS = (
    _t(
        "TYP-CASH-01",
        when=(
            Has("customer_segment", A, In("business", "cash_intensive")),
            Has("cash_ratio_deviation", A, "above"),
            Has("turnover_deviation", A, "far_above")),
        typology="cash_intensive_layering",
        strength=0.65,
        source="FATF cash-intensive business typology material",
        rationale=(
            "Cash exceeds what this customer type should generate, and turnover far exceeds "
            "the declared profile. The expectation is inherited from the customer frame, so "
            "a genuinely cash-heavy trade is not penalised for being one."
        )),
    _t(
        "TYP-CASH-02",
        when=(
            Has("customer_segment", A, In("business", "cash_intensive")),
            Has("cash_ratio_deviation", A, "above"),
            Has("turnover_deviation", A, "above")),
        typology="cash_intensive_layering",
        strength=0.40,
        source="FATF cash-intensive business typology material",
        rationale="Cash usage and turnover both run above the expected profile."),
    _t(
        "TYP-CASH-NEG-01",
        when=(
            Has("customer_segment", A, In("business", "cash_intensive")),
            Has("cash_ratio_deviation", A, "within")),
        typology="cash_intensive_layering",
        strength=-0.60,
        source="FATF cash-intensive business typology material",
        rationale="Cash usage is consistent with the customer's expected pattern."),
    _t(
        "TYP-DORM-01",
        when=(
            Has("dormancy_break", A, "true"),
            Has("turnover_deviation", A, In("above", "far_above"))),
        typology="dormant_reactivation",
        strength=0.65,
        source=_JMLSG,
        rationale=(
            "A long-dormant account has resumed activity at a level well above its profile. "
            "An account with a quiet history is attractive precisely because it looks clean."
        )),
    _t(
        "TYP-DORM-02",
        when=(
            Has("dormancy_break", A, "true"),
            Has("counterparty_concentration", A, In("concentrated", "hub"))),
        typology="dormant_reactivation",
        strength=0.40,
        source=_JMLSG,
        rationale="Reactivation coincides with an influx of payers the account never had."))

# --------------------------------------------------------------------------------------
# Status-driven typologies
# --------------------------------------------------------------------------------------

_STATUS = (
    _t(
        "TYP-PEP-01",
        when=(
            Has("pep_exposure", A, In("foreign", "associate")),
            Has("turnover_deviation", A, "far_above")),
        typology="pep_misuse",
        strength=0.60,
        source="MLR 2017 reg. 35; FATF Recommendation 12",
        provenance=Provenance.STATUTORY,
        rationale=(
            "Political exposure combined with value movement well beyond the declared "
            "profile. Note that PEP status alone is a reason for enhanced diligence, not a "
            "reason for suspicion, which is why this rule needs the second premise."
        )),
    _t(
        "TYP-PEP-02",
        when=(
            Has("pep_exposure", A, "foreign"),
            Has("geographic_risk", A, In("elevated", "high"))),
        typology="pep_misuse",
        strength=0.45,
        source="MLR 2017 reg. 35; FATF Recommendation 12",
        provenance=Provenance.STATUTORY,
        rationale="A foreign PEP is transacting with a higher-risk jurisdiction."),
    _t(
        "TYP-SANC-01",
        when=(Has("designation_signal", A, "confirmed"),),
        typology="sanctions_evasion",
        strength=0.95,
        source="Sanctions and Anti-Money Laundering Act 2018; OFSI guidance",
        provenance=Provenance.STATUTORY,
        rationale=(
            "A confirmed designation match. The certainty is high but deliberately not 1.0 - "
            "screening produces false matches, and the disposition layer escalates this to a "
            "human regardless rather than acting on it."
        )),
    _t(
        "TYP-SANC-02",
        when=(
            Has("designation_signal", A, "possible"),
            Has("geographic_risk", A, In("elevated", "high"))),
        typology="sanctions_evasion",
        strength=0.55,
        source="OFSI guidance on possible matches",
        provenance=Provenance.GUIDANCE,
        rationale="A possible designation match alongside higher-risk geography."),
    _t(
        "TYP-MEDIA-01",
        when=(
            Has("adverse_media_signal", A, "verified"),
            Has("turnover_deviation", A, In("above", "far_above"))),
        typology="third_party_funding",
        strength=0.30,
        source="FCA Financial Crime Guide (April 2025)",
        provenance=Provenance.GUIDANCE,
        rationale=(
            "Corroborated adverse media alongside unexplained volume. Unverified media "
            "deliberately does not feed any typology: acting on unchecked reporting about a "
            "named person is its own harm."
        )),
    _t(
        "TYP-GAMB-01",
        when=(
            Has("gambling_cycling_pattern", A, "present"),
            Has("velocity", A, In("high", "extreme"))),
        typology="gambling_cycling",
        strength=0.55,
        source="UK Gambling Commission / JMLSG sectoral guidance",
        rationale=(
            "Funds moving rapidly through a gambling operator can manufacture a plausible "
            "source for money that already existed."
        )),
    _t(
        "TYP-GAMB-02",
        when=(
            Has("gambling_cycling_pattern", A, "present"),
            Has("turnover_deviation", A, "far_above")),
        typology="gambling_cycling",
        strength=0.45,
        source="UK Gambling Commission / JMLSG sectoral guidance",
        rationale="Gambling flows far exceed the customer's declared means."))


TYPOLOGY_RULES = RuleSet(
    (*_STRUCTURING, *_FLOW, *_NETWORK, *_BUSINESS, *_STATUS),
    name="typologies")
