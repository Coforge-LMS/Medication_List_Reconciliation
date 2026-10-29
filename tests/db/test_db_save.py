from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contract import Finding, MedicationRecord, PatientInfo, Reason, ReconciliationInput, Rejection
from db import models
from db.repo import save_run

TABLES = ("patient", "reconciliation_run", "medication_record", "finding", "rejected_record")
PATIENT = PatientInfo(identifier="CASE-MIXED", fhir_patient_id="1", name="Ana Diaz")


def record(source, record_id, name):
    return MedicationRecord(
        patient_id="CASE-MIXED",
        source=source,
        source_record_id=record_id,
        name=name,
        dose_amount=Decimal("10"),
        dose_unit="mg",
        date_recorded=date(2026, 9, 15),
        normalized_name=name.lower(),
        raw={"id": record_id, "name": name},
    )


def payload():
    return ReconciliationInput(
        fhir=[record("fhir", "mr-1", "Lisinopril"), record("fhir", "mr-2", "Metformin")],
        pharmacy=[record("pharmacy", "PH-1", "Lisinopril"), record("pharmacy", "PH-2", "Aspirin")],
        rejected=[
            Rejection(
                source="pharmacy",
                source_record_id="PH-3",
                name="Amlodipine",
                raw={"dose_amount": "ten"},
                reasons=[Reason(field="dose_amount", code="unreadable_dosage", message="bad")],
            )
        ],
    )


def finding(discrepancy_type="missing"):
    return Finding(discrepancy_type=discrepancy_type, medication="metformin", summary="x")


def save(engine, findings):
    with Session(engine) as session:
        return save_run(session, PATIENT, "http://hapi:8080/fhir", "1.0.0", payload(), findings)


def counts(engine):
    with engine.connect() as conn:  # fresh connection: what any other reader sees
        return {t: conn.scalar(text(f"SELECT count(*) FROM {t}")) for t in TABLES}


def test_success_commits_exact_rows_in_all_tables(db):
    save(db, [finding("missing"), finding("duplicate")])
    assert counts(db) == {
        "patient": 1,
        "reconciliation_run": 1,
        "medication_record": 4,
        "finding": 2,
        "rejected_record": 1,
    }


class ExplodingFindings(list):
    """Raises when save_run iterates it, i.e. after the patient upsert and run flush."""

    def __iter__(self):
        raise RuntimeError("boom after flush")


@pytest.mark.parametrize(
    "findings, error",
    [
        (
            [Finding.model_construct(discrepancy_type=None, medication="m", summary="s")],
            IntegrityError,
        ),
        (ExplodingFindings([finding()]), RuntimeError),
    ],
    ids=["not_null_violation", "exception_after_flush"],
)
def test_failure_rolls_back_everything_including_patient(db, findings, error):
    with pytest.raises(error):
        save(db, findings)
    assert counts(db) == dict.fromkeys(TABLES, 0)


def test_finding_with_unknown_run_id_violates_foreign_key(db):
    with pytest.raises(IntegrityError), db.begin() as conn:
        conn.execute(
            insert(models.Finding).values(
                run_id=999999, discrepancy_type="missing", medication="m", summary="s"
            )
        )


def test_rows_carry_source_record_id_and_raw(db):
    save(db, [])
    with db.connect() as conn:
        meds = conn.execute(
            text("SELECT source, source_record_id, raw FROM medication_record ORDER BY id")
        ).all()
        rejected = conn.execute(text("SELECT source_record_id, raw, reasons FROM rejected_record"))
        assert rejected.one() == (
            "PH-3",
            {"dose_amount": "ten"},
            [{"field": "dose_amount", "code": "unreadable_dosage", "message": "bad"}],
        )
    assert [(s, rid) for s, rid, _ in meds] == [
        ("fhir", "mr-1"),
        ("fhir", "mr-2"),
        ("pharmacy", "PH-1"),
        ("pharmacy", "PH-2"),
    ]
    assert meds[0].raw == {"id": "mr-1", "name": "Lisinopril"}
