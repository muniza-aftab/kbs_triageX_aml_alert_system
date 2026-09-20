"""The predicate registry: every fact the system is allowed to state.

This is the executable form of the layer vocabularies in ``docs/03-knowledge-model.md``.
Registering predicates rather than letting rules invent them buys three things:

* **Typo safety.** A rule concluding ``depoist_frequency`` fails loudly at load time
  instead of silently never matching anything.
* **Layer enforcement.** Each predicate declares its layer, so the rule validator can
  reject any rule whose premises are not strictly below its conclusion. That is what
  prevents the knowledge base collapsing into a flat input-to-outcome lookup table.
* **Safe handling of the unknown.** Predicates marked ``mandatory`` may not be queried
  under negation-as-failure, so a missing sanctions check can never be mistaken for a
  clean one.

Layers: 0 measurements, 1 indicators, 2 typologies, 3 assessment, 4 posture, 5 disposition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

FactValue = str | bool | int | float


@dataclass(frozen=True, slots=True)
class PredicateSpec:
    """Declaration of a single predicate."""

    name: str
    layer: int
    values: frozenset[str] | None = None
    """Allowed values, or ``None`` for open numeric/boolean predicates."""

    multi_valued: bool = False
    """If true, several distinct values may hold simultaneously for one subject.

    ``typology`` is the motivating case: one alert can be consistent with structuring
    *and* with a mule account at the same time. For single-valued predicates, two
    different values asserted for the same subject are an incompatibility, which is
    what the conflict detector looks for.
    """

    mandatory: bool = False
    """If true, an unknown value forces abstention and negation-as-failure is refused."""

    description: str = ""

    def permits(self, value: FactValue) -> bool:
        if self.values is None:
            return isinstance(value, bool | int | float | str)
        return isinstance(value, str) and value in self.values


def _spec(
    name: str,
    layer: int,
    values: tuple[str, ...] | None = None,
    *,
    multi_valued: bool = False,
    mandatory: bool = False,
    description: str = "") -> PredicateSpec:
    return PredicateSpec(
        name=name,
        layer=layer,
        values=frozenset(values) if values is not None else None,
        multi_valued=multi_valued,
        mandatory=mandatory,
        description=description)


# --------------------------------------------------------------------------------------
# Layer 0, measurements
# --------------------------------------------------------------------------------------
# Computed from the case file by the loader: arithmetic, temporal and graph quantities.
# These carry no judgement whatsoever. They are the numbers an indicator rule compares
# against a threshold.

_L0: Final[tuple[PredicateSpec, ...]] = (
    _spec("credit_count", 0, description="Inbound transactions in the alert window"),
    _spec("max_single_credit", 0, description="Largest single inbound amount"),
    _spec("aggregate_credits", 0, description="Total inbound value over the window"),
    _spec("distinct_payers", 0, description="Distinct counterparties paying in"),
    _spec("distinct_channels", 0, description="Distinct channels used for credits"),
    _spec("account_age_days", 0),
    _spec("days_since_prior_activity", 0),
    _spec("outflow_within_window_ratio", 0, description="Share of inflow leaving within the pass-through window"),
    _spec("closing_to_inflow_ratio", 0, description="Closing balance as a share of total inflow"),
    _spec("cash_ratio", 0, description="Cash credits as a share of all credits"),
    _spec("observed_monthly_turnover", 0),
    _spec("expected_monthly_turnover", 0),
    _spec("expected_cash_ratio", 0),
    _spec("max_counterparty_secrecy", 0, description="Highest secrecy score among counterparties"),
    _spec("undeclared_payer_count", 0, description="Payers with no declared relationship"),
    _spec("worst_fatf_status", 0, ("compliant", "grey_list", "black_list", "unknown")),
    _spec("has_crypto_transaction", 0),
    _spec("has_gambling_counterparty", 0),
    _spec("closed_value_loop", 0, description="A value path returning to origin was found"),
    _spec("payer_hub_degree", 0, description="In-degree of the alerted account in the payer graph"),
    # Slot mirrors: asserted straight from the customer frame.
    _spec("customer_type", 0, ("retail", "business", "cash_intensive", "trust"), mandatory=True),
    _spec("kyc_status", 0, ("complete", "partial", "expired", "unknown"), mandatory=True),
    _spec(
        "sanctions_signal",
        0,
        ("none", "possible", "confirmed", "not_checked"),
        mandatory=True,
        description="'not_checked' is an unknown, not a clean result"),
    _spec("pep_status", 0, ("none", "domestic", "foreign", "associate")),
    _spec("source_of_funds_evidence", 0, ("present", "absent", "requested", "unknown")),
    _spec("adverse_media", 0, ("none", "unverified", "verified", "unknown")),
    _spec("declared_purpose", 0, ("consistent", "inconsistent", "absent", "unknown")))

# --------------------------------------------------------------------------------------
# Layer 1, indicators
# --------------------------------------------------------------------------------------
# Observations. An indicator says what is true of the behaviour, never what it means,
# which is why one indicator can support several different typologies.

_L1: Final[tuple[PredicateSpec, ...]] = (
    _spec("deposit_frequency", 1, ("normal", "elevated", "extreme")),
    _spec("threshold_proximity", 1, ("none", "moderate", "high")),
    _spec("channel_dispersion", 1, ("present",)),
    _spec("aggregation_gap", 1, ("present",)),
    _spec("velocity", 1, ("normal", "high", "extreme")),
    _spec("balance_retention", 1, ("low", "normal")),
    _spec("turnover_deviation", 1, ("within", "above", "far_above")),
    _spec("cash_ratio_deviation", 1, ("within", "above")),
    _spec("counterparty_concentration", 1, ("diffuse", "concentrated", "hub")),
    _spec("geographic_risk", 1, ("low", "elevated", "high", "unknown")),
    _spec("account_immaturity", 1, ("false", "true")),
    _spec("dormancy_break", 1, ("false", "true")),
    _spec("third_party_pattern", 1, ("absent", "present")),
    _spec("round_trip_signature", 1, ("present",)),
    _spec("gambling_cycling_pattern", 1, ("present",)),
    _spec("documentation_gap", 1, ("source_of_funds", "purpose"), multi_valued=True),
    _spec(
        "customer_segment",
        1,
        ("retail", "business", "cash_intensive", "trust"),
        description="Customer type as an indicator, so typology rules can scope themselves"),
    _spec("kyc_currency", 1, ("current", "stale", "expired")),
    _spec("pep_exposure", 1, ("none", "domestic", "foreign", "associate")),
    _spec("adverse_media_signal", 1, ("none", "unverified", "verified")),
    _spec(
        "designation_signal",
        1,
        ("none", "possible", "confirmed"),
        description=(
            "Sanctions screening outcome as an indicator. Note the absent fourth value: "
            "there is no indicator for 'not screened', because that is an absence of "
            "knowledge for the meta-layer to act on, not an observation about the case."
        )),
    # Scope observations. These are indicators like any other, "an instrument appears that
    # this system has no model of" is an observation about the case, not a judgement. Having
    # them at layer 1 is what lets scope_state be derived at layer 3 without a layer-4 rule
    # ever having to read raw data.
    _spec(
        "unsupported_instrument",
        1,
        ("present",),
        description="A transaction type outside the knowledge base's competence (e.g. crypto)"),
    _spec(
        "unsupported_structure",
        1,
        ("present",),
        description="A customer structure outside the knowledge base's competence (e.g. a trust)"))

# --------------------------------------------------------------------------------------
# Layer 2, typologies
# --------------------------------------------------------------------------------------

TYPOLOGY_NAMES: Final[tuple[str, ...]] = (
    "structuring",
    "rapid_pass_through",
    "round_tripping",
    "mule_account",
    "cash_intensive_layering",
    "third_party_funding",
    "dormant_reactivation",
    "pep_misuse",
    "sanctions_evasion",
    "gambling_cycling")

_L2: Final[tuple[PredicateSpec, ...]] = (
    _spec(
        "typology",
        2,
        TYPOLOGY_NAMES,
        multi_valued=True,
        description="A hypothesis about pattern, never about intent",
    ),
)

DISPOSITIONS: Final[tuple[str, ...]] = (
    "clear",
    "monitor",
    "request_evidence",
    "refer_to_investigation",
    "refuse_to_decide")

# --------------------------------------------------------------------------------------
# Layer 3, risk posture
# --------------------------------------------------------------------------------------

_L3: Final[tuple[PredicateSpec, ...]] = (
    _spec("typology_support", 3, ("none", "weak", "moderate", "strong")),
    _spec("composite_risk", 4, ("low", "moderate", "high", "severe")),
    _spec("evidence_sufficiency", 3, ("sufficient", "partial", "insufficient")),
    _spec("conflict_state", 3, ("none", "soft", "irreconcilable")),
    _spec("scope_state", 3, ("in_scope", "boundary", "out_of_scope")),
    _spec(
        "mandatory_escalation",
        3,
        ("absent", "present"),
        description=(
            "A statutory trigger requires escalation regardless of computed risk. Sits at "
            "layer 3 so the disposition layer can read it without reaching into raw data."
        )),
    _spec(
        "missing_premise",
        3,
        multi_valued=True,
        description="Names a mandatory premise that could not be established"),
    _spec(
        "out_of_scope_reason",
        3,
        multi_valued=True,
        description="Names why the case is outside the knowledge base's competence"),
    _spec(
        "disposition_blocked",
        4,
        ("clear", "monitor"),
        multi_valued=True,
        description=(
            "A prohibition forbids this outcome for this case. Deliberately layer 3 rather "
            "than layer 4: a prohibition is a statement about the case's posture, and "
            "keeping it below the disposition layer means no disposition rule ever has to "
            "read another disposition fact."
        )))

# --------------------------------------------------------------------------------------
# Layer 4, disposition
# --------------------------------------------------------------------------------------

_L4: Final[tuple[PredicateSpec, ...]] = (_spec("disposition", 5, DISPOSITIONS),)


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------

PREDICATES: Final[dict[str, PredicateSpec]] = {
    spec.name: spec for spec in (*_L0, *_L1, *_L2, *_L3, *_L4)
}

MAX_LAYER: Final = 5


class UnknownPredicateError(KeyError):
    """Raised when a rule or assertion names a predicate that is not registered."""


def spec_for(predicate: str) -> PredicateSpec:
    try:
        return PREDICATES[predicate]
    except KeyError as exc:  # pragma: no cover - defensive
        raise UnknownPredicateError(
            f"{predicate!r} is not a registered predicate. "
            f"Add it to triagex.kb.predicates with an explicit layer."
        ) from exc


MANDATORY_PREDICATES: Final[frozenset[str]] = frozenset(
    name for name, spec in PREDICATES.items() if spec.mandatory
)

UNKNOWN_VALUES: Final[frozenset[str]] = frozenset({"unknown", "not_checked"})
"""Values that represent an absence of knowledge rather than a finding."""


def by_layer(layer: int) -> list[PredicateSpec]:
    return [spec for spec in PREDICATES.values() if spec.layer == layer]
