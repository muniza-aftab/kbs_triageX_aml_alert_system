"""Case files: TOML in, measurements out.

A case file describes a world, a customer, their accounts, the transactions in the alert
window, the counterparties involved. The loader turns that into the Layer 0 measurements the
indicator rules compare against thresholds.

**Everything passes through the frame system on the way in.** The loader could read the TOML
straight into a dictionary, but then a case file with `kyc_status = "complete "` or a missing
`onboarding_date` would fail somewhere deep in the rule base, or worse, quietly not match a
rule. Instantiating frames means a malformed case is rejected at the door with a message
naming the slot, and it is where the pessimistic defaults come from: a case file that never
mentions sanctions screening produces ``not_checked``, not ``none``.

TOML rather than YAML, read with the standard library's ``tomllib``, so the core keeps its
zero-dependency property.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from triagex import frames
from triagex.facts import FactBase
from triagex.kb.predicates import FactValue
from triagex.kb.reference import jurisdiction

CASE_DIR = Path(__file__).parent / "cases"

CASH_CHANNELS = frozenset({"branch", "atm"})

_FATF_SEVERITY = {"compliant": 0, "unknown": 1, "grey_list": 2, "black_list": 3}


class CaseFormatError(ValueError):
    """Raised when a case file is not a valid case."""


# --------------------------------------------------------------------------------------
# The loaded case
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Expectation:
    """What a case file claims should happen, making every case a test."""

    disposition: str | None = None
    must_fire: tuple[str, ...] = ()
    must_not_fire: tuple[str, ...] = ()
    reason: str | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Case:
    alert_id: str
    window_start: date
    window_end: date
    trigger_rule: str
    customer: frames.FrameInstance
    accounts: tuple[frames.FrameInstance, ...]
    counterparties: tuple[frames.FrameInstance, ...]
    transactions: tuple[frames.FrameInstance, ...]
    expectation: Expectation
    flows: tuple[dict[str, Any], ...] = ()
    """Counterparty-to-counterparty movement the bank can see from correspondent data.

    Without these the transaction graph is a star centred on the account and cannot contain a
    cycle, so round-tripping would be undetectable in principle rather than merely unobserved.
    """

    source_path: Path | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def window_days(self) -> int:
        return max((self.window_end - self.window_start).days + 1, 1)

    def counterparty(self, cp_id: str) -> frames.FrameInstance | None:
        return next((c for c in self.counterparties if c.id == cp_id), None)

    def credits(self) -> tuple[frames.FrameInstance, ...]:
        return tuple(t for t in self.transactions if t.get("direction") == "in")

    def debits(self) -> tuple[frames.FrameInstance, ...]:
        return tuple(t for t in self.transactions if t.get("direction") == "out")


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


def load_case(path: str | Path) -> Case:
    """Read and validate one case file."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise CaseFormatError(f"{path.name}: {exc}") from exc
    return parse_case(raw, source_path=path)


def parse_case(raw: dict[str, Any], *, source_path: Path | None = None) -> Case:
    name = source_path.name if source_path else "<inline>"

    for key in ("alert_id", "window", "customer"):
        if key not in raw:
            raise CaseFormatError(f"{name}: missing required section {key!r}")

    window = raw["window"]
    window_start = _as_date(window["start"], name)
    window_end = _as_date(window["end"], name)
    customer = _instantiate(raw["customer"], default_frame="RetailCustomer", what="customer")

    accounts = tuple(
        _instantiate(a, default_frame="CurrentAccount", what="account")
        for a in raw.get("accounts", ())
    )
    counterparties = tuple(
        _instantiate(c, default_frame="UnknownCounterparty", what="counterparty")
        for c in raw.get("counterparties", ())
    )

    transactions: list[frames.FrameInstance] = []
    for spec in raw.get("transactions", ()):
        transactions.extend(_expand_transaction(spec, name))

    expected = raw.get("expected", {})

    return Case(
        alert_id=str(raw["alert_id"]),
        window_start=window_start,
        window_end=window_end,
        trigger_rule=str(raw.get("trigger_rule", "unspecified")),
        customer=customer,
        accounts=accounts,
        counterparties=counterparties,
        transactions=tuple(transactions),
        flows=tuple(dict(flow) for flow in raw.get("flows", ())),
        expectation=Expectation(
            disposition=expected.get("disposition"),
            must_fire=tuple(expected.get("must_fire", ())),
            must_not_fire=tuple(expected.get("must_not_fire", ())),
            reason=expected.get("reason"),
            notes=expected.get("notes", "")),
        source_path=source_path,
        tags=tuple(raw.get("tags", ())))


def _instantiate(spec: dict[str, Any], *, default_frame: str, what: str) -> frames.FrameInstance:
    values = dict(spec)
    frame = values.pop("frame", default_frame)
    try:
        return frames.instantiate(frame, **values)
    except frames.FrameError as exc:
        raise CaseFormatError(f"invalid {what}: {exc}") from exc


def _expand_transaction(spec: dict[str, Any], name: str) -> list[frames.FrameInstance]:
    """Expand a transaction block, honouring ``repeat``.

    Fourteen near-identical deposits is the single commonest shape in this domain, and
    writing fourteen TOML tables makes a case file unreadable, which matters, because these
    files are documentation as much as they are fixtures. ``repeat`` with ``interval_hours``
    expands at load time, with ids suffixed so each transaction stays individually
    identifiable in a trace.
    """
    values = dict(spec)
    repeat = int(values.pop("repeat", 1))
    interval = float(values.pop("interval_hours", 24.0))
    step = float(values.pop("amount_step", 0.0))

    if repeat < 1:
        raise CaseFormatError(f"{name}: repeat must be at least 1")

    base_id = str(values.get("id", "T"))
    base_time = values.get("timestamp")
    if repeat > 1 and not isinstance(base_time, datetime):
        raise CaseFormatError(f"{name}: {base_id} uses repeat but has no datetime timestamp")

    expanded = []
    for index in range(repeat):
        instance = dict(values)
        if repeat > 1:
            instance["id"] = f"{base_id}-{index + 1}"
            assert isinstance(base_time, datetime)
            instance["timestamp"] = base_time + timedelta(hours=interval * index)
            if step:
                instance["amount"] = float(values["amount"]) + step * index
        expanded.append(_instantiate(instance, default_frame="CashDeposit", what="transaction"))
    return expanded


def _num(value: Any, default: float = 0.0) -> float:
    """Narrow a slot value to a float.

    Slot values are deliberately a wide union (a date is as valid a slot value as a
    number), so numeric measurement needs an explicit narrowing step rather than a bare
    ``float()`` that would accept a date and fail at runtime. Booleans are excluded: ``True``
    is not a quantity.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _as_date(value: Any, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise CaseFormatError(f"{name}: expected a date, got {value!r}")


# --------------------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------------------


def measurements(case: Case) -> dict[str, FactValue]:
    """Compute the Layer 0 measurements for a case.

    Arithmetic, temporal and graph quantities only. Nothing here decides anything, the
    point of keeping this separate from the rule base is that a reviewer can check the
    numbers without reading any knowledge, and check the knowledge without re-deriving any
    numbers.
    """
    inbound = case.credits()
    outbound = case.debits()

    credit_values = [float(t.require("amount")) for t in inbound]
    total_credits = sum(credit_values)
    total_debits = sum(float(t.require("amount")) for t in outbound)

    payer_ids = {str(t.get("counterparty")) for t in inbound if t.get("counterparty")}
    undeclared = {
        cp_id
        for cp_id in payer_ids
        if (cp := case.counterparty(cp_id)) is not None and not cp.get("relationship_declared")
    }

    cash_credits = sum(
        float(t.require("amount")) for t in inbound if t.get("channel") in CASH_CHANNELS
    )

    balance = sum(_num(a.get("balance")) for a in case.accounts)
    opened = min(
        (a.require("opened_date") for a in case.accounts),
        default=case.customer.require("onboarding_date"))
    activity_dates = [
        value
        for a in case.accounts
        if isinstance(value := a.get("last_activity_date"), date)
    ]
    last_activity = max(activity_dates, default=None)

    jurisdictions = [jurisdiction(str(c.get("jurisdiction") or "ZZ")) for c in case.counterparties]
    worst = max(
        (j.fatf_status.value for j in jurisdictions),
        key=lambda status: _FATF_SEVERITY[status],
        default="compliant")

    scaled_turnover = total_credits * 30.0 / case.window_days

    out: dict[str, FactValue] = {
        # Volume and patterning
        "credit_count": len(inbound),
        "max_single_credit": max(credit_values, default=0.0),
        "aggregate_credits": total_credits,
        "distinct_payers": len(payer_ids),
        "distinct_channels": len({str(t.get("channel")) for t in inbound}),
        "payer_hub_degree": len(payer_ids),
        "undeclared_payer_count": len(undeclared),
        # Flow
        "outflow_within_window_ratio": min(total_debits / total_credits, 1.0)
        if total_credits
        else 0.0,
        "closing_to_inflow_ratio": min(balance / total_credits, 1.0) if total_credits else 1.0,
        "cash_ratio": cash_credits / total_credits if total_credits else 0.0,
        # Profile
        "observed_monthly_turnover": scaled_turnover,
        "expected_monthly_turnover": _num(case.customer.require("expected_monthly_turnover")),
        "expected_cash_ratio": _num(case.customer.get("expected_cash_ratio"), 0.15),
        # Lifecycle
        "account_age_days": max((case.window_end - opened).days, 0),
        "days_since_prior_activity": (case.window_start - last_activity).days
        if last_activity
        else 0,
        # Geography
        "worst_fatf_status": worst,
        "max_counterparty_secrecy": max((j.secrecy_score for j in jurisdictions), default=0),
        # Structural flags
        "has_crypto_transaction": any(t.isa("CryptoTransfer") for t in case.transactions),
        "has_gambling_counterparty": any(
            bool(c.get("is_gambling_operator")) for c in case.counterparties
        ),
        "closed_value_loop": _has_closed_loop(case),
        # Customer slot mirrors
        "customer_type": str(case.customer.require("customer_type")),
        "kyc_status": str(case.customer.get("kyc_status")),
        "sanctions_signal": str(case.customer.get("sanctions_signal")),
        "pep_status": str(case.customer.get("pep_status")),
        "source_of_funds_evidence": str(case.customer.get("source_of_funds_evidence")),
        "adverse_media": str(case.customer.get("adverse_media")),
        "declared_purpose": str(case.customer.get("declared_purpose")),
    }
    return out


def _has_closed_loop(case: Case) -> bool:
    """Whether value returns to its origin, computed by graph search.

    This measurement was a hand-declared boolean in the case file until the network search
    existed. Computing it closes the placeholder: the round-tripping indicator now rests on an
    actual cycle in the transaction graph rather than on a case author asserting one.
    """
    from triagex.search.network import graph_for_case

    return graph_for_case(case).has_closed_loop()


def factbase_for(case: Case) -> FactBase:
    """Seed a fact base with a case's measurements, keyed to the alert."""
    fb = FactBase()
    for predicate, value in measurements(case).items():
        fb.assert_raw(predicate, case.alert_id, value, field=f"case.{predicate}")
    return fb


# --------------------------------------------------------------------------------------
# The library
# --------------------------------------------------------------------------------------


def case_paths(directory: Path | None = None) -> list[Path]:
    return sorted((directory or CASE_DIR).glob("*.toml"))


def load_library(directory: Path | None = None) -> list[Case]:
    """Load every case in the library, sorted by filename for reproducibility."""
    return [load_case(path) for path in case_paths(directory)]
