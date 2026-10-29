"""Saved-run read models shared by db (writer), app pages and the PDF (readers)."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from contract.findings import Finding
from contract.medication import MedicationRecord, Rejection


class PatientInfo(BaseModel):
    """FHIR patient snapshot: identifier is the stable key, fhir_patient_id the latest HAPI id."""

    model_config = ConfigDict(frozen=True)

    identifier: str
    fhir_patient_id: str
    name: str | None = None
    birth_date: date | None = None
    gender: str | None = None


class RunSummary(BaseModel):
    """One history row."""

    model_config = ConfigDict(frozen=True)

    run_id: int
    app_version: str
    started_at: datetime
    finding_count: int
    counts_by_type: dict[str, int]


class RunDetail(BaseModel):
    """Everything a saved run holds: what was compared, what was rejected, what was found."""

    model_config = ConfigDict(frozen=True)

    run_id: int
    app_version: str
    started_at: datetime
    patient: PatientInfo
    fhir: list[MedicationRecord]
    pharmacy: list[MedicationRecord]
    rejected: list[Rejection]
    findings: list[Finding]
