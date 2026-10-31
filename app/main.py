"""FastAPI entry point: pages, JSON API and /healthz."""

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import service
from app.fhir_client import FhirClient, FhirError, InvalidFhirId, patient_row
from app.labels import (
    DISCLAIMER,
    SOURCE_HEADINGS,
    group_findings,
    interview_line,
    label_for,
    utc_time,
)
from app.pharmacy import PharmacyDataError
from app.version import __version__
from contract import AliasConfig, RunDetail, format_dose
from db import repo
from db.session import get_engine, get_session
from ingest.aliases import load_aliases
from ingest.fhir import PatientMappingError, map_patient


@cache
def _aliases_at(path: Path) -> AliasConfig:
    """Load and validate one alias file once."""
    return load_aliases(path)


def get_aliases() -> AliasConfig:
    """FastAPI dependency: the alias config at ALIASES_PATH (default data/aliases.json)."""
    default = Path(__file__).resolve().parents[1] / "data" / "aliases.json"
    return _aliases_at(Path(os.environ.get("ALIASES_PATH") or default))


def get_fhir_client() -> Iterator[FhirClient]:
    """FastAPI dependency: a FHIR client for FHIR_BASE_URL, closed after the request."""
    client = FhirClient.from_env()
    try:
        yield client
    finally:
        client.close()


SessionDep = Annotated[Session, Depends(get_session)]
FhirDep = Annotated[FhirClient, Depends(get_fhir_client)]
AliasesDep = Annotated[AliasConfig, Depends(get_aliases)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Refuse to start on a bad alias config; create missing tables when a DB is set."""
    get_aliases()
    if os.environ.get("DATABASE_URL"):
        repo.init_db(get_engine())
    yield


app = FastAPI(title="MedRec", version=__version__, lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.filters["utc_time"] = utc_time
templates.env.globals.update(
    version=__version__,
    disclaimer=DISCLAIMER,
    format_dose=format_dose,
    source_headings=SOURCE_HEADINGS,
)


@app.exception_handler(OperationalError)
def database_unavailable(request: Request, exc: OperationalError):
    """The app database can't be reached: a 503 page (or JSON for /api) instead of a traceback."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Database unavailable"}, status_code=503)
    return _message(
        request,
        503,
        "Database unavailable",
        "The app database can't be reached; try again shortly.",
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def patient_list(request: Request, fhir: FhirDep):
    """Live patient list from FHIR; a readable 502 page when the server is unavailable."""
    try:
        patients = [patient_row(p) for p in fhir.list_patients()]
    except (httpx.HTTPError, FhirError) as exc:
        return _message(
            request, 502, "FHIR server unavailable", f"Could not load patients from FHIR ({exc})."
        )
    return templates.TemplateResponse(request, "patients.html", {"patients": patients})


@app.get("/patients/{fhir_id}", response_class=HTMLResponse)
def patient_page(
    request: Request, fhir_id: str, session: SessionDep, fhir: FhirDep, aliases: AliasesDep
):
    """The three medication lists and rejections as they stand now, with a Run button."""
    try:
        prepared = service.collect(fhir_id, session, fhir, aliases)
    except PIPELINE_ERRORS as exc:
        return _message(request, *pipeline_error(exc))
    data = prepared.data
    return templates.TemplateResponse(
        request,
        "patient.html",
        {
            "fhir_id": fhir_id,
            "patient": prepared.patient,
            "interview": interview_line(prepared.interview),
            "columns": [
                (SOURCE_HEADINGS["intake"], data.intake or []),
                (SOURCE_HEADINGS["fhir"], data.fhir),
                (SOURCE_HEADINGS["pharmacy"], data.pharmacy),
            ],
            "rejected": data.rejected,
        },
    )


@app.post("/patients/{fhir_id}/reconcile")
def reconcile_page(
    request: Request, fhir_id: str, session: SessionDep, fhir: FhirDep, aliases: AliasesDep
):
    """Run and save a reconciliation, then 303 to its run page."""
    try:
        run_id = service.reconcile(fhir_id, session, fhir, aliases)
    except PIPELINE_ERRORS as exc:
        return _message(request, *pipeline_error(exc))
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@app.get("/patients/{fhir_id}/history", response_class=HTMLResponse)
def history_page(request: Request, fhir_id: str, session: SessionDep, fhir: FhirDep):
    """This patient's runs, newest first, keyed by the stable identifier (survives re-imports)."""
    try:
        patient = map_patient(fhir.read_patient(fhir_id))
    except PIPELINE_ERRORS as exc:
        return _message(request, *pipeline_error(exc))
    runs = repo.list_runs(session, patient.identifier)
    return templates.TemplateResponse(
        request,
        "history.html",
        {"fhir_id": fhir_id, "patient": patient, "runs": runs, "label_for": label_for},
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: int, session: SessionDep):
    """Findings grouped by type, the three medication lists, rejections and the interview."""
    run = repo.get_run(session, run_id)
    if run is None:
        return _message(request, 404, "Run not found", f"No reconciliation run {run_id}.")
    return templates.TemplateResponse(
        request,
        "run.html",
        {
            "run": run,
            "interview": interview_line(run.intake_interview),
            "groups": group_findings(run.findings),
            "headings": list(SOURCE_HEADINGS.values()),
            "columns": _columns(run),
            "rejected": run.rejected,
        },
    )


@app.post("/api/patients/{fhir_id}/reconcile", status_code=201)
def reconcile_json(fhir_id: str, session: SessionDep, fhir: FhirDep, aliases: AliasesDep) -> dict:
    """Run and save a reconciliation; 201 with the same JSON as GET /api/runs/{id}."""
    try:
        run_id = service.reconcile(fhir_id, session, fhir, aliases)
    except PIPELINE_ERRORS as exc:
        status, heading, message = pipeline_error(exc)
        raise HTTPException(status_code=status, detail=f"{heading}: {message}") from exc
    return repo.get_run(session, run_id).model_dump(mode="json")


@app.get("/api/runs/{run_id}")
def run_json(run_id: int, session: SessionDep) -> dict:
    """Run JSON: patient, interview, records per source, rejections and findings."""
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.model_dump(mode="json")


PIPELINE_ERRORS = (
    httpx.HTTPError,
    FhirError,
    InvalidFhirId,
    PatientMappingError,
    FileNotFoundError,
    PharmacyDataError,
)


def pipeline_error(exc: Exception) -> tuple[int, str, str]:
    """(status, heading, message) for a failure while fetching or preparing a patient."""
    if isinstance(exc, InvalidFhirId) or (
        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404
    ):
        return 404, "Patient not found", "The FHIR server has no such patient."
    if isinstance(exc, FhirError):
        return 502, "FHIR server unavailable", str(exc)
    if isinstance(exc, httpx.HTTPError):
        return 502, "FHIR server unavailable", f"Could not reach the FHIR server ({exc})."
    if isinstance(exc, PatientMappingError):
        return 422, "Patient cannot be reconciled", str(exc)
    return 503, "Pharmacy dataset not available", str(exc)


def _columns(run: RunDetail) -> list[tuple[str, list]]:
    """(heading, records) for Patient-reported, FHIR and Pharmacy, in that order."""
    return [(heading, getattr(run, source)) for source, heading in SOURCE_HEADINGS.items()]


def _message(request: Request, status: int, heading: str, message: str) -> HTMLResponse:
    """A plain page for errors (missing run, FHIR unavailable) with the usual footer."""
    return templates.TemplateResponse(
        request, "message.html", {"heading": heading, "message": message}, status_code=status
    )
