"""Reference data for the AML triage knowledge base.

**Everything in this module is illustrative.** None of it is authoritative, none of it
should be used to make a decision about a real person, and no live list is embedded.

Two deliberate decisions are worth reading before using anything here:

1. **Jurisdictions are fictional.** Real FATF listings change several times a year and
   naming real countries in a portfolio project would embed a stale list with political
   content for no engineering benefit. A production system would load the current lists
   from the FATF and HM Treasury publications at runtime; this one models the *shape* of
   that data with invented jurisdictions so the rules can be exercised honestly.

2. **Numeric thresholds are reconstructed, not sourced.** Published guidance describes the
   shape of suspicious behaviour but leaves cut-offs to each firm's risk appetite. Every
   number below was chosen to be plausible and is tagged ``reconstructed`` in the
   provenance index. The evaluation deliberately tests sensitivity to them rather than
   treating them as ground truth.

See ``docs/02-knowledge-acquisition.md`` for the provenance policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# --------------------------------------------------------------------------------------
# Jurisdictions (fictional)
# --------------------------------------------------------------------------------------


class FatfStatus(StrEnum):
    """Mirrors the shape of FATF's public listing categories."""

    COMPLIANT = "compliant"
    GREY_LIST = "grey_list"
    BLACK_LIST = "black_list"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class JurisdictionProfile:
    code: str
    name: str
    fatf_status: FatfStatus
    secrecy_score: int  # 0-10, higher means less transparent


JURISDICTIONS: Final[dict[str, JurisdictionProfile]] = {
    "AL": JurisdictionProfile("AL", "Alvarra", FatfStatus.COMPLIANT, 2),
    "BR": JurisdictionProfile("BR", "Brevik", FatfStatus.COMPLIANT, 3),
    "CO": JurisdictionProfile("CO", "Corvane", FatfStatus.COMPLIANT, 4),
    "DM": JurisdictionProfile("DM", "Dalmuir", FatfStatus.GREY_LIST, 6),
    "ES": JurisdictionProfile("ES", "Esterhold", FatfStatus.GREY_LIST, 7),
    "FN": JurisdictionProfile("FN", "Fenmark", FatfStatus.GREY_LIST, 8),
    "GY": JurisdictionProfile("GY", "Gysant", FatfStatus.BLACK_LIST, 9),
    "HV": JurisdictionProfile("HV", "Havrenne", FatfStatus.BLACK_LIST, 10),
    "ZZ": JurisdictionProfile("ZZ", "Unrecorded", FatfStatus.UNKNOWN, 5),
}

HOME_JURISDICTION: Final = "AL"
"""The modelled institution's own jurisdiction. Stands in for the UK."""


def jurisdiction(code: str) -> JurisdictionProfile:
    """Look up a jurisdiction, falling back to the explicit 'unknown' profile.

    An unrecognised code must never read as low risk, so it resolves to ``ZZ``
    (``fatf_status = unknown``), which the meta-layer can treat as a scope condition
    rather than as a benign value.
    """
    return JURISDICTIONS.get(code.upper(), JURISDICTIONS["ZZ"])


# --------------------------------------------------------------------------------------
# Thresholds  (all reconstructed)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Numeric cut-offs used by the Layer 1 indicator rules."""

    # Cash and threshold proximity
    internal_review_threshold: float = 3_000.0
    """Illustrative internal review trigger. Structuring is defined relative to this."""

    proximity_band_lower: float = 0.80
    """A deposit between 80% and 99.9% of the review threshold sits 'just under' it."""

    proximity_band_upper: float = 0.999

    # Frequency
    frequency_window_days: int = 7
    frequency_elevated: int = 5
    frequency_extreme: int = 10

    # Aggregation
    aggregation_gap_multiple: float = 5.0
    """Aggregate over the window exceeding this multiple of the largest single item."""

    # Velocity / pass-through
    passthrough_hours: int = 48
    """Funds leaving within this window of arriving counts as rapid pass-through."""

    retention_ratio_low: float = 0.10
    """Closing balance below this share of inflow means the money did not stay."""

    # Turnover
    turnover_above_multiple: float = 2.0
    turnover_far_above_multiple: float = 5.0

    # Account lifecycle
    immaturity_days: int = 90
    dormancy_days: int = 180

    # Counterparty network
    concentration_degree: int = 5
    """Distinct payers into one account before it looks concentrated."""

    hub_degree: int = 12
    """Distinct payers before the account looks like a collection hub."""

    novel_counterparty_txn_count: int = 3
    """At or below this prior transaction count, a counterparty is 'new'."""

    # Cash-intensive business
    cash_ratio_tolerance: float = 0.15
    """Permitted overshoot above the frame's declared expected_cash_ratio."""


THRESHOLDS: Final = Thresholds()


# --------------------------------------------------------------------------------------
# Certainty factor constants
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CertaintyConstants:
    noise_floor: float = 0.20
    """Facts weaker than this are not asserted at all."""

    conflict_irreconcilable_delta: float = 0.15
    """Incompatible L3 conclusions closer than this cannot be resolved by preference."""

    support_weak: float = 0.30
    support_moderate: float = 0.55
    support_strong: float = 0.75
    """Bands mapping the strongest typology cf onto ``typology_support``."""


CF: Final = CertaintyConstants()


# --------------------------------------------------------------------------------------
# Scope and mandatory premises
# --------------------------------------------------------------------------------------

MANDATORY_PREMISES: Final[frozenset[str]] = frozenset(
    {
        "sanctions_signal",
        "kyc_status",
        "customer_type",
    }
)
"""Premises that must be *known*. An unknown value forces ``refuse_to_decide`` rather
than being treated as benign. Enforced by the engine: these predicates may not be
queried under negation-as-failure."""

SCOPE_MARKER_FRAMES: Final[frozenset[str]] = frozenset(
    {
        "CryptoTransfer",
        "TrustCustomer",
    }
)
"""Instantiating any of these puts a case outside the knowledge base's competence."""

EXCLUDED_TYPOLOGIES: Final[dict[str, str]] = {
    "trade_based": "Requires trade documents, invoices and pricing benchmarks that are not modelled.",
    "crypto_ramp": "Requires chain analytics; a different evidence base entirely.",
    "correspondent_banking": "Nested relationships and downstream customers are not modelled.",
    "tcsp_structuring": "Beneficial-ownership chain reasoning is out of scope.",
}
"""Named exclusions. These are load-bearing: a system that claims total coverage cannot
have a meaningful abstention outcome."""


# --------------------------------------------------------------------------------------
# Typology catalogue
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypologyProfile:
    name: str
    summary: str
    provenance: str  # statutory | guidance | reconstructed


TYPOLOGIES: Final[dict[str, TypologyProfile]] = {
    "structuring": TypologyProfile(
        "structuring",
        "A larger sum split into deposits kept below a review threshold.",
        "guidance"),
    "rapid_pass_through": TypologyProfile(
        "rapid_pass_through",
        "Funds arrive and leave almost immediately, leaving little balance behind.",
        "guidance"),
    "round_tripping": TypologyProfile(
        "round_tripping",
        "Value returns to its origin via intermediaries, manufacturing apparent trade.",
        "guidance"),
    "mule_account": TypologyProfile(
        "mule_account",
        "A newly opened or low-profile account receiving many unrelated inbound payments.",
        "guidance"),
    "cash_intensive_layering": TypologyProfile(
        "cash_intensive_layering",
        "A genuine cash business used to mix illicit funds with real takings.",
        "guidance"),
    "third_party_funding": TypologyProfile(
        "third_party_funding",
        "Deposits from parties with no declared or plausible relationship to the customer.",
        "guidance"),
    "dormant_reactivation": TypologyProfile(
        "dormant_reactivation",
        "A long-inactive account suddenly carrying high-value flows.",
        "guidance"),
    "pep_misuse": TypologyProfile(
        "pep_misuse",
        "Politically exposed person exposure combined with unexplained value movement.",
        "statutory"),
    "sanctions_evasion": TypologyProfile(
        "sanctions_evasion",
        "Routing or structuring consistent with avoiding a designation.",
        "statutory"),
    "gambling_cycling": TypologyProfile(
        "gambling_cycling",
        "Funds cycled through betting activity to manufacture a clean source.",
        "reconstructed"),
}


# --------------------------------------------------------------------------------------
# Evidence costs (drive the contrastive explanation search)
# --------------------------------------------------------------------------------------

EVIDENCE_COSTS: Final[dict[str, float]] = {
    "sanctions_screen": 1.0,
    "internal_transaction_history": 1.0,
    "kyc_refresh": 3.0,
    "counterparty_relationship_declaration": 4.0,
    "source_of_funds_evidence": 5.0,
    "employer_confirmation": 6.0,
    "adverse_media_review": 6.0,
    "customer_interview": 9.0,
    "beneficial_ownership_trace": 12.0,
}
"""Relative cost of obtaining each kind of evidence, combining analyst effort with how
intrusive the request is for the customer. Used as edge cost in the contrastive search,
so the ``request_evidence`` disposition asks for the cheapest sufficient evidence rather
than everything at once. An internal check costs less than a question to the customer;
a full ownership trace costs most."""

MIN_EVIDENCE_COST: Final = min(EVIDENCE_COSTS.values())
"""Used as the admissible heuristic for A*: any remaining step costs at least this much."""


# --------------------------------------------------------------------------------------
# Evaluation cost matrix
# --------------------------------------------------------------------------------------

AMBIGUOUS_DECISION_COST: Final = 9.0
"""Cost of deciding a case that has no defensible answer.

Without this the evaluation cannot reward abstention at all: if every case has a correct label,
declining is always a small loss and the coverage curve slopes one way by construction. Cases
where the evidence genuinely does not support a view are the only ones on which a reject option
can be shown to pay, so they carry a real penalty for answering and none for declining.
"""

ABSTENTION_COST: Final = 2.0
"""Cost of declining to decide: an analyst still has to look, but nothing is decided
wrongly. Abstention is not free, a system that abstains on everything is useless."""

MISCLASSIFICATION_COSTS: Final[dict[tuple[str, str], float]] = {
    # (expected, predicted): cost.  Asymmetric by design.
    ("refer_to_investigation", "clear"): 25.0,
    ("refer_to_investigation", "monitor"): 15.0,
    ("refer_to_investigation", "request_evidence"): 4.0,
    ("request_evidence", "clear"): 8.0,
    ("request_evidence", "refer_to_investigation"): 3.0,
    ("monitor", "clear"): 5.0,
    ("monitor", "refer_to_investigation"): 3.0,
    ("clear", "monitor"): 1.0,
    ("clear", "request_evidence"): 3.0,
    ("clear", "refer_to_investigation"): 6.0,
    # Deciding a case the system could not properly assess. Ranked by how much the wrong
    # answer closes down: clearing it ends the firm's attention on a case nobody understood,
    # which is the worst of these, while escalating it at least puts it in front of a human.
    ("refuse_to_decide", "clear"): 12.0,
    ("refuse_to_decide", "monitor"): 10.0,
    ("refuse_to_decide", "request_evidence"): 6.0,
    ("refuse_to_decide", "refer_to_investigation"): 5.0,
}
"""Risk-weighted cost of each error. Missing a case that should have been referred costs
far more than over-escalating a clean one, but over-escalation is not free either: it
consumes investigator time and can freeze an innocent customer's account. Plain accuracy
would treat these as equivalent, which is why the evaluation does not report it alone."""
