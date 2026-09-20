"""Domain knowledge: predicates, reference data, and the rule base.

This package initialiser is deliberately empty of imports. ``kb.reference`` is a
dependency of the engine (the certainty arithmetic reads its constants), so importing
rule modules here would make ``import triagex.kb.reference`` pull in the entire rule
base and close an import cycle through ``dsl`` and ``facts``.

The assembled rule set lives in :mod:`triagex.kb.knowledge_base`.
"""
