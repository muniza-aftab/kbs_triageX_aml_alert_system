"""The alert dossier: one self-contained HTML file per assessed case.

A terminal trace is the right medium for a developer and the wrong one for anybody else. The
dossier renders the same information as a page an analyst could actually be handed: the
decision, what supports it, what would have changed it, and what the system declined to judge.

**Self-contained by construction.** One file, inline CSS, no scripts, no fonts, no network. It
opens from disk, survives being emailed, and needs no server, which is what makes it usable
as evidence in a portfolio rather than something that has to be demonstrated live.

Light and dark are both handled through a ``prefers-color-scheme`` block rather than a toggle,
because the page has no JavaScript and should still not glare at someone at night.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from triagex.explain.why import Explanation, explain, near_misses, why_not_all
from triagex.pipeline import Assessment

OUTCOME_TONE = {
    "clear": "ok",
    "monitor": "watch",
    "request_evidence": "ask",
    "refer_to_investigation": "escalate",
    "refuse_to_decide": "abstain",
}

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #fbfaf8;
  --panel: #ffffff;
  --ink: #1b1a17;
  --muted: #6b6760;
  --line: #e4e0d8;
  --ok: #2d6a4f;
  --watch: #7a5c00;
  --ask: #1f5673;
  --escalate: #8c2f1f;
  --abstain: #4a4458;
  --accent-bg: #f3f0ea;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #17161a;
    --panel: #1f1e23;
    --ink: #eceaf0;
    --muted: #a09aa8;
    --line: #322f38;
    --ok: #74c69d;
    --watch: #e0b750;
    --ask: #7fb3d5;
    --escalate: #e08a7a;
    --abstain: #b8aecb;
    --accent-bg: #262430;
  }
}
:root[data-theme="dark"] {
  --bg: #17161a; --panel: #1f1e23; --ink: #eceaf0; --muted: #a09aa8;
  --line: #322f38; --ok: #74c69d; --watch: #e0b750; --ask: #7fb3d5;
  --escalate: #e08a7a; --abstain: #b8aecb; --accent-bg: #262430;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 16px 64px;
  background: var(--bg); color: var(--ink);
  font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 860px; margin: 0 auto; }
header { border-bottom: 1px solid var(--line); padding-bottom: 20px; margin-bottom: 28px; }
.eyebrow { font-size: 13px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h1 { font-size: 30px; margin: 6px 0 4px; letter-spacing: -.01em; }
.outcome { display: inline-block; font-weight: 650; font-size: 15px; padding: 5px 12px;
  border-radius: 999px; border: 1px solid currentColor; margin-top: 10px; }
.outcome.ok { color: var(--ok); } .outcome.watch { color: var(--watch); }
.outcome.ask { color: var(--ask); } .outcome.escalate { color: var(--escalate); }
.outcome.abstain { color: var(--abstain); }
.lede { color: var(--muted); margin-top: 14px; max-width: 62ch; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 20px 22px; margin-bottom: 20px; }
h2 { font-size: 13px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 14px; font-weight: 650; }
table { width: 100%; border-collapse: collapse; font-size: 15px; }
td { padding: 7px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
tr:last-child td { border-bottom: 0; }
td.k { color: var(--muted); width: 42%; padding-right: 16px; }
td.v { font-weight: 600; }
.reason { padding: 12px 0; border-bottom: 1px solid var(--line); }
.reason:last-child { border-bottom: 0; }
.reason .claim { font-weight: 600; }
.reason .why { color: var(--muted); font-size: 14.5px; margin-top: 3px; }
.reason .rid { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px; color: var(--muted); }
ul { margin: 0; padding-left: 20px; }
li { margin-bottom: 7px; }
.bar { height: 7px; border-radius: 4px; background: var(--accent-bg); overflow: hidden;
  margin-top: 5px; }
.bar > i { display: block; height: 100%; background: currentColor; }
.typ { margin-bottom: 14px; }
.typ:last-child { margin-bottom: 0; }
.typ .row { display: flex; justify-content: space-between; font-size: 15px; }
.typ .cf { font-variant-numeric: tabular-nums; color: var(--muted); }
pre { background: var(--accent-bg); border-radius: 8px; padding: 14px 16px; overflow-x: auto;
  font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0; }
footer { color: var(--muted); font-size: 13px; margin-top: 32px; padding-top: 18px;
  border-top: 1px solid var(--line); }
.warn { border-left: 3px solid var(--escalate); padding-left: 14px; }
@media (max-width: 560px) { body { padding: 20px 16px 48px; } h1 { font-size: 24px; } }
"""


@dataclass(frozen=True, slots=True)
class Dossier:
    alert: str
    html: str

    def write(self, directory: Path | str) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.alert}.html"
        path.write_text(self.html, encoding="utf-8")
        return path


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _section(title: str, body: str, *, classes: str = "") -> str:
    attr = f' class="{classes}"' if classes else ""
    return f"<section{attr}><h2>{_esc(title)}</h2>{body}</section>"


def _rows(pairs: tuple[tuple[str, str], ...]) -> str:
    if not pairs:
        return "<p>Nothing recorded.</p>"
    cells = "".join(
        f'<tr><td class="k">{_esc(k.replace("_", " "))}</td>'
        f'<td class="v">{_esc(v.replace("_", " "))}</td></tr>'
        for k, v in pairs
    )
    return f"<table>{cells}</table>"


def _typologies(items: tuple[tuple[str, float], ...], tone: str) -> str:
    if not items:
        return "<p>No recognised pattern reached the reporting threshold.</p>"
    blocks = []
    for name, cf in items:
        width = max(min(abs(cf), 1.0), 0.02) * 100
        blocks.append(
            f'<div class="typ"><div class="row">'
            f'<span>{_esc(name.replace("_", " "))}</span>'
            f'<span class="cf">{cf:+.2f}</span></div>'
            f'<div class="bar" style="color: var(--{tone})"><i style="width:{width:.0f}%"></i></div>'
            f"</div>"
        )
    return "".join(blocks)


def _reasons(explanation: Explanation) -> str:
    if not explanation.reasons:
        return "<p>No supporting rules fired.</p>"
    blocks = []
    for reason in explanation.reasons:
        cf = f" ({reason.certainty:+.2f})" if reason.certainty is not None else ""
        blocks.append(
            f'<div class="reason"><div class="claim">{_esc(reason.statement)}{_esc(cf)}</div>'
            f'<div class="why">{_esc(reason.rationale)}</div>'
            f'<div class="rid">{_esc(reason.rule_id)}</div></div>'
        )
    return "".join(blocks)


def _bullets(items: tuple[str, ...] | list[str], empty: str) -> str:
    if not items:
        return f"<p>{_esc(empty)}</p>"
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _what_would_change(assessment: Assessment) -> str:
    """The unmet conditions of every outcome the case did not get."""
    blocks = []
    for outcome, verdict in why_not_all(assessment).items():
        lines = [item.describe() for item in verdict.unmet]
        if verdict.blocked_by_precedence:
            lines.insert(0, f"a higher-precedence stage fired first: {verdict.blocked_by_precedence}")
        lines.extend(f"a prohibition forbids it: {p}" for p in verdict.prohibitions)
        if not lines:
            lines = ["no stage of the decision list produces this outcome"]
        blocks.append(
            f'<div class="reason"><div class="claim">{_esc(outcome.replace("_", " "))}</div>'
            + "<ul>"
            + "".join(f"<li>{_esc(line)}</li>" for line in lines)
            + "</ul></div>"
        )
    return "".join(blocks)


def build(assessment: Assessment, *, case_notes: str = "") -> Dossier:
    """Render one assessment as a self-contained HTML dossier."""
    explanation = explain(assessment)
    tone = OUTCOME_TONE.get(assessment.outcome, "abstain")
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(assessment.alert)} alert dossier</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        "<header>",
        '<div class="eyebrow">AML alert dossier</div>',
        f"<h1>{_esc(assessment.alert)}</h1>",
        f'<div class="outcome {tone}">{_esc(assessment.outcome.replace("_", " "))}</div>',
        f'<p class="lede">{_esc(explanation.headline)}</p>',
        "</header>",
    ]

    if explanation.abstention_reasons:
        parts.append(
            _section(
                "Why no decision was made",
                _bullets(explanation.abstention_reasons, ""),
                classes="warn")
        )

    parts.append(_section("Assessment", _rows(explanation.posture)))
    parts.append(_section("Patterns matched", _typologies(explanation.typologies, tone)))
    parts.append(_section("Reasoning", _reasons(explanation)))
    parts.append(_section("What would have to be different", _what_would_change(assessment)))

    misses = near_misses(assessment)
    if misses:
        parts.append(_section("Nearly concluded otherwise", _bullets(misses, "")))

    if case_notes:
        parts.append(_section("Case notes", f"<p>{_esc(case_notes)}</p>"))

    trace = assessment.trace
    parts.append(
        _section(
            "Inference trace",
            f"<pre>{_esc(trace.render())}</pre>")
    )

    parts.append(
        "<footer>Generated "
        + _esc(generated)
        + f" &middot; {len(trace.fired)} rules fired across {trace.cycles_run} cycles"
        + " &middot; Illustrative system built on synthetic data. Thresholds, jurisdictions"
        " and screening results are invented and must not be used to make a decision about a"
        " real person.</footer>"
    )
    parts.append("</div></body></html>")

    return Dossier(alert=assessment.alert, html="".join(parts))


def write_dossier(assessment: Assessment, directory: Path | str, *, case_notes: str = "") -> Path:
    return build(assessment, case_notes=case_notes).write(directory)
