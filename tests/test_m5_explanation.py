"""M5 acceptance tests: backward chaining and the explanation facility.

The explanation facility is the part of an expert system that justifies calling it one, so
these tests check the substance rather than that strings were produced. The specific claims:

* backward chaining genuinely unifies and genuinely proves, including against fact bases that
  do not already contain the conclusion;
* "why not" is answerable and *actionable*, it names the predicate and its actual value, not
  just the absence of an outcome;
* explanations are built from rule rationales, so knowledge and its justification cannot drift
  apart;
* the dossier is genuinely self-contained.
"""

from __future__ import annotations

import re

import pytest

from triagex.data.loader import CASE_DIR, factbase_for, load_case
from triagex.dsl import ANY, In
from triagex.engine.backward import BackwardChainer, Goal, GoalError, diagnose
from triagex.explain import dossier
from triagex.explain.why import (
    explain,
    how,
    near_misses,
    prove_hypothetically,
    why_not,
    why_not_all,
)
from triagex.facts import FactBase
from triagex.kb.disposition import DECISION_LIST
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.predicates import DISPOSITIONS
from triagex.pipeline import assess
from triagex.terminal import configure_stdout, supports_unicode

CHAINER = BackwardChainer(KNOWLEDGE_BASE)


def _case(name: str):  # type: ignore[no-untyped-def]
    return load_case(CASE_DIR / f"{name}.toml")


def _assessed(name: str):  # type: ignore[no-untyped-def]
    case = _case(name)
    return assess(factbase_for(case), case.alert_id), case


STRUCTURING, STRUCTURING_CASE = _assessed("request_structuring_no_sof_01")
CLEAN, CLEAN_CASE = _assessed("clear_salaried_01")
CRYPTO, CRYPTO_CASE = _assessed("refuse_crypto_in_window_01")
SANCTIONED, SANCTIONED_CASE = _assessed("refer_sanctions_confirmed_01")


# --------------------------------------------------------------------------------------
# Backward chaining
# --------------------------------------------------------------------------------------


def test_derivable_predicates_are_those_some_rule_concludes() -> None:
    assert CHAINER.is_derivable("typology")
    assert CHAINER.is_derivable("composite_risk")
    # A measurement is observed, never derived.
    assert not CHAINER.is_derivable("credit_count")
    assert not CHAINER.is_derivable("sanctions_signal")


def test_believed_facts_prove_immediately() -> None:
    goal = Goal("typology", STRUCTURING.alert, "structuring")
    proof = CHAINER.first_proof(goal, STRUCTURING.facts)
    assert proof is not None
    assert proof.is_leaf, "a believed fact is the cheapest proof and should come first"


def test_proof_can_be_rebuilt_without_the_conclusion_present() -> None:
    """The real test of backward chaining: derive it rather than look it up."""
    pruned = FactBase()
    for fact in STRUCTURING.facts:
        if fact.layer == 0:
            pruned.assert_fact(fact)

    proof = CHAINER.first_proof(Goal("typology", STRUCTURING.alert, "structuring"), pruned)
    assert proof is not None
    assert not proof.is_leaf, "nothing above layer 0 was seeded, so this had to be derived"
    assert proof.rule is not None
    assert proof.subproofs, "the derivation must rest on sub-proofs"
    used = proof.rules_used()
    assert any(rid.startswith("TYP-STRUCT") for rid in used)
    assert any(rid.startswith("IND-") for rid in used)


def test_unification_binds_the_alert_through_the_whole_proof() -> None:
    pruned = FactBase()
    for fact in STRUCTURING.facts:
        if fact.layer == 0:
            pruned.assert_fact(fact)
    proof = CHAINER.first_proof(Goal("typology", STRUCTURING.alert, ANY), pruned)
    assert proof is not None
    assert proof.bindings.get("a") == STRUCTURING.alert


def test_goals_above_the_meta_layer_cannot_be_derived_from_measurements() -> None:
    """A real boundary, asserted so it cannot regress silently.

    typology_support is computed by a function rather than a rule, so nothing concludes it and
    backward chaining cannot cross it. composite_risk depends on it, so composite_risk is
    unprovable from raw measurements even though every number it needs is present.
    """
    pruned = FactBase()
    for fact in STRUCTURING.facts:
        if fact.layer == 0:
            pruned.assert_fact(fact)

    assert not CHAINER.is_derivable("typology_support")
    assert CHAINER.first_proof(Goal("composite_risk", STRUCTURING.alert, ANY), pruned) is None
    # With the meta facts believed, as they are after a real assessment, it proves fine.
    assert CHAINER.can_prove(Goal("composite_risk", STRUCTURING.alert, ANY), STRUCTURING.facts)


def test_set_valued_goals_are_supported() -> None:
    goal = Goal("typology_support", STRUCTURING.alert, In("moderate", "strong"))
    assert CHAINER.can_prove(goal, STRUCTURING.facts)
    assert not CHAINER.can_prove(
        Goal("typology_support", STRUCTURING.alert, In("none", "weak")), STRUCTURING.facts
    )


def test_unprovable_goal_fails_cleanly() -> None:
    assert not CHAINER.can_prove(
        Goal("typology", CLEAN.alert, "sanctions_evasion"), CLEAN.facts
    )


def test_goal_subject_must_be_ground() -> None:
    from triagex.dsl import Var

    with pytest.raises(GoalError, match="must be ground"):
        Goal("typology", Var("a"), "structuring")  # type: ignore[arg-type]


def test_search_reports_its_own_cost() -> None:
    _proof, stats = CHAINER.prove_with_stats(
        Goal("composite_risk", STRUCTURING.alert, ANY), STRUCTURING.facts
    )
    assert stats.goals_attempted >= 1
    assert "goals" in stats.describe()


def test_proof_rendering_is_a_tree() -> None:
    pruned = FactBase()
    for fact in STRUCTURING.facts:
        if fact.layer == 0:
            pruned.assert_fact(fact)
    proof = CHAINER.first_proof(Goal("typology", STRUCTURING.alert, "structuring"), pruned)
    assert proof is not None
    rendered = proof.render()
    assert "typology" in rendered
    assert "  " in rendered, "nesting should be visible"


# --------------------------------------------------------------------------------------
# Diagnosis
# --------------------------------------------------------------------------------------


def test_diagnose_names_the_actual_value_not_just_the_failure() -> None:
    clear_stage = next(s for s in DECISION_LIST if s.outcome == "clear")
    unmet = diagnose(clear_stage.when, STRUCTURING.facts, STRUCTURING.alert)
    described = " | ".join(item.describe() for item in unmet)
    assert "evidence_sufficiency is partial, not sufficient" in described
    assert "typology_support is strong, not none" in described


def test_diagnose_explains_negation_as_failure_readably() -> None:
    clear_stage = next(s for s in DECISION_LIST if s.outcome == "clear")
    unmet = diagnose(clear_stage.when, STRUCTURING.facts, STRUCTURING.alert)
    blocked = [item for item in unmet if item.predicate == "disposition_blocked"]
    assert blocked, "closure is prohibited here, so the Missing premise must fail"
    # "disposition_blocked is clear, not any value" would be accurate and useless.
    assert "must not be" in blocked[0].describe()


# --------------------------------------------------------------------------------------
# Why
# --------------------------------------------------------------------------------------


def test_explanation_uses_rule_rationales_verbatim() -> None:
    explanation = explain(STRUCTURING)
    by_id = {rule.id: rule for rule in KNOWLEDGE_BASE}
    assert explanation.reasons
    for reason in explanation.reasons:
        assert reason.rationale == by_id[reason.rule_id].rationale


def test_explanation_is_ordered_by_depth_not_firing_order() -> None:
    explanation = explain(STRUCTURING)
    by_id = {rule.id: rule for rule in KNOWLEDGE_BASE}
    layers = [by_id[r.rule_id].layer for r in explanation.reasons]
    assert layers == sorted(layers), "evidence should read bottom-up, not agenda-order"


def test_explanation_reports_the_deciding_stage_rationale_as_the_headline() -> None:
    assert explain(STRUCTURING).headline == STRUCTURING.decision.stage.rationale


def test_abstention_explanation_names_what_it_could_not_handle() -> None:
    explanation = explain(CRYPTO)
    assert explanation.abstention_reasons
    assert any("chain analytics" in reason for reason in explanation.abstention_reasons)


def test_explanation_text_contains_the_outcome_and_the_evidence() -> None:
    text = explain(STRUCTURING).to_text()
    assert "REQUEST_EVIDENCE" in text
    assert "structuring" in text
    assert "IND-PROX-01" in text


def test_all_rationales_survive_a_legacy_console() -> None:
    # Rule rationales are the strings printed most often, so they are held to ASCII.
    for rule in KNOWLEDGE_BASE:
        assert rule.rationale.isascii(), f"{rule.id} rationale is not ASCII"
    for stage in DECISION_LIST:
        assert stage.rationale.isascii(), f"{stage.id} rationale is not ASCII"


# --------------------------------------------------------------------------------------
# Why not
# --------------------------------------------------------------------------------------


def test_why_not_is_actionable() -> None:
    verdict = why_not(STRUCTURING, "clear")
    assert not verdict.reachable
    text = verdict.to_text()
    assert "evidence_sufficiency is partial" in text
    assert verdict.prohibitions, "a prohibition blocks closure here and should be reported"


def test_why_not_on_the_actual_outcome_says_so() -> None:
    assert why_not(STRUCTURING, "request_evidence").reachable is True


def test_why_not_explains_precedence_when_a_stage_would_have_matched() -> None:
    # The crypto case has strong support and sufficient evidence, so it would have been
    # referred - but the scope abstention sits higher in the decision list and fired first.
    verdict = why_not(CRYPTO, "refer_to_investigation")
    assert verdict.blocked_by_precedence == "DISP-REFUSE-01 (refuse_to_decide)"


def test_why_not_covers_every_other_outcome() -> None:
    verdicts = why_not_all(STRUCTURING)
    assert set(verdicts) == set(DISPOSITIONS) - {STRUCTURING.outcome}
    for verdict in verdicts.values():
        assert verdict.to_text().strip()


def test_why_not_rejects_an_unknown_outcome() -> None:
    with pytest.raises(ValueError, match="not a disposition"):
        why_not(STRUCTURING, "definitely_launder")


# --------------------------------------------------------------------------------------
# How
# --------------------------------------------------------------------------------------


def test_how_returns_a_derivation_down_to_measurements() -> None:
    tree = how(STRUCTURING, "typology_support")
    assert "typology_support" in tree
    assert "asserted from case." in tree


def test_how_on_something_never_established() -> None:
    assert "never established" in how(CLEAN, "mandatory_escalation", "present")


def test_hypothetical_proof_distinguishes_ruled_out_from_unreachable() -> None:
    measurement = prove_hypothetically(CLEAN, "credit_count", "3")
    assert "base measurement" in measurement

    ruled_out = prove_hypothetically(CLEAN, "typology", "sanctions_evasion")
    assert "cannot be established" in ruled_out

    supported = prove_hypothetically(STRUCTURING, "typology", "structuring")
    assert "is supported" in supported


# --------------------------------------------------------------------------------------
# Near misses
# --------------------------------------------------------------------------------------


def test_near_misses_report_the_margin_to_the_deciding_threshold() -> None:
    # Defining this as "activations that lost" produced nothing for any case in the library,
    # because the rules are mutually exclusive. Margin is what actually informs a reviewer.
    misses = near_misses(STRUCTURING)
    assert misses
    assert any("margin" in miss for miss in misses)
    assert any("typology support is strong" in miss for miss in misses)


def test_near_misses_are_capped() -> None:
    assert len(near_misses(STRUCTURING, limit=2)) <= 2


# --------------------------------------------------------------------------------------
# The dossier
# --------------------------------------------------------------------------------------


def test_dossier_is_self_contained() -> None:
    page = dossier.build(STRUCTURING).html
    assert page.startswith("<!doctype html>")
    # No network dependencies of any kind: the file must open from disk forever.
    assert "<script" not in page.lower()
    assert "http://" not in page
    assert "https://" not in page
    assert "<link" not in page.lower()


def test_dossier_contains_the_decision_and_its_justification() -> None:
    page = dossier.build(STRUCTURING).html
    assert "request evidence" in page
    assert "structuring" in page
    assert "IND-PROX-01" in page
    assert "What would have to be different" in page


def test_dossier_carries_the_synthetic_data_disclaimer() -> None:
    page = dossier.build(CLEAN).html
    assert "must not be used to make a decision about a real person" in page


def test_dossier_escapes_case_content() -> None:
    page = dossier.build(CLEAN, case_notes='<script>alert("x")</script>').html
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_dossier_supports_dark_mode_without_javascript() -> None:
    page = dossier.build(CLEAN).html
    assert "prefers-color-scheme: dark" in page
    assert 'data-theme="dark"' in page


def test_dossier_writes_one_file_per_alert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = dossier.write_dossier(STRUCTURING, tmp_path, case_notes=STRUCTURING_CASE.expectation.notes)
    assert path.name == f"{STRUCTURING.alert}.html"
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_abstention_dossier_leads_with_what_it_could_not_judge() -> None:
    page = dossier.build(CRYPTO).html
    assert "Why no decision was made" in page
    index_reason = page.index("Why no decision was made")
    assert index_reason < page.index("Reasoning")


def test_every_library_case_renders(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from triagex.data.loader import load_library

    for case in load_library():
        result = assess(factbase_for(case), case.alert_id)
        page = dossier.build(result, case_notes=case.expectation.notes).html
        assert re.search(r"<h1>[^<]+</h1>", page)


# --------------------------------------------------------------------------------------
# Terminal safety
# --------------------------------------------------------------------------------------


def test_configure_stdout_is_idempotent() -> None:
    configure_stdout()
    configure_stdout()


def test_unicode_support_probe_returns_a_bool() -> None:
    assert isinstance(supports_unicode(), bool)
