/* Shared knowledge about how results are structured, used by the dashboard and the reports. */

import { api } from "/static/js/app.js";

/* The six stages. Numbering on screen starts at 1; `n` is the layer number the engine uses. */
export const LAYERS = [
  { n: 0, name: "Measurements", sub: "Plain arithmetic about the case" },
  { n: 1, name: "Observations", sub: "Named things that are true of the activity" },
  { n: 2, name: "Patterns", sub: "Recognised laundering methods, each with a strength" },
  { n: 3, name: "Assessment", sub: "Completeness, competence and legal triggers" },
  { n: 4, name: "Risk", sub: "The overall risk posture" },
  { n: 5, name: "Decision", sub: "One of five actions, by fixed order of precedence" },
];

let ruleLayers = null;

/** Map each rule id to the stage it concludes at, from the rule base itself. Cached per page. */
export function loadRuleLayers() {
  if (!ruleLayers) {
    ruleLayers = api("/rules")
      .then((data) => new Map(data.rules.map((rule) => [rule.id, rule.layer])))
      .catch(() => new Map());
  }
  return ruleLayers;
}

export function layerOf(ruleId, layers) {
  if (layers && layers.has(ruleId)) return layers.get(ruleId);
  // Decision stages are a decision list, not rules in the rule base, so they are not listed.
  if (/^DISP-/.test(ruleId)) return 5;
  if (/^IND-/.test(ruleId)) return 1;
  if (/^TYP-/.test(ruleId)) return 2;
  return 4;
}

export function toneForKey(key) {
  return {
    clear: "ok",
    monitor: "watch",
    request_evidence: "ask",
    refer_to_investigation: "escalate",
    refuse_to_decide: "abstain",
  }[key] || "watch";
}

export function strengthLevel(word) {
  const w = String(word || "").toLowerCase();
  if (w.includes("strong")) return 4;
  if (w.includes("moderate")) return 3;
  if (w.includes("weak")) return 2;
  return 1;
}

export function assessmentValue(result, label) {
  const row = (result.assessment || []).find((item) => item.label === label);
  return row ? row.value : null;
}

/** Restates the result in sentences, using only fields the API returned. */
export function plainSummary(result) {
  const parts = [];
  const patterns = result.patterns || [];
  if (patterns.length === 1) {
    parts.push(`The activity matches one recognised pattern: ${patterns[0].name.toLowerCase()} (${patterns[0].strength.toLowerCase()}).`);
  } else if (patterns.length > 1) {
    const names = patterns.map((p) => `${p.name.toLowerCase()} (${p.strength.toLowerCase()})`);
    parts.push(`The activity matches ${patterns.length} recognised patterns: ${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}.`);
  } else {
    parts.push("The activity does not match any recognised laundering pattern strongly enough to count.");
  }
  const risk = assessmentValue(result, "Overall risk");
  const evidence = assessmentValue(result, "Evidence on file");
  const bits = [];
  if (risk) bits.push(`overall risk is ${risk.toLowerCase()}`);
  if (evidence) bits.push(`the evidence on file is ${evidence.toLowerCase()}`);
  if (bits.length) parts.push(`Taken together, ${bits.join(", and ")}.`);
  return parts.join(" ");
}
