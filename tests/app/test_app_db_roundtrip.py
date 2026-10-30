"""Run page and run JSON served from a real Postgres run (skipped without TEST_DATABASE_URL)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from contract import ReconciliationInput
from db import models
from db.repo import save_run
from tests.app.conftest import make_run


def test_saved_three_way_run_renders_from_the_database(db, client):
    """save_run a three-way run, then the page and JSON show it as stored."""
    expected = make_run()
    with Session(db) as session, session.begin():
        patient = models.Patient(identifier="CASE-MIXED")
        session.add(patient)
        session.flush()
        session.add(
            models.IntakeInterview(
                patient_id=patient.id,
                interview_ref="INT-1",
                taken_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
                taken_by="RN Okafor",
                informant="patient",
                no_medications=False,
            )
        )
    with Session(db) as session:
        run_id = save_run(
            session,
            expected.patient,
            "http://hapi.test/fhir",
            "1.0.0",
            ReconciliationInput(
                fhir=expected.fhir,
                pharmacy=expected.pharmacy,
                intake=expected.intake,
                rejected=expected.rejected,
            ),
            expected.findings,
        )

    html = client.get(f"/runs/{run_id}").text
    assert "Intake taken 2026-10-01 by RN Okafor (patient)" in html
    assert "Other (frequency_mismatch)" in html and "200 mg" in html

    body = client.get(f"/api/runs/{run_id}").json()
    assert [f["discrepancy_type"] for f in body["findings"]] == [
        f.discrepancy_type for f in expected.findings
    ]
    assert body["intake"][0]["name"] == "ibuprofen"
    assert body["intake_interview"]["no_medications"] is False
