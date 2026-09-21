/* The results dashboard.
 *
 * One renderer for every place an assessment is shown: a fresh assessment, a worked example,
 * or an entry reopened from history. It presents what the API returned and nothing more; the
 * only derived text is phrasing that restates fields already in the result.
 *
 * A certainty factor is never shown as a percentage anywhere on the site. It is not a
 * probability, and a percentage would invite exactly that reading. Pattern strength is shown
 * by the strength wording the API provides, with a meter keyed to that wording.
 */

import {
  el, clear, icon, toneOf, outcomeBadge, toast, saveToHistory, formatDateTime,
} from "/static/js/app.js";
import { exportHtml, exportJson, printEntries } from "/static/js/report.js";
import {
  LAYERS, loadRuleLayers, layerOf, toneForKey, strengthLevel, plainSummary,
} from "/static/js/knowledge.js";

/* ---------------------------------------------------------------- small pieces */

function section(id, title, subtitle, body, extra = null) {
  return el("section", { id, class: "card", "aria-labelledby": `${id}-title` }, [
    el("div", { class: "panel-head" }, [
      el("div", {}, [
        el("h2", { id: `${id}-title`, text: title }),
        subtitle ? el("p", { text: subtitle }) : null,
      ]),
      extra,
    ]),
    body,
  ]);
}

function meter(word) {
  const level = strengthLevel(word);
  const bars = el("span", { class: "meter__bars", "aria-hidden": "true" });
  for (let i = 1; i <= 4; i += 1) bars.append(el("span", { class: i <= level ? "on" : "" }));
  return el("span", { class: "meter" }, [bars, el("span", { text: word })]);
}

/* ---------------------------------------------------------------- the dashboard */

/**
 * Render a result into `container`.
 *
 * options:
 *   reference     shown in the summary; defaults to result.alert
 *   source        "assessment" | "example" | "history"
 *   answers       [{group, label, display, edited}] for assessments, used in reports
 *   savedEntry    a history entry if this result is already saved
 *   autoSave      save to history immediately (fresh assessments)
 *   actions       extra buttons for the summary panel
 *   intro         a node shown above the dashboard (for example, why a worked example exists)
 */
export async function renderResult(container, result, options = {}) {
  const layers = await loadRuleLayers();
  const reference = options.reference || result.alert;
  const tone = toneOf(result.outcome);

  let entry = options.savedEntry || null;
  if (!entry && options.autoSave) {
    entry = saveToHistory({ source: options.source || "assessment", reference, answers: options.answers || null, result });
  }

  const reportEntry = () =>
    entry || { reference, source: options.source || "example", savedAt: new Date().toISOString(), answers: options.answers || null, result };

  clear(container);
  const root = el("div", { class: "results" });

  /* table of contents */
  const tocItems = [
    ["summary", "Summary"],
    ["explanation", "In plain words"],
    ["assessment", "Assessment"],
    ["patterns", "Patterns"],
    (result.evidence_requested || []).length ? ["evidence", "Evidence to request"] : null,
    ["reasoning", "Reasoning"],
    ["alternatives", "Why not the others"],
    ["technical", "Rules fired"],
  ].filter(Boolean);
  const toc = el("nav", { class: "results__toc", "aria-label": "Sections of this result" },
    tocItems.map(([id, text]) => el("a", { href: `#${id}`, text, dataset: { target: id } })));
  root.append(toc);

  if (options.intro) root.append(options.intro);

  /* ----- summary */
  const saveState = el("div");
  const renderSaveState = () => {
    clear(saveState);
    if (entry) {
      saveState.append(el("p", { class: "saved-note" }, [icon("check"), "Saved to session history"]));
    } else {
      saveState.append(
        el("button", {
          class: "button button--secondary button--sm",
          type: "button",
          onclick: () => {
            entry = saveToHistory({ source: options.source || "example", reference, answers: options.answers || null, result });
            if (entry) toast("Saved to history", `${reference} can be reopened from the History page.`);
            else toast("Could not save", "This browser is blocking site storage.", "alert");
            renderSaveState();
          },
        }, [icon("clock"), "Save to history"]));
    }
  };
  renderSaveState();

  const technical = result.technical || {};
  const verdict = el("section", { id: "summary", class: `card verdict ${tone}`, "aria-labelledby": "summary-title" }, [
    el("div", { class: "verdict__main" }, [
      el("div", { class: "verdict__kicker" }, [
        el("span", { text: "Recommended action" }),
        outcomeBadge(result.outcome),
      ]),
      el("h2", { id: "summary-title", class: "verdict__label", text: result.outcome.label }),
      el("p", { class: "verdict__meaning", text: result.outcome.meaning }),
      el("div", { class: "verdict__next" }, [
        icon("arrowRight"),
        el("div", {}, [el("small", { text: "Next step" }), el("p", { text: result.outcome.action })]),
      ]),
    ]),
    el("div", { class: "verdict__side" }, [
      el("dl", { class: "kv" }, [
        el("div", {}, [el("dt", { text: "Reference" }), el("dd", { class: "mono", text: reference })]),
        entry ? el("div", {}, [el("dt", { text: "Assessed" }), el("dd", { text: formatDateTime(entry.savedAt) })]) : null,
        el("div", {}, [el("dt", { text: "Rules fired" }), el("dd", { text: String(technical.rules_fired ?? "n/a") })]),
        el("div", {}, [el("dt", { text: "Decided at" }), el("dd", { class: "mono", text: technical.stage || "n/a" })]),
      ]),
      el("div", { class: "verdict__actions" }, [
        el("button", { class: "button button--sm", type: "button", onclick: () => exportHtml([reportEntry()]) }, [
          icon("file"), "Download report",
        ]),
        el("button", { class: "button button--secondary button--sm", type: "button", onclick: () => printEntries([reportEntry()]) }, [
          icon("printer"), "Save as PDF",
        ]),
        el("button", { class: "button button--secondary button--sm", type: "button", onclick: () => exportJson([reportEntry()]) }, [
          icon("braces"), "Export JSON",
        ]),
        ...(options.actions || []),
      ]),
      saveState,
    ]),
  ]);
  root.append(verdict);

  /* ----- in plain words */
  const reasons = result.reasons || [];
  root.append(
    section("explanation", "In plain words", "The decision and its basis, without the technical detail.",
      el("div", { class: "plain-words" }, [
        el("p", { text: result.outcome.headline }),
        el("p", { text: plainSummary(result), style: "margin-top: 14px; font-size: 1.05rem; color: var(--text-2)" }),
        reasons.length
          ? el("ul", {}, reasons.map((reason) => el("li", {}, [icon("check"), el("span", { text: reason })])))
          : null,
      ])));

  /* ----- assessment tiles */
  root.append(
    section("assessment", "How the case was assessed", "The intermediate conclusions the decision was drawn from.",
      el("div", { class: "tiles" }, (result.assessment || []).map((item) =>
        el("div", { class: "tile" }, [
          el("span", { class: "tile__label", text: item.label }),
          el("span", { class: "tile__value", text: item.value }),
          item.help ? el("span", { class: "tile__help", text: item.help }) : null,
        ])))));

  /* ----- patterns */
  const patterns = result.patterns || [];
  root.append(
    section("patterns", "Patterns detected", "Recognised laundering methods the activity is consistent with.",
      patterns.length
        ? el("div", { class: "grid grid--2" }, patterns.map((p) =>
            el("div", { class: "pattern" }, [
              el("div", { class: "pattern__head" }, [
                el("span", { class: "pattern__name", text: p.name }),
                meter(p.strength),
              ]),
              el("p", { text: p.explanation }),
              el("div", {}, [el("span", { class: "rule-id", text: p.technical_name })]),
            ])))
        : el("div", { class: "callout" }, [
            icon("info"),
            el("p", { text: "No recognised laundering pattern is supported strongly enough to count. That is itself a finding: it is one of the conditions for closing an alert." }),
          ])));

  /* ----- evidence */
  const evidence = result.evidence_requested || [];
  if (evidence.length) {
    root.append(
      section("evidence", "Evidence to request", "The least costly evidence that would settle the decision, found by search over every combination the bank could obtain.",
        el("ol", { class: "evidence-list" }, evidence.map((item) =>
          el("li", {}, [
            el("div", {}, [el("strong", { text: item.action }), el("div", {}, [el("span", { class: "rule-id", text: item.technical_name })])]),
            el("span", { class: "chip", text: `Relative effort ${Number(item.effort).toFixed(1)}` }),
          ])))));
  }

  /* ----- reasoning, grouped by stage */
  const reasoning = result.reasoning || [];
  const byLayer = new Map();
  for (const step of reasoning) {
    const layer = layerOf(step.rule_id, layers);
    if (!byLayer.has(layer)) byLayer.set(layer, []);
    byLayer.get(layer).push(step);
  }
  const layerBlocks = LAYERS.filter((layer) => byLayer.has(layer.n)).map((layer) => {
    const steps = byLayer.get(layer.n);
    return el("details", { class: "layer", open: true }, [
      el("summary", {}, [
        el("span", { class: "layer__num", text: String(layer.n + 1) }),
        el("span", { class: "layer__title" }, [el("strong", { text: layer.name }), el("span", { text: layer.sub })]),
        el("span", { class: "layer__count", text: `${steps.length} ${steps.length === 1 ? "finding" : "findings"}` }),
        icon("chevronDown", "chev"),
      ]),
      el("div", { class: "layer__body" }, [
        el("ol", { class: "trace" }, steps.map((step) =>
          el("li", {}, [
            el("div", { class: "trace__finding", text: step.finding }),
            el("div", { class: "trace__because", text: step.because }),
            el("div", { class: "trace__meta" }, [
              el("span", { class: "rule-id", text: step.rule_id }),
              step.source ? el("span", { text: step.source }) : null,
            ]),
          ]))),
      ]),
    ]);
  });
  root.append(
    section("reasoning", "How the decision was reached",
      "The explanation trace, stage by stage. Each finding names the rule that produced it and where that rule comes from.",
      layerBlocks.length
        ? el("div", { class: "layers" }, layerBlocks)
        : el("div", { class: `callout ${tone}` }, [
            icon("info"),
            el("div", {}, [
              el("p", {}, [
                el("strong", { text: "No rule ran to a conclusion here, by design. " }),
                "The system stopped before reasoning about the activity, because a condition it will not assume was missing.",
              ]),
              reasons.length
                ? el("p", { style: "margin-top: 6px" }, ["Stated reason: ", el("strong", { text: reasons.join("; ") })])
                : null,
            ]),
          ])));

  /* ----- alternatives */
  const alternatives = result.alternatives || [];
  const margins = result.margin_notes || [];
  root.append(
    section("alternatives", "Why not something else",
      "Every other decision the system could have reached, and exactly what stopped it.",
      el("div", {}, [
        el("div", { class: "grid grid--2" }, alternatives.map((alt) =>
          el("div", { class: `alt ${toneOf({ tone: toneForKey(alt.outcome_key) })}` }, [
            el("div", { class: "alt__head" }, [el("span", { class: "alt__dot" }), el("strong", { text: alt.outcome })]),
            el("ul", {}, (alt.blockers || []).map((blocker) =>
              el("li", {}, [icon("x"), el("span", { text: blocker })]))),
          ]))),
        margins.length
          ? el("div", { style: "margin-top: 22px" }, [
              el("h3", { text: "How close the call was" }),
              el("ul", { class: "margin-notes" }, margins.map((note) =>
                el("li", {}, [icon("scale"), el("span", { text: note })]))),
            ])
          : null,
      ])));

  /* ----- technical */
  const cited = reasoning.map((step) => ({ ...step, layer: layerOf(step.rule_id, layers) }));
  root.append(
    section("technical", "Rules fired and technical detail",
      `${cited.length} of the ${technical.rules_fired ?? "?"} rules that fired are cited in the explanation above.`,
      el("div", { class: "stack" }, [
        el("dl", { class: "kv", style: "max-width: 520px" }, [
          el("div", {}, [el("dt", { text: "Decision stage" }), el("dd", { class: "mono", text: technical.stage || "n/a" })]),
          el("div", {}, [el("dt", { text: "Rules fired" }), el("dd", { text: String(technical.rules_fired ?? "n/a") })]),
          el("div", {}, [el("dt", { text: "Inference cycles" }), el("dd", { text: String(technical.cycles ?? "n/a") })]),
          el("div", {}, [el("dt", { text: "Decision margin" }), el("dd", { class: "mono", text: technical.margin === undefined ? "n/a" : Number(technical.margin).toFixed(3) })]),
        ]),
        el("details", { class: "accordion" }, [
          el("summary", {}, [
            el("span", { text: "Rules cited in the explanation" }),
            el("span", { class: "accordion__meta", text: `${cited.length} rules` }),
            icon("chevronDown", "chev"),
          ]),
          el("div", { class: "accordion__body" }, [
            el("div", { class: "table-wrap" }, [
              el("table", {}, [
                el("thead", {}, [el("tr", {}, [
                  el("th", { scope: "col", text: "Rule" }),
                  el("th", { scope: "col", text: "Stage" }),
                  el("th", { scope: "col", text: "Concluded" }),
                  el("th", { scope: "col", text: "Source" }),
                ])]),
                el("tbody", {}, cited.map((step) => el("tr", {}, [
                  el("th", { scope: "row" }, [el("span", { class: "rule-id", text: step.rule_id })]),
                  el("td", { text: LAYERS[step.layer] ? LAYERS[step.layer].name : "" }),
                  el("td", { text: step.finding }),
                  el("td", { class: "muted", text: step.source || "" }),
                ]))),
              ]),
            ]),
          ]),
        ]),
        el("details", { class: "accordion" }, [
          el("summary", {}, [
            el("span", { text: "Technical names" }),
            el("span", { class: "accordion__meta", text: "The terms the rule base itself uses" }),
            icon("chevronDown", "chev"),
          ]),
          el("div", { class: "accordion__body" }, [
            el("div", { class: "table-wrap" }, [
              el("table", {}, [
                el("thead", {}, [el("tr", {}, [
                  el("th", { scope: "col", text: "Shown as" }),
                  el("th", { scope: "col", text: "Predicate" }),
                  el("th", { scope: "col", text: "Value" }),
                ])]),
                el("tbody", {}, (result.assessment || []).map((item) => el("tr", {}, [
                  el("th", { scope: "row", text: item.label }),
                  el("td", {}, [el("code", { text: item.technical_name })]),
                  el("td", {}, [el("code", { text: String(item.technical_value) })]),
                ]))),
              ]),
            ]),
          ]),
        ]),
      ])));

  if (result.disclaimer) {
    root.append(el("p", { class: "disclaimer-note" }, [icon("info"), el("span", { text: result.disclaimer })]));
  }

  container.append(root);
  trackToc(toc);
  return { entry: () => entry };
}

/** Highlight the table-of-contents link for the section currently in view. */
function trackToc(toc) {
  if (!("IntersectionObserver" in window)) return;
  const links = new Map([...toc.querySelectorAll("a")].map((a) => [a.dataset.target, a]));
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        for (const link of links.values()) link.classList.remove("is-active");
        const link = links.get(entry.target.id);
        if (link) {
          link.classList.add("is-active");
          toc.scrollTo({ left: Math.max(0, link.offsetLeft - 24), behavior: "smooth" });
        }
      }
    },
    { rootMargin: "-30% 0px -60% 0px" });
  for (const id of links.keys()) {
    const node = document.getElementById(id);
    if (node) observer.observe(node);
  }
}

export { LAYERS, loadRuleLayers, outcomeBadge };
