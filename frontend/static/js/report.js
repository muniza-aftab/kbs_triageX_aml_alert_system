/* Reports and exports.
 *
 * One document builder serves three outputs:
 *   exportHtml   a standalone, self-styled HTML file that opens anywhere, offline
 *   printEntries the same document sent to the browser's print dialog, which saves as PDF
 *   exportJson   the raw input and result, for anyone who wants the data rather than a document
 *
 * The document is assembled as DOM in a detached HTMLDocument and serialised, so no content is
 * ever concatenated into markup.
 */

import { download, slug, formatDateTime, toast } from "/static/js/app.js";
import {
  LAYERS, loadRuleLayers, layerOf, toneForKey, plainSummary,
} from "/static/js/knowledge.js";

const TONE_INK = {
  ok: "#1d7447",
  watch: "#2a5fae",
  ask: "#9a620f",
  escalate: "#b02e2c",
  abstain: "#5a4e9f",
};

const TONE_SOFT = {
  ok: "#e3f2e9",
  watch: "#e5edf9",
  ask: "#faefdc",
  escalate: "#fbe6e4",
  abstain: "#eeebf8",
};

/* Report styling. Every selector is scoped under .rpt so the same stylesheet can be dropped
   into the live page for printing without touching anything else on it. */
const REPORT_CSS = `
.rpt { --ink:#15171c; --ink-2:#434852; --ink-3:#6c717c; --line:#e1ddd3; --paper:#ffffff; --tint:#f7f6f2; --brand:#0d5c57;
  font-family: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--ink);
  font-size: 10.5pt; line-height: 1.55; background: var(--paper); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.rpt * { box-sizing: border-box; }
.rpt-page { max-width: 820px; margin: 0 auto; padding: 44px 48px 56px; }
.rpt-page + .rpt-page { break-before: page; page-break-before: always; }
.rpt h1, .rpt h2, .rpt h3 { font-family: "Source Serif 4", Georgia, "Times New Roman", serif; color: var(--ink); margin: 0; letter-spacing: -0.01em; }
.rpt h1 { font-size: 24pt; font-weight: 600; line-height: 1.1; }
.rpt h2 { font-size: 13.5pt; font-weight: 600; margin: 30px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.rpt h3 { font-size: 11pt; font-weight: 600; margin: 16px 0 6px; }
.rpt p { margin: 0 0 8px; }
.rpt-mast { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; padding-bottom: 18px; border-bottom: 2px solid var(--ink); }
.rpt-brand { font-family: "Source Serif 4", Georgia, serif; font-size: 15pt; font-weight: 650; letter-spacing: -0.02em; }
.rpt-brand span { color: var(--brand); }
.rpt-kicker { font-size: 8pt; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; }
.rpt-mast-right { text-align: right; font-size: 8.5pt; color: var(--ink-3); }
.rpt-title { margin: 26px 0 6px; }
.rpt-meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; margin: 18px 0 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.rpt-meta div { padding: 10px 12px; border-left: 1px solid var(--line); }
.rpt-meta div:first-child { border-left: 0; }
.rpt-meta dt { font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-3); font-weight: 600; }
.rpt-meta dd { margin: 2px 0 0; font-weight: 600; font-size: 9.5pt; word-break: break-word; }
.rpt-mono { font-family: "JetBrains Mono", ui-monospace, Consolas, monospace; font-size: 0.9em; }
.rpt-verdict { margin-top: 22px; padding: 18px 20px 16px 22px; border-radius: 10px; border-left: 5px solid var(--tone); background: var(--tone-soft); }
.rpt-verdict .rpt-kicker { color: var(--tone); }
.rpt-verdict-label { font-family: "Source Serif 4", Georgia, serif; font-size: 19pt; font-weight: 600; color: var(--tone); margin: 4px 0 6px; line-height: 1.15; }
.rpt-next { margin-top: 10px; padding: 9px 12px; background: #ffffff; border-radius: 6px; border: 1px solid var(--line); }
.rpt-next b { display: block; font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-3); }
.rpt-lead { font-family: "Source Serif 4", Georgia, serif; font-size: 12pt; line-height: 1.55; }
.rpt table { width: 100%; border-collapse: collapse; margin: 6px 0 4px; font-size: 9.5pt; }
.rpt th, .rpt td { text-align: left; vertical-align: top; padding: 7px 9px; border-bottom: 1px solid var(--line); }
.rpt thead th { font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.07em; color: var(--ink-3); background: var(--tint); font-weight: 650; }
.rpt tbody th { font-weight: 600; width: 38%; }
.rpt tr { break-inside: avoid; page-break-inside: avoid; }
.rpt-stage { background: var(--tint); font-weight: 650; font-size: 8.5pt; letter-spacing: 0.05em; text-transform: uppercase; color: var(--brand); }
.rpt-muted { color: var(--ink-3); }
.rpt-alt { padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; margin-bottom: 8px; break-inside: avoid; }
.rpt-alt strong { display: block; margin-bottom: 4px; }
.rpt-alt ul { margin: 0; padding-left: 18px; color: var(--ink-2); }
.rpt-foot { margin-top: 34px; padding-top: 12px; border-top: 1px solid var(--line); font-size: 8pt; color: var(--ink-3); }
.rpt-toolbar { position: sticky; top: 0; display: flex; gap: 8px; justify-content: flex-end; padding: 10px 16px; background: #15171c; }
.rpt-toolbar button { font: inherit; font-size: 9.5pt; font-weight: 600; padding: 7px 14px; border-radius: 7px; border: 0; background: #ffffff; color: #15171c; cursor: pointer; }
.rpt-badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 8pt; font-weight: 650; color: var(--tone); background: var(--tone-soft); }
@media print { .rpt-toolbar { display: none; } .rpt-page { padding: 0; max-width: none; } }
@media (max-width: 640px) { .rpt-page { padding: 24px 18px; } .rpt-meta { grid-template-columns: 1fr 1fr; } }
`;

/* ---------------------------------------------------------------- building */

function builder(doc) {
  return function h(tag, attrs = {}, children = []) {
    const node = doc.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "text") node.textContent = String(value);
      else if (key === "class") node.className = value;
      else node.setAttribute(key, String(value));
    }
    for (const child of [].concat(children)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(typeof child === "string" ? doc.createTextNode(child) : child);
    }
    return node;
  };
}

function sourceLabel(source) {
  return { assessment: "Assessment", example: "Worked example", history: "Assessment" }[source] || "Assessment";
}

function reportId(entry) {
  const stamp = new Date(entry.savedAt || Date.now());
  const pad = (n) => String(n).padStart(2, "0");
  return `TX-${stamp.getFullYear()}${pad(stamp.getMonth() + 1)}${pad(stamp.getDate())}-${pad(stamp.getHours())}${pad(stamp.getMinutes())}`;
}

function entryPage(h, entry, layers, generatedAt) {
  const result = entry.result;
  const tone = toneForKey(result.outcome.key);
  const technical = result.technical || {};

  const page = h("article", { class: "rpt-page" });

  page.append(
    h("header", { class: "rpt-mast" }, [
      h("div", {}, [
        h("div", { class: "rpt-brand" }, ["Triage", h("span", { text: "X" })]),
        h("div", { class: "rpt-kicker", text: "Alert assessment report" }),
      ]),
      h("div", { class: "rpt-mast-right" }, [
        h("div", { text: `Report ${reportId(entry)}` }),
        h("div", { text: `Generated ${formatDateTime(generatedAt)}` }),
      ]),
    ]),
    h("h1", { class: "rpt-title", text: `Alert ${entry.reference}` }),
    h("dl", { class: "rpt-meta" }, [
      h("div", {}, [h("dt", { text: "Reference" }), h("dd", { class: "rpt-mono", text: entry.reference })]),
      h("div", {}, [h("dt", { text: "Type" }), h("dd", { text: sourceLabel(entry.source) })]),
      h("div", {}, [h("dt", { text: "Assessed" }), h("dd", { text: formatDateTime(entry.savedAt) })]),
      h("div", {}, [h("dt", { text: "Rules fired" }), h("dd", { text: String(technical.rules_fired ?? "n/a") })]),
    ]),
  );

  const verdict = h("section", {
    class: "rpt-verdict",
    style: `--tone: ${TONE_INK[tone]}; --tone-soft: ${TONE_SOFT[tone]}`,
  }, [
    h("div", { class: "rpt-kicker", text: "Recommended action" }),
    h("div", { class: "rpt-verdict-label", text: result.outcome.label }),
    h("p", { text: result.outcome.meaning }),
    h("div", { class: "rpt-next" }, [h("b", { text: "Next step" }), result.outcome.action]),
  ]);
  page.append(verdict);

  page.append(
    h("h2", { text: "Summary" }),
    h("p", { class: "rpt-lead", text: result.outcome.headline }),
    h("p", { text: plainSummary(result) }),
  );
  if ((result.reasons || []).length) {
    page.append(h("ul", {}, result.reasons.map((reason) => h("li", { text: reason }))));
  }

  page.append(
    h("h2", { text: "Assessment" }),
    h("table", {}, [
      h("tbody", {}, (result.assessment || []).map((item) =>
        h("tr", {}, [h("th", { scope: "row", text: item.label }), h("td", { text: item.value })]))),
    ]),
  );

  page.append(h("h2", { text: "Patterns detected" }));
  if ((result.patterns || []).length) {
    page.append(
      h("table", {}, [
        h("thead", {}, [h("tr", {}, [
          h("th", { text: "Pattern" }), h("th", { text: "Strength" }), h("th", { text: "What it means" }),
        ])]),
        h("tbody", {}, result.patterns.map((p) => h("tr", {}, [
          h("th", { scope: "row", text: p.name }), h("td", { text: p.strength }), h("td", { text: p.explanation }),
        ]))),
      ]));
  } else {
    page.append(h("p", { class: "rpt-muted", text: "No recognised laundering pattern is supported strongly enough to count." }));
  }

  if ((result.evidence_requested || []).length) {
    page.append(
      h("h2", { text: "Evidence to request" }),
      h("table", {}, [
        h("thead", {}, [h("tr", {}, [h("th", { text: "Action" }), h("th", { text: "Relative effort" })])]),
        h("tbody", {}, result.evidence_requested.map((item) => h("tr", {}, [
          h("th", { scope: "row", text: item.action }), h("td", { text: Number(item.effort).toFixed(1) }),
        ]))),
      ]));
  }

  if (Array.isArray(entry.answers) && entry.answers.length) {
    const rows = [];
    let group = null;
    for (const answer of entry.answers) {
      if (answer.group !== group) {
        group = answer.group;
        rows.push(h("tr", {}, [h("td", { class: "rpt-stage", colspan: "2", text: group })]));
      }
      rows.push(h("tr", {}, [
        h("th", { scope: "row", text: answer.label }),
        h("td", { text: answer.edited ? `${answer.display}  (changed from default)` : answer.display }),
      ]));
    }
    page.append(h("h2", { text: "Information provided" }), h("table", {}, [h("tbody", {}, rows)]));
  }

  const steps = (result.reasoning || []).map((step) => ({ ...step, layer: layerOf(step.rule_id, layers) }));
  if (steps.length) {
    const rows = [];
    for (const layer of LAYERS) {
      const inLayer = steps.filter((step) => step.layer === layer.n);
      if (!inLayer.length) continue;
      rows.push(h("tr", {}, [h("td", { class: "rpt-stage", colspan: "3", text: `Stage ${layer.n + 1}: ${layer.name}` })]));
      for (const step of inLayer) {
        rows.push(h("tr", {}, [
          h("td", { style: "width: 34%" }, [h("strong", { text: step.finding })]),
          h("td", {}, [step.because, step.source ? h("div", { class: "rpt-muted", text: step.source }) : null]),
          h("td", { class: "rpt-mono", style: "white-space: nowrap", text: step.rule_id }),
        ]));
      }
    }
    page.append(
      h("h2", { text: "Reasoning trace" }),
      h("table", {}, [
        h("thead", {}, [h("tr", {}, [h("th", { text: "Finding" }), h("th", { text: "Because" }), h("th", { text: "Rule" })])]),
        h("tbody", {}, rows),
      ]));
  }

  if ((result.alternatives || []).length) {
    page.append(h("h2", { text: "Why not another decision" }));
    for (const alt of result.alternatives) {
      page.append(
        h("div", { class: "rpt-alt" }, [
          h("strong", { text: alt.outcome }),
          h("ul", {}, (alt.blockers || []).map((blocker) => h("li", { text: blocker }))),
        ]));
    }
  }
  if ((result.margin_notes || []).length) {
    page.append(h("h3", { text: "How close the call was" }), h("ul", {}, result.margin_notes.map((note) => h("li", { text: note }))));
  }

  page.append(
    h("h2", { text: "Technical record" }),
    h("table", {}, [
      h("tbody", {}, [
        h("tr", {}, [h("th", { scope: "row", text: "Decision stage" }), h("td", { class: "rpt-mono", text: technical.stage || "n/a" })]),
        h("tr", {}, [h("th", { scope: "row", text: "Rules fired" }), h("td", { text: String(technical.rules_fired ?? "n/a") })]),
        h("tr", {}, [h("th", { scope: "row", text: "Inference cycles" }), h("td", { text: String(technical.cycles ?? "n/a") })]),
        h("tr", {}, [h("th", { scope: "row", text: "Decision margin" }), h("td", { class: "rpt-mono", text: technical.margin === undefined ? "n/a" : Number(technical.margin).toFixed(3) })]),
      ]),
    ]),
    h("p", { class: "rpt-foot", text: result.disclaimer || "Demonstration system built on synthetic data. Not for use in decisions about real people." }),
  );
  return page;
}

function coverPage(h, entries, generatedAt) {
  const counts = new Map();
  for (const entry of entries) counts.set(entry.result.outcome.label, (counts.get(entry.result.outcome.label) || 0) + 1);

  return h("article", { class: "rpt-page" }, [
    h("header", { class: "rpt-mast" }, [
      h("div", {}, [
        h("div", { class: "rpt-brand" }, ["Triage", h("span", { text: "X" })]),
        h("div", { class: "rpt-kicker", text: "Session report" }),
      ]),
      h("div", { class: "rpt-mast-right" }, [h("div", { text: `Generated ${formatDateTime(generatedAt)}` })]),
    ]),
    h("h1", { class: "rpt-title", text: "Session summary" }),
    h("p", { class: "rpt-lead", text: `${entries.length} ${entries.length === 1 ? "assessment" : "assessments"} from this session, most recent first. Each is reported in full on the pages that follow.` }),
    h("h2", { text: "Decisions" }),
    h("table", {}, [
      h("tbody", {}, [...counts.entries()].map(([label, count]) =>
        h("tr", {}, [h("th", { scope: "row", text: label }), h("td", { text: String(count) })]))),
    ]),
    h("h2", { text: "Assessments" }),
    h("table", {}, [
      h("thead", {}, [h("tr", {}, [
        h("th", { text: "Reference" }), h("th", { text: "Assessed" }), h("th", { text: "Decision" }), h("th", { text: "Type" }),
      ])]),
      h("tbody", {}, entries.map((entry) => {
        const tone = toneForKey(entry.result.outcome.key);
        return h("tr", {}, [
          h("td", { class: "rpt-mono", text: entry.reference }),
          h("td", { text: formatDateTime(entry.savedAt) }),
          h("td", {}, [h("span", {
            class: "rpt-badge",
            style: `--tone: ${TONE_INK[tone]}; --tone-soft: ${TONE_SOFT[tone]}`,
            text: entry.result.outcome.label,
          })]),
          h("td", { text: sourceLabel(entry.source) }),
        ]);
      })),
    ]),
    h("p", { class: "rpt-foot", text: "Demonstration system built on synthetic data. Nothing in this report may be used to make a decision about a real person." }),
  ]);
}

async function buildReport(entries) {
  const layers = await loadRuleLayers();
  const generatedAt = new Date().toISOString();
  const title = entries.length === 1 ? `TriageX report: ${entries[0].reference}` : "TriageX session report";

  const doc = document.implementation.createHTMLDocument(title);
  doc.documentElement.setAttribute("lang", "en-GB");
  const h = builder(doc);

  const charset = doc.createElement("meta");
  charset.setAttribute("charset", "utf-8");
  doc.head.prepend(charset);
  doc.head.append(
    h("meta", { name: "viewport", content: "width=device-width, initial-scale=1" }),
    h("style", { text: REPORT_CSS }),
  );

  const body = h("div", { class: "rpt" });
  if (entries.length > 1) body.append(coverPage(h, entries, generatedAt));
  for (const entry of entries) body.append(entryPage(h, entry, layers, generatedAt));
  doc.body.append(body);
  doc.body.style.margin = "0";
  return { doc, body, title };
}

/* ---------------------------------------------------------------- outputs */

function fileStem(entries) {
  const date = new Date().toISOString().slice(0, 10);
  return entries.length === 1 ? `triagex-${slug(entries[0].reference)}-${date}` : `triagex-session-${date}`;
}

export async function exportHtml(entries) {
  if (!entries.length) return;
  const { doc } = await buildReport(entries);

  // A print button for whoever opens the file later. The file carries no other script.
  const toolbar = doc.createElement("div");
  toolbar.className = "rpt-toolbar";
  const button = doc.createElement("button");
  button.setAttribute("type", "button");
  button.setAttribute("onclick", "window.print()");
  button.textContent = "Print or save as PDF";
  toolbar.append(button);
  doc.body.prepend(toolbar);

  download(`${fileStem(entries)}.html`, `<!doctype html>\n${doc.documentElement.outerHTML}`, "text/html");
  toast("Report downloaded", "A self-contained HTML document that opens in any browser.", "download");
}

export async function printEntries(entries) {
  if (!entries.length) return;
  const { body } = await buildReport(entries);

  let root = document.getElementById("print-root");
  if (!root) {
    root = document.createElement("div");
    root.id = "print-root";
    document.body.append(root);
  }
  while (root.firstChild) root.removeChild(root.firstChild);
  const style = document.createElement("style");
  style.textContent = REPORT_CSS;
  root.append(style, document.importNode(body, true));

  const html = document.documentElement;
  html.classList.add("is-printing-report");
  const cleanup = () => {
    html.classList.remove("is-printing-report");
    while (root.firstChild) root.removeChild(root.firstChild);
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);
  window.print();
}

export function exportJson(entries) {
  if (!entries.length) return;
  const payload = {
    generator: "TriageX",
    format: "triagex.assessments/1",
    exported_at: new Date().toISOString(),
    count: entries.length,
    assessments: entries.map((entry) => ({
      reference: entry.reference,
      type: sourceLabel(entry.source).toLowerCase(),
      assessed_at: entry.savedAt,
      input: entry.answers || null,
      result: entry.result,
    })),
  };
  download(`${fileStem(entries)}.json`, `${JSON.stringify(payload, null, 2)}\n`, "application/json");
  toast("JSON exported", `${entries.length} ${entries.length === 1 ? "assessment" : "assessments"} with inputs and full results.`, "braces");
}
