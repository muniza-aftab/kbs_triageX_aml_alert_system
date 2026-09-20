"""The frame system: typed objects with inheritance, defaults and slot validation.

Frames earn their place here rather than being a nostalgic nod to 1970s AI. Two things they
do that flat records would not:

**Inheritance does real work.** ``CashIntensiveBusiness`` inherits every rule written about
``BusinessCustomer`` while overriding ``expected_cash_ratio`` from 0.15 to 0.60. Without
that, every cash-related rule would need a special case, and a takeaway banking 80% of its
turnover in cash would look identical to a consultancy doing the same thing.

**Scope markers make abstention possible.** Some frames exist purely so the meta-layer can
recognise a case the knowledge base has no business deciding. Instantiating a
``CryptoTransfer`` is sufficient to put a case out of scope, because nothing in this system
models chain analytics.

Slot narrowing is enforced: a subclass may restrict an inherited slot's allowed values or
change its default, never widen the set. Widening would silently invalidate rules written
against the parent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final

from triagex.kb.reference import SCOPE_MARKER_FRAMES

SlotValue = str | bool | int | float | date | datetime | None


class FrameError(ValueError):
    """Raised on an invalid frame definition or instantiation."""


@dataclass(frozen=True, slots=True)
class Slot:
    name: str
    kind: type | tuple[type, ...]
    values: frozenset[str] | None = None
    default: SlotValue = None
    required: bool = False
    description: str = ""

    def accepts(self, value: SlotValue) -> bool:
        if value is None:
            return not self.required
        if not isinstance(value, self.kind):
            return False
        if self.values is not None:
            return isinstance(value, str) and value in self.values
        return True

    def narrows(self, parent: Slot) -> bool:
        """Whether this slot is a legal refinement of an inherited one."""
        if parent.values is None:
            return True
        if self.values is None:
            return False
        return self.values <= parent.values


@dataclass(frozen=True, slots=True)
class FrameClass:
    name: str
    parent: str | None = None
    own_slots: tuple[Slot, ...] = ()
    description: str = ""

    @property
    def is_scope_marker(self) -> bool:
        return self.name in SCOPE_MARKER_FRAMES


# --------------------------------------------------------------------------------------
# The hierarchy
# --------------------------------------------------------------------------------------


def _s(
    name: str,
    kind: type | tuple[type, ...],
    *,
    values: tuple[str, ...] | None = None,
    default: SlotValue = None,
    required: bool = False,
    description: str = "") -> Slot:
    return Slot(
        name=name,
        kind=kind,
        values=frozenset(values) if values else None,
        default=default,
        required=required,
        description=description)


_DEFINITIONS: Final[tuple[FrameClass, ...]] = (
    FrameClass("Entity", None, (_s("id", str, required=True),)),
    # -- parties ----------------------------------------------------------------------
    FrameClass("Party", "Entity"),
    FrameClass(
        "Customer",
        "Party",
        (
            _s(
                "customer_type",
                str,
                values=("retail", "business", "cash_intensive", "trust"),
                required=True),
            _s("risk_rating", str, values=("low", "medium", "high"), default="medium"),
            _s("pep_status", str, values=("none", "domestic", "foreign", "associate"), default="none"),
            _s(
                "sanctions_signal",
                str,
                values=("none", "possible", "confirmed", "not_checked"),
                default="not_checked",
                description="Defaults to not_checked: a case that omits the check must not read as clean"),
            _s(
                "kyc_status",
                str,
                values=("complete", "partial", "expired", "unknown"),
                default="unknown"),
            _s("onboarding_date", date, required=True),
            _s("expected_monthly_turnover", (int, float), required=True),
            _s("expected_cash_ratio", (int, float), default=0.15),
            _s(
                "source_of_funds_evidence",
                str,
                values=("present", "absent", "requested", "unknown"),
                default="unknown"),
            _s("adverse_media", str, values=("none", "unverified", "verified", "unknown"), default="unknown"),
            _s("declared_occupation", str),
            _s(
                "declared_purpose",
                str,
                values=("consistent", "inconsistent", "absent", "unknown"),
                default="unknown",
                description="Whether activity matches the stated purpose of the relationship"))),
    FrameClass("RetailCustomer", "Customer", (_s("customer_type", str, values=("retail",), default="retail"),)),
    FrameClass(
        "BusinessCustomer",
        "Customer",
        (
            _s("customer_type", str, values=("business", "cash_intensive"), default="business"),
            _s("industry", str))),
    FrameClass(
        "CashIntensiveBusiness",
        "BusinessCustomer",
        (
            _s("customer_type", str, values=("cash_intensive",), default="cash_intensive"),
            _s(
                "expected_cash_ratio",
                (int, float),
                default=0.60,
                description="Overrides the 0.15 default: heavy cash use is expected here, not suspicious"))),
    FrameClass(
        "TrustCustomer",
        "Customer",
        (_s("customer_type", str, values=("trust",), default="trust"),),
        description="Scope marker: beneficial-ownership chain reasoning is out of scope"),
    FrameClass(
        "Counterparty",
        "Party",
        (
            _s("jurisdiction", str, default="ZZ"),
            _s("relationship_declared", bool, default=False),
            _s("prior_txn_count", int, default=0),
            _s("is_flagged", bool, default=False),
            _s("is_gambling_operator", bool, default=False))),
    FrameClass("KnownCounterparty", "Counterparty", (_s("relationship_declared", bool, default=True),)),
    FrameClass("UnknownCounterparty", "Counterparty"),
    # -- accounts ---------------------------------------------------------------------
    FrameClass(
        "Account",
        "Entity",
        (
            _s("owner", str, required=True),
            _s("opened_date", date, required=True),
            _s("balance", (int, float), default=0.0),
            _s("average_balance_90d", (int, float), default=0.0),
            _s("dormant_since", date),
            _s(
                "last_activity_date",
                date,
                description="Last activity before the alert window; drives dormancy detection"))),
    FrameClass("CurrentAccount", "Account"),
    FrameClass("SavingsAccount", "Account"),
    FrameClass("PaymentAccount", "Account"),
    # -- transactions -----------------------------------------------------------------
    FrameClass(
        "Transaction",
        "Entity",
        (
            _s("account", str, required=True),
            _s("amount", (int, float), required=True),
            _s("currency", str, default="GBP"),
            _s("timestamp", datetime, required=True),
            _s("direction", str, values=("in", "out"), required=True),
            _s("channel", str, values=("branch", "atm", "online", "mobile", "api"), required=True),
            _s("counterparty", str),
            _s("narrative", str))),
    FrameClass("CashDeposit", "Transaction", (_s("direction", str, values=("in",), default="in"),)),
    FrameClass("CashWithdrawal", "Transaction", (_s("direction", str, values=("out",), default="out"),)),
    FrameClass("InboundTransfer", "Transaction", (_s("direction", str, values=("in",), default="in"),)),
    FrameClass("OutboundTransfer", "Transaction", (_s("direction", str, values=("out",), default="out"),)),
    FrameClass("CardPayment", "Transaction", (_s("direction", str, values=("out",), default="out"),)),
    FrameClass(
        "CryptoTransfer",
        "Transaction",
        description="Scope marker: requires chain analytics this system does not have"),
    # -- context ----------------------------------------------------------------------
    FrameClass(
        "Jurisdiction",
        "Entity",
        (
            _s("fatf_status", str, values=("compliant", "grey_list", "black_list", "unknown"), default="unknown"),
            _s("secrecy_score", int, default=5))),
    FrameClass(
        "Alert",
        "Entity",
        (
            _s("customer", str, required=True),
            _s("window_start", date, required=True),
            _s("window_end", date, required=True),
            _s("trigger_rule", str, default="unspecified"))))

FRAMES: Final[dict[str, FrameClass]] = {f.name: f for f in _DEFINITIONS}


# --------------------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------------------


def lineage(frame_name: str) -> list[str]:
    """The frame and its ancestors, most specific first."""
    chain: list[str] = []
    current: str | None = frame_name
    while current is not None:
        if current in chain:
            raise FrameError(f"cycle in frame hierarchy at {current!r}")
        if current not in FRAMES:
            raise FrameError(f"unknown frame {current!r}")
        chain.append(current)
        current = FRAMES[current].parent
    return chain


def resolved_slots(frame_name: str) -> dict[str, Slot]:
    """All slots for a frame, with subclass definitions overriding inherited ones."""
    slots: dict[str, Slot] = {}
    for name in reversed(lineage(frame_name)):
        for slot in FRAMES[name].own_slots:
            inherited = slots.get(slot.name)
            if inherited is not None and not slot.narrows(inherited):
                raise FrameError(
                    f"{name}.{slot.name} widens the inherited allowed values "
                    f"({sorted(slot.values or ())} is not a subset of "
                    f"{sorted(inherited.values or ())}). Widening would invalidate rules "
                    f"written against the parent frame."
                )
            slots[slot.name] = slot
    return slots


def validate_hierarchy() -> None:
    """Check every frame resolves cleanly. Called by the test suite."""
    for name in FRAMES:
        resolved_slots(name)


# --------------------------------------------------------------------------------------
# Instances
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class FrameInstance:
    """One concrete object: a customer, an account, a transaction."""

    frame: str
    values: dict[str, SlotValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        slots = resolved_slots(self.frame)
        for key in self.values:
            if key not in slots:
                raise FrameError(f"{self.frame} has no slot {key!r}")
        for name, slot in slots.items():
            if name not in self.values:
                if slot.required:
                    raise FrameError(f"{self.frame}.{name} is required")
                self.values[name] = slot.default
            elif not slot.accepts(self.values[name]):
                raise FrameError(
                    f"{self.frame}.{name} = {self.values[name]!r} is not permitted "
                    f"(expected {slot.kind}"
                    f"{', one of ' + str(sorted(slot.values)) if slot.values else ''})"
                )

    # -- access ------------------------------------------------------------------------

    def get(self, slot: str) -> SlotValue:
        if slot not in resolved_slots(self.frame):
            raise FrameError(f"{self.frame} has no slot {slot!r}")
        return self.values.get(slot)

    def require(self, slot: str) -> Any:
        value = self.get(slot)
        if value is None:
            raise FrameError(f"{self.frame}.{slot} is unexpectedly unset")
        return value

    @property
    def id(self) -> str:
        return str(self.require("id"))

    def isa(self, frame_name: str) -> bool:
        """Whether this instance is of the given frame or any of its descendants."""
        return frame_name in lineage(self.frame)

    @property
    def is_scope_marker(self) -> bool:
        return any(FRAMES[name].is_scope_marker for name in lineage(self.frame))

    def __str__(self) -> str:
        return f"{self.frame}({self.values.get('id')})"


def instantiate(frame: str, **values: SlotValue) -> FrameInstance:
    """Create a validated frame instance."""
    return FrameInstance(frame=frame, values=dict(values))
