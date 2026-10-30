"""FastAPI entry point: pages, JSON API and /healthz (TECHNICAL_PLAN §6)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.fhir_client import FhirClient, patient_row
from app.labels import DISCLAIMER, SOURCE_HEADINGS, interview_line, label_for
from app.version import __version__
from contract import Finding, RunDetail, format_dose
from db import repo
from db.session import get_session


def get_fhir_client() -> Iterator[FhirClient]:
    """FastAPI dependency: a FHIR client for FHIR_BASE_URL, closed after the request."""
    client = FhirClient.from_env()
    try:
        yield client
    finally:
        client.close()


SessionDep = Annotated[Session, Depends(get_session)]
FhirDep = Annotated[FhirClient, Depends(get_fhir_client)]

app = FastAPI(title="MedRec", version=__version__)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.globals.update(
    version=__version__,
    disclaimer=DISCLAIMER,
    format_dose=format_dose,
    source_headings=SOURCE_HEADINGS,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def patient_list(request: Request, fhir: FhirDep):
    """Live patient list from FHIR; a readable 502 page when the server is unavailable."""
    try:
        patients = [patient_row(p) for p in fhir.list_patients()]
    except httpx.HTTPError as exc:
        return _message(
            request, 502, "FHIR server unavailable", f"Could not load patients from FHIR ({exc})."
        )
    return templates.TemplateResponse(request, "patients.html", {"patients": patients})


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


@app.get("/api/runs/{run_id}")
def run_json(run_id: int, session: SessionDep) -> dict:
    """Run JSON: patient, interview, records per source, rejections and findings."""
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.model_dump(mode="json")


def group_findings(findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    """(label, findings) per discrepancy type, types in first-seen order; unknown -> Other (x)."""
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        groups.setdefault(f.discrepancy_type, []).append(f)
    return [(label_for(t), fs) for t, fs in groups.items()]


def _columns(run: RunDetail) -> list[tuple[str, list]]:
    """(heading, records) for Patient-reported, FHIR and Pharmacy, in that order."""
    return [(heading, getattr(run, source)) for source, heading in SOURCE_HEADINGS.items()]


def _message(request: Request, status: int, heading: str, message: str) -> HTMLResponse:
    """A plain page for errors (missing run, FHIR unavailable) with the usual footer."""
    return templates.TemplateResponse(
        request, "message.html", {"heading": heading, "message": message}, status_code=status
    )
