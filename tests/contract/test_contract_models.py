from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from contract import Finding, MedicationRecord, Reason, ReconciliationInput, Rejection


def record(**overrides):
    fields = dict(
        patient_id="CASE-CLEAN",
        source="pharmacy",
        source_record_id="PH-0001",
        name="Zestril",
        dose_amount=Decimal("10"),
        dose_unit="mg",
        frequency="once daily",
        date_recorded=date(2026, 9, 15),
    )
    return MedicationRecord(**(fields | overrides))


def test_valid_record_keeps_original_name():
    rec = record()
    assert rec.name == "Zestril" and rec.normalized_name is None and rec.rxcui is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"dose_amount": Decimal("0")},
        {"dose_unit": "tab"},
        {"source": "clinic"},
        {"name": ""},
        {"date_recorded": date.today() + timedelta(days=1)},
    ],
)
def test_invalid_records_are_rejected_by_the_contract(overrides):
    with pytest.raises(ValidationError):
        record(**overrides)


def test_record_is_frozen():
    with pytest.raises(ValidationError):
        record().name = "other"


def test_rejection_needs_at_least_one_reason():
    with pytest.raises(ValidationError):
        Rejection(source="pharmacy", raw={}, reasons=[])
    rej = Rejection(
        source="pharmacy",
        name="amlodipine",
        raw={"dose_amount": "ten"},
        reasons=[
            Reason(field="dose_amount", code="unreadable_dosage", message="'ten' is not a number")
        ],
    )
    assert rej.reasons[0].code == "unreadable_dosage"


def test_finding_type_is_open_vocabulary():
    # V1 must be able to load findings written by a newer release.
    assert Finding(discrepancy_type="frequency_mismatch", medication="lisinopril", summary="x")


def test_reconciliation_input_defaults_to_no_rejections():
    assert ReconciliationInput(fhir=[record(source="fhir")], pharmacy=[record()]).rejected == []


def test_run_detail_holds_unknown_finding_types():
    from datetime import datetime

    from contract import PatientInfo, RunDetail

    run = RunDetail(
        run_id=1,
        app_version="1.1.0",
        started_at=datetime(2026, 10, 29, 12, 0),
        patient=PatientInfo(identifier="CASE-MIXED", fhir_patient_id="42"),
        fhir=[record(source="fhir")],
        pharmacy=[record()],
        rejected=[],
        findings=[Finding(discrepancy_type="future_type", medication="x", summary="y")],
    )
    assert run.findings[0].discrepancy_type == "future_type"
