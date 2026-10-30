from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from contract import (
    Finding,
    IntakeInterviewInfo,
    MedicationRecord,
    PatientInfo,
    Reason,
    ReconciliationInput,
    Rejection,
)
from db import models
from db.repo import get_run, latest_intake_for, list_runs, save_run

BASE_URL = "http://hapi:8080/fhir"
INTERVIEW = IntakeInterviewInfo(
    taken_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
    taken_by="RN Okafor",
    informant="patient",
    no_medications=False,
)


def patient(fhir_patient_id="1"):
    return PatientInfo(
        identifier="CASE-MIXED",
        fhir_patient_id=fhir_patient_id,
        name="Ana Diaz",
        birth_date=date(1960, 1, 2),
        gender="female",
    )


def record(source, record_id):
    return MedicationRecord(
        patient_id="CASE-MIXED",
        source=source,
        source_record_id=record_id,
        name="Zestril",
        dose_amount=Decimal("0.5"),
        dose_unit="g",
        frequency="once daily",
        date_recorded=date(2026, 9, 15),
        normalized_name="lisinopril",
        raw={"id": record_id},
    )


def save(engine, findings=(), version="1.0.0", fhir_patient_id="1", data=None):
    data = data or ReconciliationInput(fhir=[], pharmacy=[])
    with Session(engine) as session:
        return save_run(session, patient(fhir_patient_id), BASE_URL, version, data, list(findings))


def test_list_runs_is_newest_first_with_counts(db):
    first = save(db, [Finding(discrepancy_type="missing", medication="a", summary="s")])
    second = save(
        db,
        [
            Finding(discrepancy_type="duplicate", medication="a", summary="s"),
            Finding(discrepancy_type="duplicate", medication="b", summary="s"),
            Finding(discrepancy_type="missing", medication="c", summary="s"),
        ],
        version="1.1.0",
    )
    with Session(db) as session:
        runs = list_runs(session, "CASE-MIXED")
        assert list_runs(session, "CASE-OTHER") == []
    assert [r.run_id for r in runs] == [second, first]
    assert runs[0].app_version == "1.1.0"
    assert runs[0].finding_count == 3
    assert runs[0].counts_by_type == {"duplicate": 2, "missing": 1}
    assert runs[1].counts_by_type == {"missing": 1}


def test_run_without_findings_has_zero_counts(db):
    save(db)
    with Session(db) as session:
        (run,) = list_runs(session, "CASE-MIXED")
    assert run.finding_count == 0 and run.counts_by_type == {}


def test_history_survives_a_changed_hapi_id(db):
    save(db, fhir_patient_id="1")
    run_id = save(db, fhir_patient_id="99")
    with db.connect() as conn:
        assert conn.execute(text("SELECT identifier, fhir_patient_id FROM patient")).all() == [
            ("CASE-MIXED", "99")
        ]
    with Session(db) as session:
        assert len(list_runs(session, "CASE-MIXED")) == 2
        assert get_run(session, run_id).patient.fhir_patient_id == "99"


def test_get_run_round_trips_contract_objects_and_unknown_type(db, seed_intake):
    seed_intake(medications=[{"record_id": "IN-1"}, {"record_id": "IN-2"}])
    unknown = Finding(
        discrepancy_type="frequency_mismatch",
        medication="lisinopril",
        summary="Frequency differs between sources.",
        fhir_value="Zestril 0.5 g",
        pharmacy_value="Zestril 0.5 g",
        intake_value="Zestril 0.5 g",
        details={"records": [{"source": "fhir", "source_record_id": "mr-1"}]},
    )
    data = ReconciliationInput(
        fhir=[record("fhir", "mr-1"), record("fhir", "mr-2")],
        pharmacy=[record("pharmacy", "PH-1")],
        intake=[record("intake", "IN-1")],
        rejected=[
            Rejection(
                source="pharmacy",
                name="Amlodipine",
                raw={"dose_amount": "ten"},
                reasons=[Reason(field="dose_amount", code="unreadable_dosage", message="bad")],
            ),
            Rejection(
                source="intake",
                source_record_id="IN-2",
                name="warfarin",
                raw={"dose_amount": "not sure"},
                reasons=[
                    Reason(
                        field="dose_amount",
                        code="unreadable_dosage",
                        message="patient unsure of dose",
                    )
                ],
            ),
        ],
    )
    findings = [Finding(discrepancy_type="missing", medication="x", summary="s"), unknown]
    run_id = save(db, findings, data=data)
    with Session(db) as session:
        run = get_run(session, run_id)
    assert run.run_id == run_id and run.app_version == "1.0.0"
    assert run.patient == patient()
    assert run.fhir == data.fhir and run.pharmacy == data.pharmacy and run.intake == data.intake
    assert run.intake_interview == INTERVIEW
    assert run.rejected == data.rejected
    assert run.findings == findings


def test_takes_nothing_and_not_taken_round_trip_apart(db, seed_intake):
    not_taken = save(db)
    seed_intake([{"no_medications": "true"}])
    takes_nothing = save(db, data=ReconciliationInput(fhir=[], pharmacy=[], intake=[]))
    with Session(db) as session:
        first, second = get_run(session, not_taken), get_run(session, takes_nothing)
    assert first.intake == [] and first.intake_interview is None
    assert second.intake == []
    assert second.intake_interview == INTERVIEW.model_copy(update={"no_medications": True})


def test_save_run_after_a_read_on_the_same_session(db, seed_intake):
    seed_intake()
    with Session(db) as session:  # the service reads intake, then saves, on one session
        interview, _ = latest_intake_for(session, "CASE-MIXED")
        data = ReconciliationInput(fhir=[], pharmacy=[], intake=[])
        run_id = save_run(session, patient(), BASE_URL, "1.0.0", data, [])
        assert get_run(session, run_id).intake_interview == interview == INTERVIEW


@pytest.mark.parametrize("flush", [False, True], ids=["pending", "flushed"])
def test_save_run_refuses_a_session_with_uncommitted_writes(db, row_counts, flush):
    with Session(db) as session:
        session.add(models.Patient(identifier="CASE-OTHER"))
        if flush:
            session.flush()
        with pytest.raises(RuntimeError, match="uncommitted writes"):
            save_run(
                session, patient(), BASE_URL, "1.0.0", ReconciliationInput(fhir=[], pharmacy=[]), []
            )
    assert set(row_counts().values()) == {0}  # neither committed nor half-saved


def test_get_run_of_missing_id_is_none(db):
    with Session(db) as session:
        assert get_run(session, 999999) is None
