from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contract import Finding, MedicationRecord, PatientInfo, Reason, ReconciliationInput, Rejection
from db import models
from db.repo import save_run

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


def rejection(source, record_id, name):
    return Rejection(
        source=source,
        source_record_id=record_id,
        name=name,
        raw={"dose_amount": "ten"},
        reasons=[Reason(field="dose_amount", code="unreadable_dosage", message="bad")],
    )


def payload(intake=None):
    rejected = [rejection("pharmacy", "PH-3", "Amlodipine")]
    if intake is not None:
        rejected.append(rejection("intake", "IN-2", "warfarin"))
    return ReconciliationInput(
        fhir=[record("fhir", "mr-1", "Lisinopril"), record("fhir", "mr-2", "Metformin")],
        pharmacy=[record("pharmacy", "PH-1", "Lisinopril"), record("pharmacy", "PH-2", "Aspirin")],
        intake=intake,
        rejected=rejected,
    )


def finding(discrepancy_type="missing"):
    return Finding(discrepancy_type=discrepancy_type, medication="metformin", summary="x")


def save(engine, findings, data=None):
    with Session(engine) as session:
        return save_run(
            session, PATIENT, "http://hapi:8080/fhir", "1.0.0", data or payload(), findings
        )


def test_success_commits_exact_rows_in_all_tables(db, row_counts):
    save(db, [finding("missing"), finding("duplicate")])
    assert row_counts() == {
        "patient": 1,
        "intake_interview": 0,
        "intake_medication": 0,
        "reconciliation_run": 1,
        "medication_record": 4,
        "finding": 2,
        "rejected_record": 1,
    }


def test_success_with_intake_snapshots_intake_rows(db, row_counts, seed_intake):
    seed_intake(medications=[{"record_id": "IN-1"}, {"record_id": "IN-2", "dose_amount": "?"}])
    save(db, [finding()], payload(intake=[record("intake", "IN-1", "Metformin")]))
    assert row_counts() == {
        "patient": 1,
        "intake_interview": 1,
        "intake_medication": 2,
        "reconciliation_run": 1,
        "medication_record": 5,
        "finding": 1,
        "rejected_record": 2,
    }
    with db.connect() as conn:
        assert conn.scalar(text("SELECT intake_interview_id FROM reconciliation_run")) == 1


class ExplodingFindings(list):
    """Raises when save_run iterates it, i.e. after the patient upsert and run flush."""

    def __iter__(self):
        raise RuntimeError("boom after flush")


FAULTS = pytest.mark.parametrize(
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


@FAULTS
def test_failure_rolls_back_everything_including_patient(db, row_counts, findings, error):
    with pytest.raises(error):
        save(db, findings)
    assert set(row_counts().values()) == {0}


@FAULTS
def test_failure_leaves_seeded_intake_and_patient_unchanged(
    db, row_counts, seed_intake, findings, error
):
    seed_intake(medications=[{"record_id": "IN-1"}])
    before = row_counts()
    with pytest.raises(error):
        save(db, findings, payload(intake=[record("intake", "IN-1", "Metformin")]))
    assert row_counts() == before
    assert before["reconciliation_run"] == 0 and before["intake_medication"] == 1
    with db.connect() as conn:  # the patient upsert was rolled back too
        assert conn.execute(text("SELECT fhir_patient_id, fetched_at FROM patient")).one() == (
            None,
            None,
        )


def test_intake_without_a_recorded_interview_is_refused(db, row_counts):
    with pytest.raises(ValueError, match="no interview recorded"):
        save(db, [], payload(intake=[]))
    assert set(row_counts().values()) == {0}


@pytest.mark.parametrize(
    "table, values",
    [
        (
            models.Finding,
            {"run_id": 999999, "discrepancy_type": "x", "medication": "m", "summary": "s"},
        ),
        (
            models.IntakeInterview,
            {
                "patient_id": 999999,
                "interview_ref": "INT-X",
                "taken_at": datetime(2026, 10, 1, tzinfo=UTC),
                "taken_by": "RN",
                "informant": "patient",
            },
        ),
        (models.IntakeMedication, {"interview_id": 999999, "record_id": "IN-X", "raw": {}}),
    ],
    ids=["finding_run_id", "intake_interview_patient_id", "intake_medication_interview_id"],
)
def test_insert_with_unknown_parent_violates_foreign_key(db, table, values):
    with pytest.raises(IntegrityError), db.begin() as conn:
        conn.execute(insert(table).values(values))


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
