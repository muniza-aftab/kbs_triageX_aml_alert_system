"""Layer 4, the veto layer: prohibitions.

Non-monotonic knowledge. These rules do not decide anything; they remove options from the
disposition layer, which then has to reach its conclusion without them.

**The asymmetry is the point.** Every rule here forbids a *permissive* outcome. There is
deliberately no rule anywhere in this file that forbids escalation, forbids abstention, or
forces a case to be cleared. The veto layer can only ever push a case towards more human
attention, never less.

That is not an accident of which rules seemed useful. It is the design constraint that makes
the layer safe to have at all: a mechanism that can override the reasoning engine is
dangerous exactly in proportion to what it can override *towards*. A test enforces it, every
rule in this module must conclude ``disposition_blocked`` with a value in
:data:`PERMISSIVE_OUTCOMES`.
"""

from __future__ import annotations

from typing import Final

from triagex.dsl import Conclude, Has, In, Provenance, Rule, RuleSet, Var

A = Var("a")

PERMISSIVE_OUTCOMES: Final[frozenset[str]] = frozenset({"clear", "monitor"})
"""The only outcomes a prohibition may block. See the module docstring."""


def _v(
    id: str,  # noqa: A002
    *,
    when: tuple[object, ...],
    blocks: str,
    source: str,
    rationale: str,
    provenance: Provenance = Provenance.GUIDANCE,
    priority: int = 100) -> Rule:
    if blocks not in PERMISSIVE_OUTCOMES:
        raise ValueError(
            f"{id}: the veto layer may only block permissive outcomes "
            f"({sorted(PERMISSIVE_OUTCOMES)}), never {blocks!r}"
        )
    return Rule(
        id=id,
        layer=4,
        when=when,  # type: ignore[arg-type]
        then=Conclude("disposition_blocked", A, blocks),
        source=source,
        provenance=provenance,
        rationale=rationale,
        priority=priority)


_PROHIBITIONS = (
    _v(
        "VETO-CLEAR-01",
        when=(Has("mandatory_escalation", A, "present"),),
        blocks="clear",
        source="Sanctions and Anti-Money Laundering Act 2018; OFSI reporting obligations",
        provenance=Provenance.STATUTORY,
        rationale=(
            "A case carrying a designation match cannot be closed by this system under any "
            "combination of other evidence."
        )),
    _v(
        "VETO-MONITOR-01",
        when=(Has("mandatory_escalation", A, "present"),),
        blocks="monitor",
        source="Sanctions and Anti-Money Laundering Act 2018; OFSI reporting obligations",
        provenance=Provenance.STATUTORY,
        rationale=(
            "Nor can it be quietly watched. A designation match needs a decision by someone "
            "with the authority to report it."
        )),
    _v(
        "VETO-CLEAR-02",
        when=(Has("typology_support", A, "strong"),),
        blocks="clear",
        source="JMLSG Part I; FCA Financial Crime Guide (April 2025)",
        rationale=(
            "Strong typology support forecloses closure. If the disposition layer cannot "
            "justify escalating, the correct outcome is to ask for more, not to close."
        )),
    _v(
        "VETO-CLEAR-03",
        when=(Has("evidence_sufficiency", A, "insufficient"),),
        blocks="clear",
        source="MLR 2017 reg. 27 (ongoing monitoring)",
        provenance=Provenance.STATUTORY,
        rationale=(
            "A case cannot be closed on evidence the firm itself considers inadequate. "
            "Lapsed due diligence means the customer is not currently known."
        )),
    _v(
        "VETO-CLEAR-04",
        when=(
            Has("scope_state", A, "boundary"),
            Has("typology_support", A, In("moderate", "strong"))),
        blocks="clear",
        source="FATF Recommendation 1 (risk-based approach)",
        rationale=(
            "Where part of the case could not be assessed and what *was* assessed looks "
            "suspicious, closure would rest on the untested part."
        )),
    _v(
        "VETO-MONITOR-02",
        when=(Has("evidence_sufficiency", A, "insufficient"),),
        blocks="monitor",
        source="MLR 2017 reg. 27 (ongoing monitoring)",
        provenance=Provenance.STATUTORY,
        rationale=(
            "Monitoring a customer whose due diligence has lapsed is watching without "
            "knowing what is being watched; the diligence has to be refreshed first."
        )))


VETO_RULES = RuleSet(_PROHIBITIONS, name="veto")
