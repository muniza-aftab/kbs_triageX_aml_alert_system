"""HTTP API for the website.

Deployed to Render as a long-lived web service. The front end in ``frontend/`` is a separate
static deployment on Vercel and calls this API across origins, which is why CORS is configured
rather than assumed away.

For local development this app also serves ``frontend/`` when that directory is present, so one
command gives you the whole site. In production that mount is unused: Vercel serves the static
files from its own edge network and never touches this process.

**The knowledge base is untouched by this layer.** The API validates form input, calls the same
pipeline the CLI calls, and renders the result through ``triagex.plain``. It contains no rules,
no thresholds and no decision logic, a deliberate constraint, because a web layer that starts
making judgements is a second knowledge base nobody audits.

The core package still has no runtime dependencies; FastAPI is an optional ``[web]`` extra that
only the deployment needs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # running from a checkout rather than an install
    sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from triagex.data.loader import Case, factbase_for, load_library  # noqa: E402
from triagex.kb.knowledge_base import KNOWLEDGE_BASE  # noqa: E402
from triagex.kb.predicates import PREDICATES  # noqa: E402
from triagex.pipeline import assess, assess_measurements  # noqa: E402
from triagex.plain import (  # noqa: E402
    FormError,
    form_schema,
    outcome_catalogue,
    render,
    to_measurements,
)
from triagex.verify.anomalies import audit_static  # noqa: E402

FRONTEND_DIR = ROOT / "frontend"

DISCLAIMER = (
    "Illustrative system built on synthetic data. Thresholds, country risk ratings and "
    "screening results are invented. Nothing here may be used to make a decision about a "
    "real person."
)

app = FastAPI(
    title="TriageX",
    description="Intelligent AML Alert Triage and Risk Prioritization. Transforming complex alerts into focused investigative action.",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json")

# The front end is deployed separately (Vercel) from this API (Render), so requests arrive
# cross-origin and CORS is load-bearing rather than decorative.
#
# Origins are read from ALLOWED_ORIGINS if set, so a deployment can be locked to its own Vercel
# domain. The default is permissive because this API exposes no user data and holds no state:
# every endpoint is either static reference material or a pure function of the request body.
# A system with anything worth stealing should not ship this default.
_origins_env = os.environ.get("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"])

_LIBRARY: list[Case] | None = None


def library() -> list[Case]:
    """The case library, loaded once. Parsing 24 TOML files per request would be silly."""
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = load_library()
    return _LIBRARY


def find_case(alert_id: str) -> Case:
    for case in library():
        if case.alert_id.lower() == alert_id.lower():
            return case
    raise HTTPException(status_code=404, detail=f"No case with id {alert_id!r}")


# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------


class AssessRequest(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    reference: str = Field(default="WEB-CASE", max_length=40)


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "rules": len(KNOWLEDGE_BASE),
        "cases": len(library()),
        "allowed_origins": ALLOWED_ORIGINS,
        "disclaimer": DISCLAIMER,
    }


@app.get("/api/outcomes")
def outcomes() -> dict[str, Any]:
    """The five possible decisions, in plain language."""
    return {"outcomes": outcome_catalogue(), "disclaimer": DISCLAIMER}


@app.get("/api/form")
def form() -> dict[str, Any]:
    """The assessment questions.

    Served rather than hard-coded in the page so the wording, the options and the measurements
    they set have one source of truth.
    """
    return form_schema()


@app.get("/api/cases")
def cases() -> dict[str, Any]:
    """Every worked example, with the decision it receives."""
    rows = []
    for case in library():
        result = assess(factbase_for(case), case.alert_id)
        plain = render(result, include_evidence=False)
        rows.append(
            {
                "alert": case.alert_id,
                "name": case.source_path.stem.replace("_", " ") if case.source_path else "",
                "tags": list(case.tags),
                "outcome": plain.outcome,
                "notes": case.expectation.notes.strip(),
                "expected": case.expectation.disposition,
                "matches_expectation": (
                    case.expectation.disposition is None
                    or case.expectation.disposition == result.outcome
                ),
            }
        )
    return {"cases": rows, "disclaimer": DISCLAIMER}


@app.get("/api/cases/{alert_id}")
def case_detail(alert_id: str) -> dict[str, Any]:
    case = find_case(alert_id)
    result = assess(factbase_for(case), case.alert_id)
    payload = render(result).to_dict()
    payload["notes"] = case.expectation.notes.strip()
    payload["tags"] = list(case.tags)
    payload["disclaimer"] = DISCLAIMER
    return payload


@app.post("/api/assess")
def assess_form(request: AssessRequest) -> dict[str, Any]:
    """Assess a case described through the web form."""
    try:
        measurements = to_measurements(request.answers)
    except FormError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = assess_measurements(request.reference, measurements)
    payload = render(result).to_dict()
    payload["disclaimer"] = DISCLAIMER
    return payload


@app.get("/api/rules")
def rules(layer: int | None = None) -> dict[str, Any]:
    """The rule base, with each rule's plain-language reason and its source."""
    selected = [r for r in KNOWLEDGE_BASE if layer is None or r.layer == layer]
    return {
        "total": len(KNOWLEDGE_BASE),
        "shown": len(selected),
        "rules": [
            {
                "id": rule.id,
                "layer": rule.layer,
                "reason": rule.rationale,
                "source": rule.source,
                "provenance": rule.provenance.value,
                "strength": rule.strength,
            }
            for rule in sorted(selected, key=lambda r: (r.layer, r.id))
        ],
    }


@app.get("/api/knowledge")
def knowledge() -> dict[str, Any]:
    """What the knowledge base is made of, for the About page.

    Read-only reporting over structures that already exist. Rules were already listed by
    /api/rules; the fact types (predicates) were not exposed anywhere, so a page describing the
    system could state how many rules it has but not how many kinds of fact they reason over.
    """
    predicates = sorted(PREDICATES.values(), key=lambda p: (p.layer, p.name))
    by_layer: dict[int, int] = {}
    for spec in predicates:
        by_layer[spec.layer] = by_layer.get(spec.layer, 0) + 1

    rules_by_layer: dict[int, int] = {}
    provenance: dict[str, int] = {}
    for rule in KNOWLEDGE_BASE:
        rules_by_layer[rule.layer] = rules_by_layer.get(rule.layer, 0) + 1
        provenance[rule.provenance.value] = provenance.get(rule.provenance.value, 0) + 1

    return {
        "rules": len(KNOWLEDGE_BASE),
        "fact_types": len(predicates),
        "mandatory_fact_types": sum(1 for p in predicates if p.mandatory),
        "cases": len(library()),
        "fact_types_by_layer": {str(k): v for k, v in sorted(by_layer.items())},
        "rules_by_layer": {str(k): v for k, v in sorted(rules_by_layer.items())},
        "rules_by_provenance": provenance,
        "facts": [
            {
                "name": spec.name,
                "layer": spec.layer,
                "description": spec.description,
                "mandatory": spec.mandatory,
            }
            for spec in predicates
        ],
    }


@app.get("/api/audit")
def audit() -> dict[str, Any]:
    """The static rule-base audit, so the site can show the system checking itself."""
    report = audit_static()
    return {
        "rules_checked": report.rules_checked,
        "errors": len(report.errors),
        "warnings": len(report.of_severity("warning")),
        "notes": len(report.of_severity("note")),
        "clean": report.clean,
        "findings": [
            {
                "kind": finding.kind,
                "severity": finding.severity,
                "message": finding.message,
                "rules": list(finding.rule_ids),
            }
            for finding in report.findings
        ],
    }


# --------------------------------------------------------------------------------------
# Static site
# --------------------------------------------------------------------------------------


@app.exception_handler(404)
async def not_found(request: Request, exc: Any) -> JSONResponse | FileResponse:
    """API 404s stay JSON; a mistyped page URL falls back to the site.

    The first version ignored the request path and served the HTML page for everything, so an
    API client asking for a case that does not exist received a web page with a 404 status -
    unparseable, and impossible to distinguish from a routing problem.
    """
    if request.url.path.startswith("/api/"):
        detail = getattr(exc, "detail", "Not found")
        return JSONResponse({"detail": detail}, status_code=404)

    index = FRONTEND_DIR / "index.html"
    if index.is_file():
        return FileResponse(index, status_code=404)
    return JSONResponse({"detail": "Not found"}, status_code=404)


class _RevalidatingStaticFiles(StaticFiles):
    """Static files that the browser must revalidate before reuse.

    Without a Cache-Control header a browser applies its own heuristic and may keep serving a
    stale script after the file on disk has changed, which during development looks exactly
    like a fix that did not work. no-cache still permits a cheap 304 via the ETag.
    """

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


if FRONTEND_DIR.is_dir():
    # Local convenience only. On Render the front end is not deployed alongside this service,
    # so this mount simply does not apply.
    app.mount("/", _RevalidatingStaticFiles(directory=FRONTEND_DIR, html=True), name="site")
