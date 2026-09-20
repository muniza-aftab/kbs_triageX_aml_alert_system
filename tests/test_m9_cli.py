"""M9 acceptance tests: the command-line interface and the documentation's claims.

The CLI is the surface most people will actually touch, so it is tested for the things that make a
first impression: it runs, it exits with meaningful codes, it does not crash on a bad argument, and
it carries the synthetic-data disclaimer where someone will see it.

The documentation tests are unusual and deliberate. A README that describes commands that do not
exist, or quotes an alert id that was renamed, is worse than no README, so the claims are checked
against the code rather than trusted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triagex.cli import DISCLAIMER, build_parser, main
from triagex.data.loader import case_paths, load_library
from triagex.kb.knowledge_base import KNOWLEDGE_BASE
from triagex.kb.predicates import DISPOSITIONS

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


# --------------------------------------------------------------------------------------
# The CLI runs
# --------------------------------------------------------------------------------------


def test_parser_builds_and_requires_a_command() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


@pytest.mark.parametrize(
    "argv",
    [
        ["cases"],
        ["rules"],
        ["rules", "--layer", "2"],
        ["run", "ALT-3001"],
        ["run", "ALT-3001", "--explain"],
        ["run", "ALT-3001", "--why-not", "clear"],
        ["run", "ALT-3001", "--why-not"],
        ["run", "ALT-3001", "--how", "typology_support"],
        ["run", "ALT-3001", "--trace"],
        ["graph", "ALT-4006"],
        ["audit", "--corpus", "0"],
    ],
    ids=lambda argv: " ".join(argv))
def test_command_succeeds(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 0
    assert capsys.readouterr().out.strip(), "a command that prints nothing has not run"


def test_evidence_command_runs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evidence", "ALT-3001", "--target", "refer_to_investigation", "--depth", "2"]) == 0
    assert "effort" in capsys.readouterr().out


def test_case_can_be_referenced_by_id_stem_or_path(capsys: pytest.CaptureFixture[str]) -> None:
    for reference in (
        "ALT-3001",
        "request_structuring_no_sof_01",
        str(case_paths()[0])):
        assert main(["run", reference]) == 0
    assert capsys.readouterr().out


def test_unknown_case_exits_with_a_helpful_message() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "ALT-NOPE"])
    assert "no case matching" in str(excinfo.value)


def test_invalid_layer_is_rejected_by_the_parser() -> None:
    with pytest.raises(SystemExit):
        main(["rules", "--layer", "9"])


def test_audit_exit_code_reflects_the_knowledge_base(capsys: pytest.CaptureFixture[str]) -> None:
    # Zero means sound. If this ever returns 1, something is genuinely wrong with the rules.
    assert main(["audit", "--corpus", "0"]) == 0
    assert "rule-base audit" in capsys.readouterr().out


def test_dossier_writes_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["dossier", "ALT-3001", "-o", str(tmp_path)]) == 0
    written = list(tmp_path.glob("*.html"))
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "wrote 1 dossier" in capsys.readouterr().out


def test_dossier_all_writes_one_per_case(tmp_path: Path) -> None:
    assert main(["dossier", "all", "-o", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.html"))) == len(load_library())


def test_run_reports_agreement_with_the_case_file(capsys: pytest.CaptureFixture[str]) -> None:
    main(["run", "ALT-3001"])
    assert "as expected" in capsys.readouterr().out


def test_disclaimer_names_the_risk_plainly() -> None:
    assert "synthetic" in DISCLAIMER.lower()
    assert "real person" in DISCLAIMER


# --------------------------------------------------------------------------------------
# The documentation describes the system that exists
# --------------------------------------------------------------------------------------

README = (ROOT / "README.md").read_text(encoding="utf-8")

EXPECTED_DOCS = (
    "01-domain-primer.md",
    "02-knowledge-acquisition.md",
    "03-knowledge-model.md",
    "04-inference.md",
    "05-abstention.md",
    "06-search.md",
    "07-evaluation.md",
    "08-design-decisions.md",
    "09-limitations.md",
    "refinement-log.md")


@pytest.mark.parametrize("name", EXPECTED_DOCS)
def test_documented_file_exists(name: str) -> None:
    assert (DOCS / name).is_file()


@pytest.mark.parametrize("name", EXPECTED_DOCS)
def test_readme_links_to_every_doc(name: str) -> None:
    assert f"docs/{name}" in README


def test_every_doc_is_linked_from_the_readme() -> None:
    # The other direction: an unlinked doc is an orphan nobody will read.
    for path in DOCS.glob("*.md"):
        assert f"docs/{path.name}" in README, f"{path.name} is not linked from the README"


def test_readme_commands_all_exist() -> None:
    """A README describing commands that do not exist is worse than no README."""
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )
    assert subparsers.choices is not None
    available = set(subparsers.choices)

    for line in README.splitlines():
        stripped = line.strip()
        if not stripped.startswith("triagex "):
            continue
        command = stripped.split()[1]
        assert command in available, f"README documents unknown command {command!r}"


def test_readme_rule_count_matches_the_rule_base() -> None:
    assert f"**{len(KNOWLEDGE_BASE)} rules**" in README


def test_readme_case_ids_exist() -> None:
    ids = {case.alert_id for case in load_library()}
    for token in README.split():
        candidate = token.strip("`().:").rstrip("`")
        if candidate.startswith("ALT-"):
            assert candidate in ids, f"README references unknown case {candidate}"


def test_limitations_doc_is_not_decorative() -> None:
    """A limitations page that lists two vague caveats is a marketing document."""
    text = (DOCS / "09-limitations.md").read_text(encoding="utf-8")
    assert len(text) > 3_000
    # The specific admissions that matter most, each of which a reader could otherwise miss.
    assert "never seen a real case" in text
    assert "sensitivity" in text
    # The negative result, which a limitations page could easily leave out.
    assert "not the one the literature suggests" in text


def test_every_disposition_is_named_in_the_readme() -> None:
    for disposition in DISPOSITIONS:
        assert disposition in README


def test_gitignore_excludes_generated_output_and_the_brief() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "results/" in ignore
    assert "*.pdf" in ignore
    assert "__pycache__/" in ignore
