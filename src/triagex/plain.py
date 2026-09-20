"""Plain-language presentation layer.

The rule base speaks in `typology_support`, `cf +0.86` and `IND-PROX-01`. That vocabulary is
precise and it is the right vocabulary for the knowledge base, the documentation and anyone
reading the code. It is the wrong vocabulary for the person who actually has to act on a
decision.

This module is the only place that translation happens. Two rules kept throughout:

**Nothing is simplified into inaccuracy.** "Pattern strength: Strong" is a fair rendering of
`typology_support(strong)`. "Confidence: 86%" would not be a fair rendering of `cf +0.86`,
because a certainty factor is not a probability, so certainties are shown as qualitative
strength, and the underlying number is available but never dressed up as a percentage.

**The technical identifier is always reachable.** Every translated item carries its original
term, so an analyst who wants to look a rule up can, and nobody has to take the friendly
wording on trust. Hiding the machinery would make the system less auditable, which is the
opposite of the point.

The form schema also lives here, so the website builds its questions from the same definitions
the assessment uses rather than duplicating them in HTML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from triagex.evaluate import ABSTAIN
from triagex.explain.why import explain, near_misses, why_not_all
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.predicates import FactValue
from triagex.pipeline import Assessment

# --------------------------------------------------------------------------------------
# Outcomes
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeCopy:
    key: str
    label: str
    short: str
    meaning: str
    action: str
    tone: str


OUTCOMES: dict[str, OutcomeCopy] = {
    "clear": OutcomeCopy(
        key="clear",
        label="Close the alert",
        short="Closed",
        meaning="Nothing in this activity needs further attention, and the customer file is complete.",
        action="No further action. Record the decision and close.",
        tone="ok"),
    "monitor": OutcomeCopy(
        key="monitor",
        label="Close, with enhanced monitoring",
        short="Monitoring",
        meaning=(
            "There is something faintly unusual here, but not enough to justify taking up an "
            "investigator's time."
        ),
        action="Close the alert and place the customer under enhanced ongoing monitoring.",
        tone="watch"),
    "request_evidence": OutcomeCopy(
        key="request_evidence",
        label="Request evidence before deciding",
        short="Evidence needed",
        meaning=(
            "A recognised pattern is supported, but a specific piece of evidence is missing from "
            "the file. Asking for it costs far less than escalating on an incomplete picture."
        ),
        action="Request the evidence listed below, then reassess.",
        tone="ask"),
    "refer_to_investigation": OutcomeCopy(
        key="refer_to_investigation",
        label="Refer to a financial crime investigator",
        short="Referred",
        meaning=(
            "The evidence is complete and it supports a recognised pattern. The system knows what "
            "it is looking at, but only a person with reporting authority can decide what happens "
            "next."
        ),
        action=(
            "Escalate to the financial crime team. Only the Money Laundering Reporting Officer can "
            "authorise a Suspicious Activity Report."
        ),
        tone="escalate"),
    ABSTAIN: OutcomeCopy(
        key=ABSTAIN,
        label="Cannot decide, needs a person",
        short="No decision",
        meaning=(
            "This system cannot form a view on this case. That is a deliberate outcome, not a "
            "failure: the reasons are listed below, and each one names something specific that "
            "would have to change."
        ),
        action="Pass to an analyst with the reasons below. Do not treat this as a clean result.",
        tone="abstain"),
}


# --------------------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------------------

ASSESSMENT_LABELS: dict[str, str] = {
    "typology_support": "Pattern strength",
    "composite_risk": "Overall risk",
    "evidence_sufficiency": "Evidence on file",
    "conflict_state": "Internal disagreement",
    "scope_state": "Assessable by this system",
    "mandatory_escalation": "Legal trigger",
}

ASSESSMENT_HELP: dict[str, str] = {
    "typology_support": "How strongly the activity matches a recognised laundering pattern.",
    "composite_risk": "The overall risk posture, combining the pattern strength with context.",
    "evidence_sufficiency": "Whether the customer file holds enough to support a decision.",
    "conflict_state": "Whether the evidence points in two directions at once.",
    "scope_state": "Whether every part of this case is something this system can assess.",
    "mandatory_escalation": "Whether a legal obligation forces escalation regardless of risk.",
}

VALUE_LABELS: dict[str, str] = {
    # Pattern strength
    "none": "None",
    "weak": "Weak",
    "moderate": "Moderate",
    "strong": "Strong",
    # Risk
    "low": "Low",
    "severe": "Severe",
    "high": "High",
    # Evidence
    "sufficient": "Complete",
    "partial": "Incomplete",
    "insufficient": "Not usable",
    # Conflict
    "soft": "Minor, resolved",
    "irreconcilable": "Cannot be resolved",
    # Scope
    "in_scope": "Yes, fully",
    "boundary": "Partly, one element could not be checked",
    "out_of_scope": "No",
    # Triggers
    "absent": "None",
    "present": "Yes",
}

TYPOLOGY_LABELS: dict[str, tuple[str, str]] = {
    "structuring": (
        "Splitting deposits",
        "A larger sum broken into payments kept just under a review threshold."),
    "rapid_pass_through": (
        "Money passing straight through",
        "Funds arrive and leave almost immediately, leaving nothing behind."),
    "round_tripping": (
        "Money returning to its source",
        "Value leaves and comes back through intermediaries, creating the appearance of trade."),
    "mule_account": (
        "Account used as a collection point",
        "Many unrelated people paying into one account, often a recently opened one."),
    "cash_intensive_layering": (
        "Cash business mixing funds",
        "A genuine cash business used to blend other money in with real takings."),
    "third_party_funding": (
        "Payments from unexplained third parties",
        "Money arriving from people the customer has not accounted for."),
    "dormant_reactivation": (
        "Dormant account suddenly active",
        "A long-inactive account carrying high-value payments again."),
    "pep_misuse": (
        "Political exposure with unexplained movement",
        "A politically exposed person moving value well beyond their stated profile."),
    "sanctions_evasion": (
        "Possible sanctions avoidance",
        "Routing or structuring consistent with avoiding a designation."),
    "gambling_cycling": (
        "Funds cycled through gambling",
        "Money passed through betting activity to manufacture a clean source."),
}

STRENGTH_WORDS = (
    (0.75, "Strongly indicated"),
    (0.55, "Indicated"),
    (0.30, "Weakly indicated"),
    (0.0, "Barely indicated"))

PREMISE_LABELS: dict[str, str] = {
    "sanctions_signal": "Sanctions screening has not been run",
    "kyc_status": "Customer due diligence has not been recorded",
    "customer_type": "The type of customer has not been recorded",
}
"""Missing mandatory premises, named as the check a person would recognise rather than as the
field the rule base reads."""

REASON_LABELS: dict[str, str] = {
    "out_of_scope": "Part of this case is outside what the system can assess",
    "missing_premise": "A required check has not been carried out",
    "irreconcilable_conflict": "The evidence points both ways and neither side is stronger",
    "deficiency": "No rule in the system covers this combination of facts",
    "borderline_margin": "The decision was too close to the boundary to be safe",
}


def strength_word(cf: float) -> str:
    """Qualitative strength for a certainty factor.

    Deliberately not a percentage. A certainty factor is not a probability, and rendering 0.86
    as "86% confident" would be a more precise-sounding claim than the arithmetic supports.
    """
    magnitude = abs(cf)
    for floor, word in STRENGTH_WORDS:
        if magnitude >= floor:
            return word
    return "Barely indicated"


def humanise(value: object) -> str:
    """Best-effort label for any internal value."""
    text = str(value)
    return VALUE_LABELS.get(text, text.replace("_", " "))


# --------------------------------------------------------------------------------------
# The form
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    label: str
    help: str
    group: str
    kind: str = "choice"
    choices: tuple[Choice, ...] = ()
    default: str = ""
    maps_to: str = ""
    """Measurement this answer sets. Defaults to ``name``."""

    numeric_map: tuple[tuple[str, float], ...] = ()
    """For banded questions: the number each choice stands for."""

    @property
    def target(self) -> str:
        return self.maps_to or self.name

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "help": self.help,
            "group": self.group,
            "kind": self.kind,
            "default": self.default,
            "choices": [{"value": c.value, "label": c.label} for c in self.choices],
        }


def _c(*pairs: tuple[str, str]) -> tuple[Choice, ...]:
    return tuple(Choice(value, label) for value, label in pairs)


FORM: tuple[Field, ...] = (
    # ---------------------------------------------------------------- the customer
    Field(
        name="customer_type",
        label="What kind of customer is this?",
        help="A business is expected to handle more cash than an individual, and the system allows for that.",
        group="About the customer",
        choices=_c(
            ("retail", "An individual"),
            ("business", "A business"),
            ("cash_intensive", "A cash-heavy business (shop, takeaway, salon)"),
            ("trust", "A trust")),
        default="retail"),
    Field(
        name="expected_monthly_turnover",
        label="Roughly how much do you expect through this account each month?",
        help="From the customer's own declaration when the account was opened.",
        group="About the customer",
        kind="number",
        default="2500"),
    Field(
        name="pep_status",
        label="Is the customer politically exposed?",
        help="A politically exposed person requires extra checks. It is not, by itself, a reason for suspicion.",
        group="About the customer",
        choices=_c(
            ("none", "No"),
            ("domestic", "Yes, a UK public figure"),
            ("foreign", "Yes, a foreign public figure"),
            ("associate", "A family member or close associate of one")),
        default="none"),
    # ---------------------------------------------------------------- checks
    Field(
        name="sanctions_signal",
        label="Has sanctions screening been run, and what did it find?",
        help=(
            "If screening has not been run, say so. The system will decline to decide rather than "
            "assume a clean result, this is the single most important question on the form."
        ),
        group="Checks carried out",
        choices=_c(
            ("not_checked", "Not run yet"),
            ("none", "Run, no match"),
            ("possible", "Run, possible match"),
            ("confirmed", "Run, confirmed match")),
        default="none"),
    Field(
        name="kyc_status",
        label="Is customer due diligence complete?",
        help="Whether identity and background checks are finished and current.",
        group="Checks carried out",
        choices=_c(
            ("complete", "Complete and current"),
            ("partial", "Started but not finished"),
            ("expired", "Complete but now out of date"),
            ("unknown", "Not recorded")),
        default="complete"),
    Field(
        name="source_of_funds_evidence",
        label="Do you hold evidence of where the money came from?",
        help="Payslips, sale documents, an inheritance letter, anything that explains the source.",
        group="Checks carried out",
        choices=_c(
            ("present", "Yes, on file"),
            ("absent", "No"),
            ("requested", "Requested, not yet received"),
            ("unknown", "Not recorded")),
        default="present"),
    Field(
        name="adverse_media",
        label="Has an adverse media check been done?",
        help="Uncorroborated reporting is recorded but deliberately not acted on.",
        group="Checks carried out",
        choices=_c(
            ("none", "Yes, nothing found"),
            ("unverified", "Yes, something found, not corroborated"),
            ("verified", "Yes, something found and corroborated"),
            ("unknown", "Not done")),
        default="none"),
    Field(
        name="declared_purpose",
        label="Does the activity match what the account is for?",
        help="Compared against the stated purpose of the relationship.",
        group="Checks carried out",
        choices=_c(
            ("consistent", "Yes"),
            ("inconsistent", "No"),
            ("absent", "No purpose was ever recorded"),
            ("unknown", "Not recorded")),
        default="consistent"),
    # ---------------------------------------------------------------- the activity
    Field(
        name="credit_count",
        label="How many payments came in during the alert period?",
        help="Count of incoming payments in the window under review.",
        group="The activity",
        kind="number",
        default="3"),
    Field(
        name="max_single_credit",
        label="What was the largest single payment in? (GBP)",
        help="Payments sitting just under a review threshold are treated differently from payments that cross it.",
        group="The activity",
        kind="number",
        default="800"),
    Field(
        name="aggregate_credits",
        label="What was the total received? (GBP)",
        help="A large total made up of much smaller payments is itself meaningful.",
        group="The activity",
        kind="number",
        default="2400"),
    Field(
        name="payer_hub_degree",
        label="How many different people or businesses paid in?",
        help="Distinct payers, not payment count. Twenty payments from one employer is a salary.",
        group="The activity",
        kind="number",
        default="1"),
    Field(
        name="undeclared_payer_count",
        label="How many of those payers has the customer not accounted for?",
        help="Payers with no declared relationship to the customer.",
        group="The activity",
        kind="number",
        default="0"),
    Field(
        name="outflow_within_window_ratio",
        label="How much of the money left again quickly?",
        help="Money that arrives and leaves within about two days is behaving like a transfer, not a deposit.",
        group="The activity",
        choices=_c(
            ("low", "Little or none of it"),
            ("some", "Some of it"),
            ("most", "Most of it"),
            ("all", "Almost all of it")),
        default="low",
        numeric_map=(("low", 0.15), ("some", 0.55), ("most", 0.80), ("all", 0.96))),
    Field(
        name="closing_to_inflow_ratio",
        label="How much was still in the account at the end?",
        help="An account left near empty after large sums passed through is behaving like a conduit.",
        group="The activity",
        choices=_c(
            ("healthy", "A normal balance remained"),
            ("little", "Very little remained"),
            ("nothing", "Almost nothing remained")),
        default="healthy",
        numeric_map=(("healthy", 0.55), ("little", 0.12), ("nothing", 0.02))),
    Field(
        name="cash_ratio",
        label="How much of the money came in as cash?",
        help="Judged against what is normal for this kind of customer, not against a fixed figure.",
        group="The activity",
        choices=_c(
            ("none", "None or almost none"),
            ("some", "About a quarter"),
            ("half", "About half"),
            ("most", "Most of it"),
            ("all", "Nearly all of it")),
        default="none",
        numeric_map=(
            ("none", 0.03),
            ("some", 0.25),
            ("half", 0.5),
            ("most", 0.75),
            ("all", 0.95))),
    Field(
        name="distinct_channels",
        label="How many different ways did the money come in?",
        help="Branch, cash machine, online, mobile, bank transfer. Spreading payments across channels can be a way to avoid one channel seeing the whole picture.",
        group="The activity",
        kind="number",
        default="1"),
    # ---------------------------------------------------------------- context
    Field(
        name="account_age_days",
        label="How old is the account, in days?",
        help="A very new account has no established pattern to compare this activity against.",
        group="Account and counterparties",
        kind="number",
        default="900"),
    Field(
        name="days_since_prior_activity",
        label="How long was the account quiet before this?",
        help="In days. A long-dormant account suddenly becoming active is a recognised pattern.",
        group="Account and counterparties",
        kind="number",
        default="5"),
    Field(
        name="worst_fatf_status",
        label="What is the highest-risk country involved?",
        help=(
            "Based on international monitoring status. Country names in this system are fictional; "
            "a real deployment would load the current published lists."
        ),
        group="Account and counterparties",
        choices=_c(
            ("compliant", "All countries are low risk"),
            ("grey_list", "One is under increased monitoring"),
            ("black_list", "One is subject to countermeasures"),
            ("unknown", "A country could not be identified")),
        default="compliant"),
    Field(
        name="has_crypto_transaction",
        label="Were any cryptoasset transfers involved?",
        help=(
            "This system has no model of cryptoasset flows. If any are present it will decline to "
            "decide rather than judge the half of the case it understands."
        ),
        group="Account and counterparties",
        choices=_c(("no", "No"), ("yes", "Yes")),
        default="no",
        numeric_map=(("no", 0.0), ("yes", 1.0))),
    Field(
        name="has_gambling_counterparty",
        label="Was a gambling operator involved?",
        help="Funds cycled through betting can be used to manufacture an explanation for their source.",
        group="Account and counterparties",
        choices=_c(("no", "No"), ("yes", "Yes")),
        default="no",
        numeric_map=(("no", 0.0), ("yes", 1.0))))

FORM_GROUPS: tuple[str, ...] = (
    "About the customer",
    "Checks carried out",
    "The activity",
    "Account and counterparties")

BOOLEAN_TARGETS = frozenset({"has_crypto_transaction", "has_gambling_counterparty"})


class FormError(ValueError):
    """Raised when a submitted answer is not one the form offers."""


def to_measurements(answers: dict[str, Any]) -> dict[str, FactValue]:
    """Turn form answers into the measurements the rule base reads.

    Unanswered questions fall back to the field default rather than being omitted. That is a
    deliberate choice and it is safe *because* the defaults are pessimistic where it matters:
    leaving the sanctions question alone gives ``none`` only because the form default says so,
    and a user who has not run screening must actively say ``not_checked``. The website makes
    that question unmissable for the same reason.
    """
    measurements: dict[str, FactValue] = {}

    for field_def in FORM:
        raw = answers.get(field_def.name, field_def.default)
        text = str(raw).strip() if raw not in (None, "") else field_def.default

        if field_def.kind == "number":
            try:
                measurements[field_def.target] = float(text)
            except ValueError as exc:
                raise FormError(f"{field_def.label!r} needs a number, got {text!r}") from exc
            continue

        if field_def.numeric_map:
            lookup = dict(field_def.numeric_map)
            if text not in lookup:
                raise FormError(f"{text!r} is not an option for {field_def.label!r}")
            value = lookup[text]
            measurements[field_def.target] = (
                bool(value) if field_def.target in BOOLEAN_TARGETS else value
            )
            continue

        allowed = {choice.value for choice in field_def.choices}
        if allowed and text not in allowed:
            raise FormError(f"{text!r} is not an option for {field_def.label!r}")
        measurements[field_def.target] = text

    # Derived measurements the form does not ask about directly, because asking would be
    # redundant or unanswerable by someone filling in a web form.
    turnover = float(measurements.get("aggregate_credits", 0.0) or 0.0)
    measurements["observed_monthly_turnover"] = turnover
    measurements["distinct_payers"] = measurements.get("payer_hub_degree", 1)
    measurements["expected_cash_ratio"] = (
        0.60 if measurements.get("customer_type") == "cash_intensive" else 0.15
    )
    measurements["closed_value_loop"] = False
    measurements["max_counterparty_secrecy"] = 4

    return measurements


def form_schema() -> dict[str, Any]:
    """The form definition, for the website to render.

    Served rather than duplicated in HTML so the questions, their wording and their allowed
    answers have exactly one source.
    """
    return {
        "groups": [
            {
                "name": group,
                "fields": [f.as_dict() for f in FORM if f.group == group],
            }
            for group in FORM_GROUPS
        ]
    }


# --------------------------------------------------------------------------------------
# Rendering an assessment
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class PlainAssessment:
    """One assessment, expressed for someone who has to act on it."""

    alert: str
    outcome: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    patterns: list[dict[str, Any]] = field(default_factory=list)
    assessment: list[dict[str, Any]] = field(default_factory=list)
    reasoning: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    margin_notes: list[str] = field(default_factory=list)
    evidence_requested: list[dict[str, Any]] = field(default_factory=list)
    technical: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert": self.alert,
            "outcome": self.outcome,
            "reasons": self.reasons,
            "patterns": self.patterns,
            "assessment": self.assessment,
            "reasoning": self.reasoning,
            "alternatives": self.alternatives,
            "margin_notes": self.margin_notes,
            "evidence_requested": self.evidence_requested,
            "technical": self.technical,
        }


def render(assessment: Assessment, *, include_evidence: bool = True) -> PlainAssessment:
    """Translate an assessment into plain language."""
    detail = explain(assessment)
    copy = OUTCOMES[assessment.outcome]
    by_id = {rule.id: rule for rule in KNOWLEDGE_BASE}

    patterns = [
        {
            "name": TYPOLOGY_LABELS.get(name, (name.replace("_", " "), ""))[0],
            "explanation": TYPOLOGY_LABELS.get(name, ("", ""))[1],
            "strength": strength_word(cf),
            "certainty": round(cf, 2),
            "technical_name": name,
        }
        for name, cf in detail.typologies
    ]

    assessment_rows = [
        {
            "label": ASSESSMENT_LABELS.get(key, key.replace("_", " ")),
            "value": humanise(value),
            "help": ASSESSMENT_HELP.get(key, ""),
            "technical_name": key,
            "technical_value": value,
        }
        for key, value in detail.posture
    ]

    reasoning = [
        {
            "finding": reason.statement.replace("_", " ").capitalize(),
            "because": reason.rationale,
            "rule_id": reason.rule_id,
            "source": by_id[reason.rule_id].source if reason.rule_id in by_id else "",
        }
        for reason in detail.reasons
    ]

    alternatives = []
    for outcome_key, verdict in why_not_all(assessment).items():
        blockers = [_blocker_sentence(item) for item in verdict.unmet]
        if verdict.blocked_by_precedence:
            blockers.insert(0, "A more urgent rule applied first")
        already_says_prohibited = any("prohibits" in b for b in blockers)
        if verdict.prohibitions and not already_says_prohibited:
            blockers.append("A rule prohibits this outcome outright, whatever else is true")
        alternatives.append(
            {
                "outcome": OUTCOMES[outcome_key].label,
                "outcome_key": outcome_key,
                "blockers": blockers or ["Nothing in the system produces this outcome"],
            }
        )

    plain = PlainAssessment(
        alert=assessment.alert,
        outcome={
            "key": copy.key,
            "label": copy.label,
            "short": copy.short,
            "meaning": copy.meaning,
            "action": copy.action,
            "tone": copy.tone,
            "headline": detail.headline,
        },
        reasons=[_soften(r) for r in detail.abstention_reasons],
        patterns=patterns,
        assessment=assessment_rows,
        reasoning=reasoning,
        alternatives=alternatives,
        margin_notes=near_misses(assessment, limit=2),
        technical={
            "stage": assessment.decision.stage.id,
            "rules_fired": len(assessment.trace.fired),
            "cycles": assessment.trace.cycles_run,
            "margin": None if assessment.margin is None else round(assessment.margin, 3),
        })

    if include_evidence and assessment.outcome in {"request_evidence", ABSTAIN}:
        plain.evidence_requested = _evidence_for(assessment)

    return plain


def _evidence_for(assessment: Assessment) -> list[dict[str, Any]]:
    """What to ask for, if anything would help."""
    from triagex.search.contrastive import cheapest_evidence

    measurements = {
        fact.predicate: fact.value
        for fact in assessment.facts
        if fact.layer == 0 and fact.derivation.__class__.__name__ == "Asserted"
    }
    if not measurements:
        return []

    for target in ("clear", "refer_to_investigation"):
        request = cheapest_evidence(
            assessment.alert, dict(measurements), target, max_interventions=2
        )
        if request.found:
            return [
                {"action": item.description, "effort": item.cost, "technical_name": item.name}
                for item in request.interventions
            ]
    return []


def _blocker_sentence(item: Any) -> str:
    """One unmet condition, written as a sentence.

    Built from the structured fields rather than by rewriting the technical description,
    because string substitution on a sentence produces exactly the sort of half-translated
    output that reads worse than leaving it alone: "Evidence on file is partial, not
    sufficient" has the label translated and the values left raw.
    """
    label = ASSESSMENT_LABELS.get(item.predicate, item.predicate.replace("_", " "))

    if item.predicate == "disposition_blocked":
        return "A rule prohibits this outcome for this case"

    if item.expected == "nothing recorded":
        return f"{label} has been recorded, and this outcome requires that it has not"

    wanted = " or ".join(humanise(v.strip()) for v in item.expected.split(" or "))

    if item.actual == "unknown":
        return f"{label} has not been established; it would need to be {wanted}"

    return f"{label} is {humanise(item.actual)}, and would need to be {wanted}"


def _soften(text: str) -> str:
    """Replace internal predicate names in a sentence with their plain labels."""
    out = text
    for key, label in ASSESSMENT_LABELS.items():
        out = out.replace(key, label.lower())
    for key, label in REASON_LABELS.items():
        out = out.replace(key, label.lower())
    out = out.replace("disposition_blocked", "a prohibition")

    # Missing-premise reasons arrive as "missing premise: sanctions_signal". Name the check.
    if out.startswith("missing premise: "):
        premise = out.removeprefix("missing premise: ").strip()
        return PREMISE_LABELS.get(premise, f"A required check has not been recorded: {premise}")

    out = out.replace("_", " ")
    return out[0].upper() + out[1:] if out else out


def outcome_catalogue() -> list[dict[str, Any]]:
    """The five outcomes, for the website's explanatory pages."""
    return [
        {
            "key": copy.key,
            "label": copy.label,
            "short": copy.short,
            "meaning": copy.meaning,
            "action": copy.action,
            "tone": copy.tone,
        }
        for copy in OUTCOMES.values()
    ]
