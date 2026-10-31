"""Pages and JSON served from real Postgres runs (skipped without TEST_DATABASE_URL)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.labels import DISCLAIMER
from app.main import app, get_fhir_client
from contract import ReconciliationInput
from db import models
from db.repo import save_run
from db.seed import seed
from tests.app.conftest import INTAKE_DIR, make_run
from tests.app.test_app_pdf import pages


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


def test_seeded_case_mixed_reconciles_end_to_end(db, client, recorded_client):
    """Seed the committed intake, reconcile CASE-MIXED over recorded FHIR, then read it back."""
    with Session(db) as session:
        seed(session, INTAKE_DIR)
    app.dependency_overrides[get_fhir_client] = lambda: recorded_client
    try:
        response = client.post("/api/patients/2178/reconcile")
        assert response.status_code == 201
        body = response.json()
        assert len(body["findings"]) == 7  # data/README's CASE-MIXED table
        assert body["intake_interview"]["taken_by"] == "RN Okafor"
        assert {r["source"] for r in body["rejected"]} == {"pharmacy", "intake"}

        run_page = client.get(f"/runs/{body['run_id']}").text
        assert "Duplicate medication" in run_page and "Dosage mismatch" in run_page
        assert "Intake taken 2026-10-28 by RN Okafor (patient)" in run_page

        assert client.get("/runs/99999999999999999999").status_code == 404

        history = client.get("/patients/2178/history").text
        assert f'href="/runs/{body["run_id"]}"' in history

        report = client.get(f"/runs/{body['run_id']}/report.pdf")
        assert report.status_code == 200
        pdf_text = " ".join(pages(report.content))
        assert "Marcus Mixton" in pdf_text
        assert "Intake taken 2026-10-28 by RN Okafor (patient)" in pdf_text
        assert "Ibuprofen 200 mg" in pdf_text  # a patient-reported record
        assert DISCLAIMER in pdf_text
    finally:
        app.dependency_overrides.pop(get_fhir_client, None)
