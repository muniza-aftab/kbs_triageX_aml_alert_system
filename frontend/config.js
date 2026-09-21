/* Where the API lives.
 *
 * Local development and any deployment that serves the API and the site from one origin need
 * nothing here: an empty string means "same origin as this page".
 *
 * When the front end is on Vercel and the API is on Render they are different origins, so set
 * this to the Render service URL, with no trailing slash:
 *
 *   window.TRIAGEX_API_BASE = "https://triagex-api.onrender.com";
 *
 * This is deliberately a plain file rather than a build-time variable. The site has no build
 * step, and one line to edit is a smaller cost than introducing a bundler to avoid editing it.
 */
(function () {
  // Served locally by uvicorn, the API is on the same origin, so no base is needed. Anywhere
  // else the page is the Vercel deployment and the API is the Render service. Deciding here
  // rather than by hand means the same file is correct in both places and cannot be committed
  // in the wrong state.
  var host = window.location.hostname;
  var local = host === "localhost" || host === "127.0.0.1" || host === "[::1]";
  window.TRIAGEX_API_BASE = local ? "" : "https://triagex-api.onrender.com";
})();
