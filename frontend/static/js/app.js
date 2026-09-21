/* TriageX, front-end behaviour.
 *
 * Vanilla ES modules, no framework, no build step. The pages are real HTML documents that work
 * as navigable links; JavaScript fills in data from the API and nothing else. If a fetch fails
 * the page says so in plain words rather than sitting empty.
 *
 * The API may be on a different origin: the static site deploys to Vercel and the API to Render.
 * `config.js` holds the base URL and is the only file that needs changing between environments.
 *
 * All rendering goes through `el()` and text nodes rather than assigning markup strings, so
 * content from the API cannot inject HTML. The dossier generator escapes for the same reason
 * server-side; taking care in one place and not the other would be pointless. A test enforces
 * that no file here assigns raw markup.
 */

/* Resolved from config.js so the site works whether the API shares its origin or not. */
const BASE = (typeof window !== "undefined" && window.TRIAGEX_API_BASE) || "";
const API = `${BASE.replace(/\/$/, "")}/api`;

/* ---------------------------------------------------------------- helpers */

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export async function api(path, options) {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let detail = `The server returned ${response.status}.`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = String(body.detail);
    } catch {
      /* a non-JSON error body is not worth reporting verbatim */
    }
    throw new Error(detail);
  }
  return response.json();
}

export function showError(target, message) {
  clear(target);
  target.append(
    el("div", { class: "error", role: "alert" }, [
      el("p", { text: message }),
      el("p", {
        class: "hint",
        text: "If this is a fresh deployment, the assessment service may still be starting up. Try again in a moment.",
      }),
    ]));
}

export function loading(target, message = "Working…") {
  clear(target);
  target.append(el("p", { class: "loading", text: message, role: "status" }));
}

/* ---------------------------------------------------------------- rendering an assessment */

export function renderOutcome(result) {
  const outcome = result.outcome;
  const block = el("div", { class: `outcome ${outcome.tone}` }, [
    el("p", { class: "outcome__label", text: outcome.label }),
    el("p", { class: "outcome__meaning", text: outcome.meaning }),
    el("p", { class: "outcome__action", text: outcome.action }),
  ]);

  if (result.reasons && result.reasons.length) {
    block.append(
      el("p", { class: "outcome__action", text: "Because:" }),
      el(
        "ul",
        {},
        result.reasons.map((reason) => el("li", { text: reason }))));
  }
  return block;
}

export function renderAssessmentTable(result) {
  if (!result.assessment.length) return null;
  const rows = result.assessment.map((row) =>
    el("tr", {}, [
      el("th", { scope: "row", title: row.help || "" }, row.label),
      el("td", { text: row.value }),
    ]));
  return el("table", { class: "definition" }, [
    el("caption", { text: "Assessment" }),
    el("tbody", {}, rows),
  ]);
}

export function renderPatterns(result) {
  const section = el("div");
  section.append(el("h2", { text: "Patterns matched" }));

  if (!result.patterns.length) {
    section.append(
      el("p", { text: "No recognised laundering pattern was supported by this activity." }));
    return section;
  }

  for (const pattern of result.patterns) {
    const width = Math.max(Math.min(Math.abs(pattern.certainty), 1) * 100, 3);
    section.append(
      el("div", { class: "field" }, [
        el("div", { class: "strength" }, [
          el("span", { class: "strength__name", text: pattern.name }),
          el("span", { class: "strength__word", text: pattern.strength }),
        ]),
        el("p", { class: "hint", text: pattern.explanation }),
        el("div", { class: "meter" }, [el("span", { style: `width:${width}%` })]),
      ]));
  }

  section.append(
    el("p", {
      class: "hint",
      text:
        "Strength is a qualitative judgement, not a probability. The system does not claim a " +
        "percentage likelihood, because the arithmetic behind it does not support one.",
    }));
  return section;
}

export function renderEvidence(result) {
  if (!result.evidence_requested || !result.evidence_requested.length) return null;
  const section = el("div");
  section.append(
    el("h2", { text: "What to ask for" }),
    el("p", {
      text:
        "The system searched every combination of evidence it could ask for and chose the " +
        "least burdensome one that would change this decision.",
    }),
    el(
      "ol",
      {},
      result.evidence_requested.map((item) => el("li", { text: item.action }))),
    el("p", {
      class: "hint",
      text:
        "This is what would change the assessment. It is not a prediction that the evidence " +
        "will be favourable.",
    }));
  return section;
}

export function renderReasoning(result) {
  if (!result.reasoning.length) return null;
  const items = result.reasoning.map((step) =>
    el("li", {}, [
      el("span", { class: "finding", text: step.finding }),
      el("span", { class: "because", text: step.because }),
      el("span", { class: "ref", text: `${step.rule_id} · ${step.source}` }),
    ]));
  return el("div", {}, [
    el("h2", { text: "How it reached that" }),
    el("p", {
      text: "Each step below is a single rule. The reference is the rule's identifier and the published source it came from.",
    }),
    el("ul", { class: "reasoning" }, items),
  ]);
}

export function renderAlternatives(result) {
  if (!result.alternatives.length) return null;
  const blocks = result.alternatives.map((alt) =>
    el("div", { class: "field" }, [
      el("h3", { text: alt.outcome }),
      el(
        "ul",
        {},
        alt.blockers.map((blocker) => el("li", { text: blocker }))),
    ]));
  return el("div", {}, [
    el("h2", { text: "Why not something else" }),
    el("p", {
      text: "Every other decision the system could have reached, and what stopped it.",
    }),
    ...blocks,
  ]);
}

export function renderTechnical(result) {
  const t = result.technical || {};
  const rows = [
    ["Deciding stage", t.stage],
    ["Rules fired", t.rules_fired],
    ["Inference cycles", t.cycles],
    ["Margin to the nearest boundary", t.margin === null ? "not applicable" : t.margin],
  ];
  const list = el("dl", { class: "meta" });
  for (const [label, value] of rows) {
    if (value === undefined || value === null) continue;
    list.append(el("div", {}, [el("dt", { text: label }), el("dd", { text: String(value) })]));
  }
  const extras = el("div", { class: "body" }, [list]);
  if (result.margin_notes && result.margin_notes.length) {
    extras.append(
      el("p", { class: "hint", text: "How close the call was:" }),
      el(
        "ul",
        {},
        result.margin_notes.map((note) => el("li", { text: note }))));
  }
  return el("details", {}, [el("summary", { text: "Technical detail" }), extras]);
}

export function renderResult(target, result, { heading } = {}) {
  clear(target);
  if (heading) target.append(el("h1", { text: heading }));
  target.append(renderOutcome(result));

  const table = renderAssessmentTable(result);
  if (table) target.append(table);

  const evidence = renderEvidence(result);
  if (evidence) target.append(evidence);

  target.append(renderPatterns(result));

  const reasoning = renderReasoning(result);
  if (reasoning) target.append(reasoning);

  const alternatives = renderAlternatives(result);
  if (alternatives) target.append(alternatives);

  target.append(renderTechnical(result));
}

/* ---------------------------------------------------------------- navigation state */

function normalisePath(pathname) {
  // Vercel is configured with cleanUrls, so it serves /assess rather than /assess.html while
  // the links in the markup keep the extension. Normalising both sides means the current-page
  // marker works in local development and in production, which it did not before.
  return (
    pathname
      .replace(/index\.html$/, "")
      .replace(/\.html$/, "")
      .replace(/\/$/, "") || "/"
  );
}

export function markCurrentNav() {
  const here = normalisePath(window.location.pathname);
  for (const link of document.querySelectorAll("nav.primary a")) {
    const target = normalisePath(new URL(link.href, window.location.origin).pathname);
    if (target === here) link.setAttribute("aria-current", "page");
  }
}

document.addEventListener("DOMContentLoaded", markCurrentNav);
