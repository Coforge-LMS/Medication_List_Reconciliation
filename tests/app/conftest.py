"""App test helpers: an in-memory RunDetail served without a database."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.fhir_client import FhirClient
from app.main import app
from contract import (
    Finding,
    IntakeInterviewInfo,
    MedicationRecord,
    PatientInfo,
    Reason,
    Rejection,
    RunDetail,
)
from db import repo
from db.session import get_session

BASE = "http://hapi.test/fhir"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "hapi"

INTERVIEW = IntakeInterviewInfo(
    taken_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
    taken_by="RN Okafor",
    informant="patient",
    no_medications=False,
)


def record(source, name, dose="10", unit="mg", frequency="once daily"):
    """One accepted record for CASE-MIXED."""
    return MedicationRecord(
        patient_id="CASE-MIXED",
        source=source,
        source_record_id=f"{source}-{name}-{dose}",
        name=name,
        dose_amount=Decimal(dose),
        dose_unit=unit,
        frequency=frequency,
        date_recorded=date(2026, 9, 15),
        normalized_name=name.lower(),
    )


def make_run(**overrides) -> RunDetail:
    """A three-way CASE-MIXED run with one finding of each V1 type plus an unknown type."""
    fields = {
        "run_id": 7,
        "app_version": "1.0.0",
        "started_at": datetime(2026, 10, 30, 14, 5, tzinfo=UTC),
        "patient": PatientInfo(
            identifier="CASE-MIXED", fhir_patient_id="2178", name="Marcus Mixton"
        ),
        "intake": [record("intake", "ibuprofen", "200")],
        "fhir": [record("fhir", "metoprolol tartrate", "25"), record("fhir", "metformin", "500")],
        "pharmacy": [record("pharmacy", "metformin", "1000")],
        "rejected": [
            Rejection(
                source="pharmacy",
                source_record_id="PH-9",
                name="warfarin",
                reasons=[
                    Reason(field="dose_amount", code="unreadable_dosage", message="not a number")
                ],
            )
        ],
        "findings": [
            Finding(
                discrepancy_type="dosage_mismatch",
                medication="metformin",
                summary="FHIR dose 500 mg; pharmacy dose 1000 mg.",
                fhir_value="500 mg",
                pharmacy_value="1000 mg",
            ),
            Finding(
                discrepancy_type="missing",
                medication="ibuprofen",
                summary=(
                    "Reported by the patient; not on the FHIR list and not in pharmacy records."
                ),
                intake_value="200 mg",
            ),
            Finding(
                discrepancy_type="missing",
                medication="metoprolol",
                summary=(
                    "On the FHIR list; not reported by the patient and not in pharmacy records."
                ),
                fhir_value="25 mg",
            ),
            Finding(
                discrepancy_type="frequency_mismatch",
                medication="sertraline",
                summary="FHIR frequency QD; pharmacy frequency BID.",
                fhir_value="QD",
                pharmacy_value="BID",
            ),
        ],
        "intake_interview": INTERVIEW,
    }
    return RunDetail(**fields | overrides)


@pytest.fixture
def serve_run(monkeypatch):
    """Serve the given RunDetail (or None) from repo.get_run, with no database session."""

    def serve(run):
        """Make repo.get_run return run for its own id and None otherwise."""
        monkeypatch.setattr(
            repo, "get_run", lambda session, run_id: run if run and run.run_id == run_id else None
        )
        return run

    def no_session():
        """Stand-in for db.session.get_session."""
        yield None

    app.dependency_overrides[get_session] = no_session
    yield serve
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client():
    """TestClient for the app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def recorded_client():
    """A FhirClient served from tests/fixtures/hapi by index.json key; unknown URLs give 404.

    client.requested lists every path sent, relative to BASE with percent-encoding kept.
    """
    index = json.loads((FIXTURES / "index.json").read_text())
    requested = []

    def handler(request):
        """Serve the recorded file for an exact key, or 404 so a wrong shape fails loudly."""
        key = str(request.url).removeprefix(BASE + "/")
        requested.append(key)
        if key not in index:
            return httpx.Response(404, json={"unexpected": key})
        return httpx.Response(200, content=(FIXTURES / index[key]).read_bytes())

    client = FhirClient(BASE, transport=httpx.MockTransport(handler))
    client.requested = requested
    return client
