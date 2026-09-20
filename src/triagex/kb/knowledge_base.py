"""The knowledge base: every rule the system holds, assembled and validated on import.

Assembly order is presentational only, the forward chainer is data-driven and does not
care what order rules appear in. What matters is that ``RuleSet`` validates each rule as it
is constructed, so an invalid rule fails at import rather than at inference time, and
``python -c "import triagex.kb"`` is a complete check of the knowledge base's structural
integrity.

The decision list in ``disposition.py`` is deliberately *not* part of this rule set: it is
ordered knowledge evaluated first-match-wins, and mixing it into an unordered production
rule set would lose exactly the property that makes it correct.
"""

from __future__ import annotations

from triagex.dsl import RuleSet
from triagex.kb.indicators import INDICATOR_RULES
from triagex.kb.posture import ASSESSMENT_RULES, POSTURE_RULES
from triagex.kb.typologies import TYPOLOGY_RULES
from triagex.kb.veto import VETO_RULES

KNOWLEDGE_BASE: RuleSet = (
    INDICATOR_RULES + TYPOLOGY_RULES + ASSESSMENT_RULES + POSTURE_RULES + VETO_RULES
)

LAYER_SETS = {
    1: INDICATOR_RULES,
    2: TYPOLOGY_RULES,
    3: ASSESSMENT_RULES,
    4: POSTURE_RULES + VETO_RULES,
}

__all__ = [
    "ASSESSMENT_RULES",
    "INDICATOR_RULES",
    "KNOWLEDGE_BASE",
    "LAYER_SETS",
    "POSTURE_RULES",
    "TYPOLOGY_RULES",
    "VETO_RULES",
]
