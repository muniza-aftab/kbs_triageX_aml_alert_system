# Deployment

The site is two deployments, not one:

| Piece | Lives in | Hosted on | What it is |
|---|---|---|---|
| Static front end | `frontend/` | Vercel | HTML, CSS and JavaScript. No build step, no framework. |
| JSON API | `backend/` + `src/triagex/` | Render | FastAPI over the inference engine. |

They are separate because they have different needs. The front end is a handful of files that a CDN
can serve from the edge for nothing. The API has to run Python and hold the rule base in memory, so
it needs a process. Splitting them also keeps the failure modes apart: a broken deploy of one does
not take the other down.

The two are joined by exactly one value, `window.TRIAGEX_API_BASE` in `frontend/config.js`. That is
deliberate. A single line of configuration is easier to reason about, and easier to fix at two in
the morning, than a build-time environment variable threaded through a bundler.

## Order of operations

Deploy the API first. The front end needs its URL, and the API needs the front end's domain for
CORS, so one of the two has to go first and be amended afterwards.

1. Push the repository to GitHub.
2. Deploy the API to Render. Note its URL.
3. Put that URL in `frontend/config.js` and push.
4. Deploy the front end to Vercel. Note its domain.
5. Set `ALLOWED_ORIGINS` on Render to that domain.

## The API on Render

`render.yaml` is a blueprint, so Render can read the whole service definition from the repository
rather than having it typed into a form. It declares:

- `buildCommand` installs the web dependencies from `requirements.txt`, then the package itself with
  `pip install -e .` so that `import triagex` resolves.
- `startCommand` runs `uvicorn backend.index:app` bound to `0.0.0.0` on Render's `$PORT`. Binding to
  `127.0.0.1` would make the service unreachable and the health check would fail.
- `healthCheckPath` is `/api/health`, which loads the case library and reports the rule count, so a
  passing health check means the knowledge base parsed rather than merely that the process started.
- `PYTHON_VERSION` is pinned. Without it a future default Python could change behaviour silently.

The free instance type sleeps after inactivity. The first request to a sleeping service takes
several seconds while it wakes. The front end says as much in its loading state rather than
appearing broken.

## The front end on Vercel

`vercel.json` sets `outputDirectory` to `frontend`, which tells Vercel to serve that directory as
the site root and not to look for a build. `cleanUrls` serves `/assess` rather than `/assess.html`.
`trailingSlash: false` keeps one canonical form of every path.

`framework` is `null`, which the `vercel.json` reference defines as selecting the "Other" preset.
This line is load-bearing, and its absence is the one way this deploy is known to fail. When a
repository is first imported, Vercel inspects it and stores a framework on the project. A
`requirements.txt` listing `fastapi` is enough for it to store FastAPI, after which every build runs
a Python build that looks for an ASGI entrypoint in `app.py`, `index.py`, `main.py` and similar,
finds none, and fails. The stored setting is what runs, so no amount of excluding files changes the
outcome. Pinning the preset in the repository rather than the dashboard means re-importing the
project cannot bring the failure back.

`.vercelignore` keeps the Python package, tests, documentation and `render.yaml` out of the
deployment. It applies to Git deployments as well as CLI ones: the build log reports `Found
.vercelignore` and the number of files removed. The sequence is clone first, then delete, so the
files do reach the build machine and are then discarded before the build runs. This is why it does
not prevent framework detection, which happened once at import time and is now a stored project
setting rather than something re-derived from the files on each build.

Cache headers are set per path. Fingerprinted static assets are immutable for a year. `config.js`
is explicitly `no-cache`, because it is the one file whose contents change between environments and
a stale copy would point the site at the wrong API.

## CORS

The browser calls the API from a different origin, so the API has to permit it. `ALLOWED_ORIGINS`
takes a comma-separated list of origins. Unset, it allows any origin, which is acceptable here only
because every endpoint is either static reference material or a pure function of the request body:
there is no session, no stored data and nothing to steal. A system holding anything of value should
not ship that default.

An origin is a scheme and a host, with no path and no trailing slash. `https://example.vercel.app`
is an origin; `https://example.vercel.app/` is not, and will not match.

## Verifying a deployment

Four checks, in order, because each one rules out a different failure:

1. `GET <api>/api/health` returns `200` with a rule count. The service is up and the rule base
   parsed.
2. The Vercel site loads and renders its navigation. The static deploy worked.
3. The worked examples page lists cases. The site reached the API and CORS permitted it.
4. Submitting the assessment form returns an outcome. The full request path works, including `POST`.

If step 3 fails while step 1 passes, the cause is almost always one of two things: `config.js` still
holds an empty string, or `ALLOWED_ORIGINS` does not match the site's origin exactly. The browser
console distinguishes them. A CORS rejection names the policy; a wrong base URL shows a request to
the wrong host, or to the Vercel domain itself.

## Local development

One process serves both, because `backend/index.py` mounts `frontend/` when the directory exists:

```bash
uvicorn backend.index:app --reload --port 8000
```

`config.js` holds an empty string, meaning same origin, so nothing needs changing to work locally.
That mount is unused in production, where Vercel serves the static files and the directory is not
part of the Render deploy.
