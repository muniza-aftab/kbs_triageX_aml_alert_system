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
window.TRIAGEX_API_BASE = "https://triagex-api.onrender.com";
