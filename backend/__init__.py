"""Web API for the TriageX.

A package rather than a loose module so ``uvicorn backend.index:app`` resolves unambiguously on
every platform, and so the type checker treats it as part of the project rather than as a stray
script.
"""
