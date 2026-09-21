/* TriageX front end: shared runtime.
 *
 * Every page imports this module. On import it wires up the header, the theme switch, the
 * scroll reveal and the footer; the named exports are the building blocks the pages use.
 *
 * All content from the API goes into the page through text nodes (el() with `text`), never by
 * assembling markup from strings.
 */

/* ---------------------------------------------------------------- where the API lives */

const BASE = (typeof window !== "undefined" && window.TRIAGEX_API_BASE) || "";
const API = `${BASE.replace(/\/$/, "")}/api`;

export const API_ROOT = API;

/* ---------------------------------------------------------------- DOM helpers */

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "text") node.textContent = String(value);
    else if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/* ---------------------------------------------------------------- icons
 * A small stroke icon set, drawn on a 24 unit grid. Built with createElementNS so no markup
 * strings are involved.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

const ICONS = {
  check: ["M20 6 9 17l-5-5"],
  x: ["M18 6 6 18", "M6 6l12 12"],
  arrowRight: ["M5 12h14", "m13 6 6 6-6 6"],
  arrowLeft: ["M19 12H5", "m11 18-6-6 6-6"],
  chevronDown: ["m6 9 6 6 6-6"],
  chevronRight: ["m9 18 6-6-6-6"],
  download: ["M12 3v12", "m7 10 5 5 5-5", "M5 21h14"],
  printer: ["M6 9V3h12v6", "M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2", "M6 14h12v7H6z"],
  braces: ["M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1", "M16 21h1a2 2 0 0 0 2-2v-5a2 2 0 0 1 2-2 2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"],
  file: ["M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z", "M14 3v6h6", "M8 13h8", "M8 17h5"],
  clock: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 6v6l4 2"],
  trash: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"],
  info: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 16v-4", "M12 8h.01"],
  alert: ["M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z", "M12 9v4", "M12 17h.01"],
  search: ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "m21 21-4.3-4.3"],
  refresh: ["M3 12a9 9 0 0 1 15.5-6.3L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-15.5 6.3L3 16", "M3 21v-5h5"],
  edit: ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
  plus: ["M12 5v14", "M5 12h14"],
  layers: ["m12 2 10 5-10 5L2 7z", "m2 17 10 5 10-5", "m2 12 10 5 10-5"],
  flag: ["M4 22V4", "M4 4h13l-2 4 2 4H4"],
  scale: ["M12 3v18", "M5 21h14", "M3 8l4-5 4 5a4 4 0 0 1-8 0z", "M13 8l4-5 4 5a4 4 0 0 1-8 0z", "M7 3h10"],
  question: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3", "M12 17h.01"],
  shield: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", "m9 12 2 2 4-4"],
  spark: ["M12 3v4", "M12 17v4", "M3 12h4", "M17 12h4", "m5.6 5.6 2.8 2.8", "m15.6 15.6 2.8 2.8", "m5.6 18.4 2.8-2.8", "m15.6 8.4 2.8-2.8"],
  eye: ["M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"],
  book: ["M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z", "M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"],
};

export function icon(name, className = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.setAttribute("class", className);
  for (const d of ICONS[name] || []) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

/* ---------------------------------------------------------------- outcomes */

export const TONES = ["ok", "watch", "ask", "escalate", "abstain"];

export function toneOf(outcome) {
  return outcome && TONES.includes(outcome.tone) ? outcome.tone : "watch";
}

export function outcomeBadge(outcome, text) {
  return el("span", { class: `badge ${toneOf(outcome)}`, text: text || outcome.short || outcome.label });
}

/* ---------------------------------------------------------------- the API client
 *
 * The API runs on a free hosting tier that sleeps when idle, so the first request can take the
 * best part of a minute. Rather than leaving a spinner that looks broken, a request that is
 * still pending after a few seconds tells the user why, once per page.
 */

let slowNoticeShown = false;
const SLOW_AFTER_MS = 4500;
const TIMEOUT_MS = 90000;

export async function api(path, options = {}, { slowNotice = true } = {}) {
  const controller = new AbortController();
  const slowTimer = window.setTimeout(() => {
    if (slowNoticeShown || !slowNotice) return;
    slowNoticeShown = true;
    toast("Waking up the assessment service", "It sleeps when idle. The first request can take up to a minute; after that it is fast.", "clock", 12000);
  }, SLOW_AFTER_MS);
  const timeoutTimer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);

  let response;
  try {
    response = await fetch(`${API}${path}`, { ...options, signal: controller.signal });
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("The assessment service did not respond in time.");
    }
    throw new Error("Could not reach the assessment service.");
  } finally {
    window.clearTimeout(slowTimer);
    window.clearTimeout(timeoutTimer);
  }

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

/* ---------------------------------------------------------------- loading and error states */

export function showError(target, message, retry) {
  clear(target);
  target.append(
    el("div", { class: "error", role: "alert" }, [
      icon("alert"),
      el("div", {}, [
        el("p", { text: message }),
        el("p", {
          class: "hint",
          text: "If the service has been idle it may still be starting up. Trying again in a moment usually works.",
        }),
        retry
          ? el("button", { class: "button button--secondary button--sm", type: "button", onclick: retry }, [
              icon("refresh"),
              "Try again",
            ])
          : null,
      ]),
    ]));
}

export function loading(target, message = "Working…") {
  clear(target);
  target.append(el("p", { class: "loading", text: message, role: "status" }));
}

export function skeletonCards(target, count = 6, className = "") {
  clear(target);
  for (let i = 0; i < count; i += 1) {
    target.append(
      el("div", { class: `card card--flat skeleton-card ${className}`, "aria-hidden": "true" }, [
        el("div", { class: "skeleton skeleton--title" }),
        el("div", { class: "skeleton skeleton--line" }),
        el("div", { class: "skeleton skeleton--line", style: "width: 88%" }),
        el("div", { class: "skeleton skeleton--line", style: "width: 64%" }),
      ]));
  }
}

/* ---------------------------------------------------------------- toasts */

let toastHost = null;

export function toast(title, body = "", iconName = "check", duration = 4200) {
  if (!toastHost) {
    toastHost = el("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toastHost);
  }
  const node = el("div", { class: "toast" }, [
    icon(iconName),
    el("div", {}, [el("strong", { text: title }), body ? el("span", { text: body }) : null]),
  ]);
  toastHost.append(node);
  window.setTimeout(() => {
    node.classList.add("is-leaving");
    node.addEventListener("animationend", () => node.remove(), { once: true });
    window.setTimeout(() => node.remove(), 400);
  }, duration);
}

/* ---------------------------------------------------------------- confirmation dialog */

export function confirmDialog(title, message, confirmLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    const dialog = el("dialog", { class: "confirm", "aria-labelledby": "confirm-title" }, [
      el("form", { method: "dialog" }, [
        el("div", { class: "confirm__body" }, [
          el("h2", { id: "confirm-title", class: "display", text: title, style: "font-size: 1.35rem" }),
          el("p", { text: message }),
        ]),
        el("div", { class: "confirm__actions" }, [
          el("button", { class: "button button--secondary", value: "cancel", text: "Cancel" }),
          el("button", {
            class: `button ${danger ? "button--danger" : ""}`,
            value: "confirm",
            text: confirmLabel,
          }),
        ]),
      ]),
    ]);
    document.body.append(dialog);
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "confirm");
      dialog.remove();
    });
    if (typeof dialog.showModal === "function") dialog.showModal();
    else resolve(window.confirm(`${title}\n\n${message}`));
  });
}

/* ---------------------------------------------------------------- storage
 * Browser storage can be unavailable (private windows, blocked site data), so every access is
 * guarded and the site works without it; only history persistence is lost.
 */

export const store = {
  get(key, fallback = null) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  },
  remove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* nothing to do */
    }
  },
};

export const session = {
  get(key, fallback = null) {
    try {
      const raw = window.sessionStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* drafts are a convenience, not a requirement */
    }
  },
  remove(key) {
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      /* nothing to do */
    }
  },
};

/* ---------------------------------------------------------------- assessment history */

const HISTORY_KEY = "triagex.history.v1";
const HISTORY_LIMIT = 50;

export function listHistory() {
  const items = store.get(HISTORY_KEY, []);
  return Array.isArray(items) ? items : [];
}

export function getHistoryEntry(id) {
  return listHistory().find((entry) => entry.id === id) || null;
}

export function saveToHistory({ source, reference, answers = null, result }) {
  const entry = {
    id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`,
    savedAt: new Date().toISOString(),
    source,
    reference,
    answers,
    result,
  };
  const items = [entry, ...listHistory()].slice(0, HISTORY_LIMIT);
  const ok = store.set(HISTORY_KEY, items);
  updateHistoryCount();
  return ok ? entry : null;
}

export function removeFromHistory(id) {
  store.set(HISTORY_KEY, listHistory().filter((entry) => entry.id !== id));
  updateHistoryCount();
}

export function clearHistory() {
  store.remove(HISTORY_KEY);
  updateHistoryCount();
}

function updateHistoryCount() {
  const count = listHistory().length;
  for (const badge of document.querySelectorAll("[data-history-count]")) {
    badge.textContent = String(count);
    badge.hidden = count === 0;
  }
}

/* ---------------------------------------------------------------- files */

export function download(filename, content, type = "application/json") {
  const blob = new Blob([content], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(text) {
  return String(text || "assessment")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40) || "assessment";
}

/* ---------------------------------------------------------------- dates */

export function formatDateTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(iso) {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/* ---------------------------------------------------------------- navigation */

function normalisePath(pathname) {
  // Vercel is configured with cleanUrls, so it serves /assess rather than /assess.html while
  // the links in the markup keep the extension. Normalising both sides means the current-page
  // marker works in local development and in production.
  return (
    pathname
      .replace(/index\.html$/, "")
      .replace(/\.html$/, "")
      .replace(/\/$/, "") || "/"
  );
}

export function markCurrentNav() {
  const here = normalisePath(window.location.pathname);
  const alias = { "/case": "/cases" };
  const current = alias[here] || here;
  for (const link of document.querySelectorAll(".nav a")) {
    const target = normalisePath(new URL(link.href, window.location.origin).pathname);
    if (target === current) link.setAttribute("aria-current", "page");
  }
}

function initHeader() {
  const header = document.querySelector(".site-header");
  if (!header) return;

  const onScroll = () => header.classList.toggle("is-scrolled", window.scrollY > 4);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  const menu = header.querySelector(".menu-button");
  if (menu) {
    menu.addEventListener("click", () => {
      const open = header.classList.toggle("is-open");
      menu.setAttribute("aria-expanded", String(open));
    });
    for (const link of header.querySelectorAll(".nav a")) {
      link.addEventListener("click", () => {
        header.classList.remove("is-open");
        menu.setAttribute("aria-expanded", "false");
      });
    }
  }
}

/* ---------------------------------------------------------------- theme */

const THEME_KEY = "triagex.theme";

function effectiveTheme() {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function initTheme() {
  const toggle = document.querySelector(".theme-toggle");
  if (!toggle) return;
  const label = () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    toggle.setAttribute("aria-label", `Switch to ${next} theme`);
    toggle.setAttribute("title", `Switch to ${next} theme`);
  };
  label();
  toggle.addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store.set(THEME_KEY, next);
    label();
  });
}

/* ---------------------------------------------------------------- scroll reveal */

export function observeReveal(root = document) {
  const targets = root.querySelectorAll("[data-reveal]:not(.is-visible)");
  if (!document.documentElement.classList.contains("js-reveal")) return;
  if (!("IntersectionObserver" in window)) {
    for (const node of targets) node.classList.add("is-visible");
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  for (const node of targets) observer.observe(node);
}

/* ---------------------------------------------------------------- footer */

function initFooter() {
  for (const link of document.querySelectorAll("[data-api-docs]")) {
    link.setAttribute("href", `${API}/docs`);
  }
  for (const node of document.querySelectorAll("[data-year]")) {
    node.textContent = String(new Date().getFullYear());
  }
}

/* ---------------------------------------------------------------- boot */

function boot() {
  initHeader();
  initTheme();
  markCurrentNav();
  updateHistoryCount();
  initFooter();
  observeReveal();
  document.documentElement.dataset.revealReady = "true";
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
