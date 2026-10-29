"""Persistence: atomic save of one run, and the history reads (TECHNICAL_PLAN §5)."""

from datetime import UTC, datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from contract import (
    Finding,
    MedicationRecord,
    PatientInfo,
    ReconciliationInput,
    Rejection,
    RunDetail,
    RunSummary,
)
from db import models


def init_db(engine: Engine) -> None:
    """Create missing tables; a no-op on an existing schema."""
    models.Base.metadata.create_all(engine)


def save_run(
    session: Session,
    patient: PatientInfo,
    fhir_base_url: str,
    app_version: str,
    data: ReconciliationInput,
    findings: list[Finding],
) -> int:
    """Upsert the patient and store the run with its records, rejections and findings.

    One transaction: any exception rolls back everything, the patient upsert included.
    """
    with session.begin():
        values = patient.model_dump() | {
            "fhir_base_url": fhir_base_url,
            "fetched_at": datetime.now(UTC),
        }
        patient_id = session.scalar(
            insert(models.Patient)
            .values(values)
            .on_conflict_do_update(index_elements=["identifier"], set_=values)
            .returning(models.Patient.id)
        )
        run = models.ReconciliationRun(
            patient_id=patient_id, app_version=app_version, started_at=datetime.now(UTC)
        )
        session.add(run)
        session.flush()
        session.add_all(
            models.MedicationRecord(
                run_id=run.id,
                source=r.source,
                source_record_id=r.source_record_id,
                original_name=r.name,
                normalized_name=r.normalized_name,
                rxcui=r.rxcui,
                dose_amount=r.dose_amount,
                dose_unit=r.dose_unit,
                frequency=r.frequency,
                date_recorded=r.date_recorded,
                raw=r.raw,
            )
            for r in [*data.fhir, *data.pharmacy]
        )
        session.add_all(
            models.RejectedRecord(
                run_id=run.id,
                source=r.source,
                source_record_id=r.source_record_id,
                original_name=r.name,
                raw=r.raw,
                reasons=[reason.model_dump(mode="json") for reason in r.reasons],
            )
            for r in data.rejected
        )
        session.add_all(
            models.Finding(
                run_id=run.id,
                discrepancy_type=f.discrepancy_type,
                medication=f.medication,
                summary=f.summary,
                fhir_value=f.fhir_value,
                pharmacy_value=f.pharmacy_value,
                details=f.details,
            )
            for f in findings
        )
        session.flush()
        return run.id


def get_run(session: Session, run_id: int) -> RunDetail | None:
    """Rebuild a saved run as contract objects, records and findings in insertion order."""
    run = session.get(models.ReconciliationRun, run_id)
    if run is None:
        return None
    p = session.get_one(models.Patient, run.patient_id)

    def rows(model):
        return session.scalars(select(model).where(model.run_id == run_id).order_by(model.id))

    records = [
        MedicationRecord(
            patient_id=p.identifier,
            source=m.source,
            source_record_id=m.source_record_id,
            name=m.original_name,
            dose_amount=m.dose_amount,
            dose_unit=m.dose_unit,
            frequency=m.frequency,
            date_recorded=m.date_recorded,
            normalized_name=m.normalized_name,
            rxcui=m.rxcui,
            raw=m.raw,
        )
        for m in rows(models.MedicationRecord)
    ]
    return RunDetail(
        run_id=run.id,
        app_version=run.app_version,
        started_at=run.started_at,
        patient=PatientInfo(
            identifier=p.identifier,
            fhir_patient_id=p.fhir_patient_id,
            name=p.name,
            birth_date=p.birth_date,
            gender=p.gender,
        ),
        fhir=[r for r in records if r.source == "fhir"],
        pharmacy=[r for r in records if r.source == "pharmacy"],
        rejected=[
            Rejection(
                source=r.source,
                source_record_id=r.source_record_id,
                name=r.original_name,
                raw=r.raw,
                reasons=r.reasons,
            )
            for r in rows(models.RejectedRecord)
        ],
        findings=[
            Finding(
                discrepancy_type=f.discrepancy_type,
                medication=f.medication,
                summary=f.summary,
                fhir_value=f.fhir_value,
                pharmacy_value=f.pharmacy_value,
                details=f.details,
            )
            for f in rows(models.Finding)
        ],
    )


def list_runs(session: Session, identifier: str) -> list[RunSummary]:
    """History for one patient identifier, newest first, with finding counts per type."""
    run, finding = models.ReconciliationRun, models.Finding
    stmt = (
        select(
            run.id,
            run.app_version,
            run.started_at,
            finding.discrepancy_type,
            func.count(finding.id),
        )
        .join(models.Patient, models.Patient.id == run.patient_id)
        .outerjoin(finding, finding.run_id == run.id)
        .where(models.Patient.identifier == identifier)
        .group_by(run.id, finding.discrepancy_type)
        .order_by(run.started_at.desc(), run.id.desc(), finding.discrepancy_type)
    )
    summaries: dict[int, dict] = {}
    for run_id, version, started_at, dtype, count in session.execute(stmt):
        s = summaries.setdefault(
            run_id,
            {
                "run_id": run_id,
                "app_version": version,
                "started_at": started_at,
                "counts_by_type": {},
            },
        )
        if dtype is not None:  # a run with no findings outer-joins to one NULL row
            s["counts_by_type"][dtype] = count
    return [
        RunSummary(**s, finding_count=sum(s["counts_by_type"].values())) for s in summaries.values()
    ]
