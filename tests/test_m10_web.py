"""Tests for the plain-language layer and the website API.

The risk with a presentation layer is that it drifts from the system it presents, or quietly
overstates what the system knows. So these tests check two things beyond "does it return 200":

**That the translation is faithful.** A certainty factor must never be rendered as a
percentage, every technical identifier must remain reachable, and the plain wording must not
claim more than the rule base concluded.

**That the web layer contains no knowledge.** It validates input, calls the pipeline and renders
the result. If it ever starts deciding things, that is a second knowledge base nobody audits.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from triagex.data.loader import CASE_DIR, factbase_for, load_case, load_library
from triagex.kb.predicates import DISPOSITIONS, PREDICATES
from triagex.pipeline import assess, assess_measurements
from triagex.plain import (
    ASSESSMENT_LABELS,
    FORM,
    FORM_GROUPS,
    OUTCOMES,
    TYPOLOGY_LABELS,
    FormError,
    form_schema,
    outcome_catalogue,
    render,
    strength_word,
    to_measurements,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend"


@pytest.fixture(scope="module")
def client() -> TestClient:
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend.index import app

    return TestClient(app)


def _assess(name: str):  # type: ignore[no-untyped-def]
    case = load_case(CASE_DIR / f"{name}.toml")
    return assess(factbase_for(case), case.alert_id)


# --------------------------------------------------------------------------------------
# The translation is faithful
# --------------------------------------------------------------------------------------


def test_every_outcome_has_plain_copy() -> None:
    assert set(OUTCOMES) == set(DISPOSITIONS)
    for copy in OUTCOMES.values():
        assert copy.label and copy.meaning and copy.action
        assert len(copy.meaning.split()) >= 8, f"{copy.key} meaning is too terse to be useful"


def test_abstention_copy_does_not_read_as_a_failure() -> None:
    copy = OUTCOMES["refuse_to_decide"]
    assert "deliberate outcome" in copy.meaning
    assert "clean result" in copy.action


def test_every_typology_has_a_plain_name_and_explanation() -> None:
    from triagex.kb.predicates import TYPOLOGY_NAMES

    assert set(TYPOLOGY_LABELS) == set(TYPOLOGY_NAMES)
    for name, (label, explanation) in TYPOLOGY_LABELS.items():
        assert label and explanation, name
        assert "typology" not in label.lower(), f"{name} label still uses jargon"


def test_every_assessment_predicate_has_a_plain_label() -> None:
    for key in ASSESSMENT_LABELS:
        assert key in PREDICATES, f"{key} is not a real predicate"


def test_certainty_is_never_rendered_as_a_percentage() -> None:
    """A certainty factor is not a probability, so '86% likely' would be a false claim."""
    for value in (0.86, 0.55, 0.31, 0.05, -0.6):
        word = strength_word(value)
        assert "%" not in word
        assert not re.search(r"\d", word)


def test_strength_words_are_ordered() -> None:
    assert strength_word(0.9) == "Strongly indicated"
    assert strength_word(0.6) == "Indicated"
    assert strength_word(0.35) == "Weakly indicated"
    assert strength_word(0.05) == "Barely indicated"


def test_technical_identifiers_stay_reachable() -> None:
    """Friendly wording must not be the only thing available, or nothing is auditable."""
    plain = render(_assess("request_structuring_no_sof_01"))
    assert all(p["technical_name"] for p in plain.patterns)
    assert all(row["technical_name"] for row in plain.assessment)
    assert all(step["rule_id"] for step in plain.reasoning)
    assert plain.technical["stage"]


def test_reasoning_quotes_the_rule_rationale_verbatim() -> None:
    from triagex.kb.knowledge_base import KNOWLEDGE_BASE

    by_id = {rule.id: rule for rule in KNOWLEDGE_BASE}
    plain = render(_assess("request_structuring_no_sof_01"))
    for step in plain.reasoning:
        assert step["because"] == by_id[step["rule_id"]].rationale


def test_blockers_translate_both_the_label_and_the_value() -> None:
    """The half-translated sentence problem: a friendly label with a raw value beside it."""
    plain = render(_assess("request_structuring_no_sof_01"))
    clear = next(a for a in plain.alternatives if a["outcome_key"] == "clear")
    joined = " | ".join(clear["blockers"])
    assert "Evidence on file is Incomplete" in joined
    assert "evidence_sufficiency" not in joined
    assert "partial" not in joined


def test_missing_premises_are_named_as_checks_not_fields() -> None:
    plain = render(_assess("refuse_never_screened_01"))
    assert plain.reasons == ["Sanctions screening has not been run"]

    plain = render(_assess("refuse_kyc_never_recorded_01"))
    assert "due diligence" in plain.reasons[0].lower()


def test_prohibition_is_not_reported_twice_in_different_words() -> None:
    plain = render(_assess("request_structuring_no_sof_01"))
    clear = next(a for a in plain.alternatives if a["outcome_key"] == "clear")
    prohibitions = [b for b in clear["blockers"] if "prohibit" in b.lower()]
    assert len(prohibitions) == 1


def test_evidence_request_is_offered_only_where_it_helps() -> None:
    asked = render(_assess("request_structuring_no_sof_01"))
    assert asked.evidence_requested
    assert "source-of-funds" in asked.evidence_requested[0]["action"]

    # Nothing resolves an out-of-scope case, so no request should be manufactured.
    crypto = render(_assess("refuse_crypto_in_window_01"))
    assert crypto.evidence_requested == []


def test_no_internal_identifier_leaks_into_user_facing_prose() -> None:
    """Rule ids belong in the reference field, not in a sentence someone reads."""
    for case in load_library():
        plain = render(assess(factbase_for(case), case.alert_id))
        prose = " ".join(
            [
                plain.outcome["label"],
                plain.outcome["meaning"],
                plain.outcome["action"],
                *plain.reasons,
                *(b for alt in plain.alternatives for b in alt["blockers"]),
            ]
        )
        assert not re.search(r"\b(IND|TYP|POS|VETO|DISP)-[A-Z]+-\d+\b", prose), case.alert_id
        assert "typology_support" not in prose
        assert "cf +" not in prose


@pytest.mark.parametrize("name", [c.source_path.stem for c in load_library() if c.source_path])
def test_every_case_renders_without_error(name: str) -> None:
    plain = render(_assess(name))
    assert plain.outcome["label"]
    assert plain.alternatives


# --------------------------------------------------------------------------------------
# The form
# --------------------------------------------------------------------------------------


def test_form_covers_the_mandatory_checks() -> None:
    names = {f.name for f in FORM}
    for required in ("sanctions_signal", "kyc_status", "customer_type"):
        assert required in names, f"{required} decides whether the system can answer at all"


def test_every_field_has_a_question_and_help_text() -> None:
    for field_def in FORM:
        assert field_def.label.endswith("?") or field_def.kind == "number", field_def.name
        assert field_def.help, field_def.name
        assert field_def.group in FORM_GROUPS


def test_choice_labels_avoid_internal_vocabulary() -> None:
    for field_def in FORM:
        for choice in field_def.choices:
            assert "_" not in choice.label, f"{field_def.name}/{choice.value}"


def test_defaults_produce_a_complete_measurement_set() -> None:
    measurements = to_measurements({})
    result = assess_measurements("TEST", measurements)
    assert result.outcome in DISPOSITIONS
    # The default answers describe an unremarkable account, so they should close.
    assert result.outcome == "clear"


def test_saying_screening_was_not_run_produces_an_abstention() -> None:
    result = assess_measurements("TEST", to_measurements({"sanctions_signal": "not_checked"}))
    assert result.outcome == "refuse_to_decide"


def test_banded_answers_map_to_numbers() -> None:
    low = to_measurements({"cash_ratio": "none"})
    high = to_measurements({"cash_ratio": "all"})
    assert float(low["cash_ratio"]) < float(high["cash_ratio"])


def test_yes_no_answers_become_booleans() -> None:
    assert to_measurements({"has_crypto_transaction": "yes"})["has_crypto_transaction"] is True
    assert to_measurements({"has_crypto_transaction": "no"})["has_crypto_transaction"] is False


def test_invalid_choice_is_rejected_with_the_question_named() -> None:
    with pytest.raises(FormError, match="What kind of customer"):
        to_measurements({"customer_type": "a goldfish"})


def test_non_numeric_answer_to_a_number_question_is_rejected() -> None:
    with pytest.raises(FormError, match="needs a number"):
        to_measurements({"credit_count": "several"})


def test_schema_groups_every_field_exactly_once() -> None:
    schema = form_schema()
    listed = [f["name"] for group in schema["groups"] for f in group["fields"]]
    assert sorted(listed) == sorted(f.name for f in FORM)
    assert len(listed) == len(set(listed))


# --------------------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["rules"] > 100
    assert "real person" in body["disclaimer"]


def test_outcomes_endpoint_matches_the_catalogue(client: TestClient) -> None:
    body = client.get("/api/outcomes").json()
    assert len(body["outcomes"]) == len(outcome_catalogue())


def test_form_endpoint_is_the_single_source_of_questions(client: TestClient) -> None:
    body = client.get("/api/form").json()
    assert [g["name"] for g in body["groups"]] == list(FORM_GROUPS)


def test_cases_endpoint_lists_the_library(client: TestClient) -> None:
    body = client.get("/api/cases").json()
    assert len(body["cases"]) == len(load_library())
    assert all(row["matches_expectation"] for row in body["cases"])


def test_case_detail(client: TestClient) -> None:
    body = client.get("/api/cases/ALT-3001").json()
    assert body["outcome"]["key"] == "request_evidence"
    assert body["notes"]
    assert body["evidence_requested"]


def test_case_detail_is_case_insensitive(client: TestClient) -> None:
    assert client.get("/api/cases/alt-3001").status_code == 200


def test_unknown_case_is_a_clean_404(client: TestClient) -> None:
    response = client.get("/api/cases/ALT-9999")
    assert response.status_code == 404
    assert "No case with id" in response.json()["detail"]


def test_assess_endpoint(client: TestClient) -> None:
    response = client.post("/api/assess", json={"answers": {}})
    assert response.status_code == 200
    assert response.json()["outcome"]["key"] == "clear"


def test_assess_rejects_invalid_input_with_a_readable_message(client: TestClient) -> None:
    response = client.post("/api/assess", json={"answers": {"kyc_status": "maybe"}})
    assert response.status_code == 422
    assert "is not an option" in response.json()["detail"]


def test_rules_endpoint_exposes_provenance(client: TestClient) -> None:
    body = client.get("/api/rules?layer=2").json()
    assert body["shown"] < body["total"]
    for rule in body["rules"]:
        assert rule["source"]
        assert rule["provenance"] in {"statutory", "guidance", "reconstructed"}


def test_audit_endpoint_reports_a_clean_rule_base(client: TestClient) -> None:
    body = client.get("/api/audit").json()
    assert body["clean"] is True
    assert body["errors"] == 0


def test_static_site_is_served(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/static/css/main.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


# --------------------------------------------------------------------------------------
# The pages themselves
# --------------------------------------------------------------------------------------

PAGES = ("index.html", "assess.html", "cases.html", "case.html", "about.html")


@pytest.mark.parametrize("page", PAGES)
def test_page_exists_and_is_wellformed(page: str) -> None:
    text = (WEB / page).read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert '<html lang="en-GB">' in text
    assert "</html>" in text.strip()[-10:]


@pytest.mark.parametrize("page", PAGES)
def test_page_is_accessible_at_the_basics(page: str) -> None:
    text = (WEB / page).read_text(encoding="utf-8")
    assert 'class="skip"' in text, "needs a skip link"
    assert "<title>" in text
    assert 'name="viewport"' in text
    assert 'name="description"' in text
    assert "<main id=\"main\">" in text


@pytest.mark.parametrize("page", PAGES)
def test_every_page_carries_the_disclaimer(page: str) -> None:
    text = (WEB / page).read_text(encoding="utf-8")
    assert "Demonstration system" in text


@pytest.mark.parametrize("page", PAGES)
def test_no_framework_or_cdn_is_used(page: str) -> None:
    """The site is meant to be plain HTML, CSS and JS with no build step."""
    text = (WEB / page).read_text(encoding="utf-8").lower()
    assert "http://" not in text
    assert "cdn." not in text
    assert "unpkg" not in text
    assert "react" not in text


def test_no_page_uses_innerhtml_with_interpolation() -> None:
    """Content comes from the API, so it goes through text nodes, not string concatenation."""
    script = (WEB / "static/js/app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    for page in PAGES:
        assert "innerHTML" not in (WEB / page).read_text(encoding="utf-8")


def test_css_supports_both_colour_schemes() -> None:
    css = (WEB / "static/css/main.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert 'data-theme="dark"' in css
    assert "@media print" in css


def test_deployment_config_separates_the_two_platforms() -> None:
    """Vercel gets the static front end; Render gets the API. Neither builds the other."""
    vercel = (ROOT / "vercel.json").read_text(encoding="utf-8")
    render_yaml = (ROOT / "render.yaml").read_text(encoding="utf-8")
    ignore = (ROOT / ".vercelignore").read_text(encoding="utf-8")

    assert '"outputDirectory": "frontend"' in vercel
    assert "backend" not in vercel, "Vercel must not try to build the Python API"

    # A requirements.txt holding fastapi is enough for Vercel to store FastAPI as the project
    # framework when the repository is first imported, and it then runs a Python build that has
    # no entrypoint and fails. Removing the files with .vercelignore does not undo the stored
    # setting. Per the vercel.json reference, null selects the "Other" preset, so this line is
    # what keeps the front end a static deploy. It belongs in the repository rather than the
    # dashboard so that re-importing the project cannot resurrect the failure.
    assert json.loads(vercel)["framework"] is None, "framework must be null, meaning Other"
    assert "uvicorn backend.index:app" in render_yaml
    assert "/api/health" in render_yaml
    assert "backend/" in ignore and "src/" in ignore


def test_frontend_api_base_is_configurable() -> None:
    """The two halves live on different origins, so the base URL cannot be hard-coded."""
    config = (ROOT / "frontend/config.js").read_text(encoding="utf-8")
    assert "window.TRIAGEX_API_BASE" in config
    script = (ROOT / "frontend/static/js/app.js").read_text(encoding="utf-8")
    assert "TRIAGEX_API_BASE" in script
    assert 'const API = "/api";' not in script


def test_every_page_loads_the_api_config() -> None:
    for page in PAGES:
        text = (ROOT / "frontend" / page).read_text(encoding="utf-8")
        assert 'src="/config.js"' in text, page


def test_cors_origins_are_configurable() -> None:
    backend = (ROOT / "backend/index.py").read_text(encoding="utf-8")
    assert "ALLOWED_ORIGINS" in backend
    assert 'os.environ.get("ALLOWED_ORIGINS"' in backend


def test_requirements_only_cover_the_web_layer() -> None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "fastapi" in text
    assert "uvicorn" in text
    # The core must stay dependency-free; nothing here may creep into it.
    assert "networkx" not in text
    assert "matplotlib" not in text


def test_every_script_parses() -> None:
    """A syntax error in a module stops the whole page silently.

    The browser refuses to run the file, so nothing replaces the loading placeholders and no
    error handler ever fires, which is exactly how a broken spread in app.js once left every page
    stuck on "Loading..." while each file was still served with a 200. Serving checks cannot see
    this; only parsing can. Skipped where Node is not installed.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    scripts: list[tuple[str, str]] = [
        ("static/js/app.js", (WEB / "static/js/app.js").read_text(encoding="utf-8")),
        ("config.js", (WEB / "config.js").read_text(encoding="utf-8")),
    ]
    for page in PAGES:
        html = (WEB / page).read_text(encoding="utf-8")
        for i, body in enumerate(re.findall(r'<script type="module">(.*?)</script>', html, re.S)):
            scripts.append((f"{page} inline script {i}", body))

    with tempfile.TemporaryDirectory() as tmp:
        for name, source in scripts:
            path = Path(tmp) / "check.mjs"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            assert result.returncode == 0, f"{name} does not parse:\n{result.stderr}"
