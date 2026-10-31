import io
from collections import Counter
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.labels import DISCLAIMER
from app.version import __version__
from db import models, repo
from db.seed import seed

INTAKE_DIR = Path(__file__).resolve().parents[2] / "data" / "intake"
INTERVIEW_LINE = "Intake taken 2026-10-28 by RN Okafor (patient)"


def test_case_mixed_detail_reconcile_history_and_pdf(db, e2e_client):
    """The seeded three-source case produces the seven documented findings and a saved PDF."""
    client, requested = e2e_client
    with Session(db) as session:
        seed(session, INTAKE_DIR)

    detail = client.get("/patients/2178")
    assert detail.status_code == 200
    assert INTERVIEW_LINE in detail.text
    assert 'action="/patients/2178/reconcile"' in detail.text
    for heading in ("Patient-reported", "FHIR", "Pharmacy"):
        assert f"<h3>{heading}</h3>" in detail.text
    assert "0.5 g" in detail.text and "200 mg" in detail.text
    assert DISCLAIMER in detail.text

    response = client.post("/patients/2178/reconcile", follow_redirects=False)
    assert response.status_code == 303
    run_url = response.headers["location"]
    assert run_url.startswith("/runs/")
    run_id = int(run_url.rsplit("/", 1)[1])

    # A fresh session/connection sees only committed data, including every source snapshot.
    with Session(db) as session:
        run = repo.get_run(session, run_id)
        assert run is not None
        assert run.patient.identifier == "CASE-MIXED"
        assert run.patient.fhir_patient_id == "2178"
        assert run.app_version == __version__
        assert run.intake_interview.taken_by == "RN Okafor"
        assert not run.intake_interview.no_medications
        assert (len(run.fhir), len(run.pharmacy), len(run.intake)) == (5, 5, 5)
        assert len(run.rejected) == 6
        assert Counter(r.source for r in run.rejected) == {"pharmacy": 5, "intake": 1}
        assert session.scalar(select(func.count()).select_from(models.ReconciliationRun)) == 1
        for model, expected in (
            (models.MedicationRecord, 15),
            (models.Finding, 7),
            (models.RejectedRecord, 6),
        ):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.run_id == run_id)
                )
                == expected
            )
        stored_run = session.get(models.ReconciliationRun, run_id)
        interview = session.get(models.IntakeInterview, stored_run.intake_interview_id)
        patient = session.get(models.Patient, stored_run.patient_id)
        assert interview.patient_id == patient.id
        assert patient.fhir_base_url == "http://hapi.test/fhir"
        assert all(r.source_record_id and r.raw for r in run.fhir + run.pharmacy + run.intake)

    findings = {(f.discrepancy_type, f.medication): f for f in run.findings}
    assert len(run.findings) == len(findings) == 7
    assert set(findings) == {
        ("duplicate", "acetaminophen"),
        ("duplicate", "sertraline"),
        ("dosage_mismatch", "acetaminophen"),
        ("missing", "ibuprofen"),
        ("missing", "metoprolol"),
        ("missing", "omeprazole"),
        ("missing", "warfarin"),
    }
    for medication, present, absent, rejected in (
        ("ibuprofen", ["intake"], ["fhir", "pharmacy"], 0),
        ("metoprolol", ["fhir"], ["intake", "pharmacy"], 0),
        ("omeprazole", ["pharmacy"], ["intake", "fhir"], 0),
        ("warfarin", ["fhir"], ["intake", "pharmacy"], 2),
    ):
        finding = findings["missing", medication]
        assert finding.details["present_in"] == present
        assert finding.details["missing_from"] == absent
        assert finding.details["rejected_count"] == rejected
    dose = findings["dosage_mismatch", "acetaminophen"]
    assert (dose.intake_value, dose.fhir_value, dose.pharmacy_value) == (
        "1000 mg",
        "500 mg",
        "500 mg, 1000 mg",
    )
    # No metformin finding: patient-reported 0.5 g equals the other sources' 500 mg.
    assert all(f.medication != "metformin" for f in run.findings)

    page = client.get(run_url)
    assert page.status_code == 200
    assert INTERVIEW_LINE in page.text
    assert "0.5 g" in page.text and "200 mg" in page.text
    for label in ("Duplicate medication", "Missing medication", "Dosage mismatch"):
        assert f"<h3>{label}</h3>" in page.text
    assert f'href="{run_url}/report.pdf"' in page.text
    assert DISCLAIMER in page.text

    history = client.get("/patients/2178/history")
    assert history.status_code == 200
    assert f'href="{run_url}"' in history.text
    assert "CASE-MIXED" in history.text and __version__ in history.text

    # Saved views and the report must not refetch live FHIR data.
    assert requested == [
        "Patient/2178",
        "MedicationRequest?patient=2178&status=active",
        "Patient/2178",
        "MedicationRequest?patient=2178&status=active",
        "Patient/2178",
    ]
    requested.clear()
    report = client.get(f"{run_url}/report.pdf")
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"
    assert report.headers["content-disposition"] == (
        f'attachment; filename="reconciliation-run-{run_id}.pdf"'
    )
    assert report.content.startswith(b"%PDF-")
    text = " ".join(
        " ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(report.content)).pages
    )
    assert "CASE-MIXED" in text and INTERVIEW_LINE in text
    intake_table = text.split("Patient-reported medications", 1)[1].split("FHIR medications", 1)[0]
    assert "Metformin 0.5 g" in intake_table
    assert "Ibuprofen 200 mg" in intake_table
    assert DISCLAIMER in text
    assert requested == []


def test_no_interview_patient_keeps_the_two_source_result(db, e2e_client):
    """An empty test DB has no interview: no intake findings or false 'reports none' claims."""
    client, requested = e2e_client
    detail = client.get("/patients/2178")
    assert detail.status_code == 200
    assert "No intake history recorded" in detail.text

    response = client.post("/patients/2178/reconcile", follow_redirects=False)
    assert response.status_code == 303
    run_url = response.headers["location"]
    run_id = int(run_url.rsplit("/", 1)[1])
    with Session(db) as session:
        run = repo.get_run(session, run_id)
        assert session.get(models.ReconciliationRun, run_id).intake_interview_id is None
        assert run.intake_interview is None and run.intake == []
        assert len(run.rejected) == 5
        assert all(r.source == "pharmacy" for r in run.rejected)
    assert len(run.findings) == 5
    assert {(f.discrepancy_type, f.medication) for f in run.findings} == {
        ("duplicate", "acetaminophen"),
        ("dosage_mismatch", "acetaminophen"),
        ("missing", "metoprolol"),
        ("missing", "omeprazole"),
        ("missing", "warfarin"),
    }
    assert all(f.intake_value is None for f in run.findings)
    assert {
        f.medication: f.details["missing_from"]
        for f in run.findings
        if f.discrepancy_type == "missing"
    } == {"metoprolol": "pharmacy", "omeprazole": "fhir", "warfarin": "pharmacy"}
    page = client.get(run_url)
    assert page.status_code == 200
    assert "No intake history recorded" in page.text
    assert "Patient reports no medications" not in page.text
    assert len(requested) == 4
