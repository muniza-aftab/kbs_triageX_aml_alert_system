/* Runs in <head>, before the page paints, so a saved dark theme never flashes light first.
 *
 * It also opts the page into scroll-reveal animation. Revealed content starts hidden, so if the
 * main script ever fails to load, a timer takes the page back out of that mode rather than
 * leaving sections invisible.
 */
(function () {
  var root = document.documentElement;
  try {
    var saved = JSON.parse(window.localStorage.getItem("triagex.theme"));
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (error) {
    /* no stored preference, or storage unavailable: follow the system */
  }

  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduced && "IntersectionObserver" in window) {
    root.classList.add("js-reveal");
    window.setTimeout(function () {
      if (root.dataset.revealReady !== "true") root.classList.remove("js-reveal");
    }, 2500);
  }
})();
