"""The reconcile pipeline the HTML and JSON routes share."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app import pharmacy
from app.fhir_client import FhirClient
from app.version import __version__
from contract import AliasConfig, IntakeInterviewInfo, PatientInfo, ReconciliationInput
from db import repo
from ingest import normalize
from ingest.fhir import map_medication_requests, map_patient
from ingest.pharmacy import validate
from rules import run_rules


class NoPharmacyData(Exception):
    """We hold no pharmacy rows for this patient, so a comparison would only show false gaps."""


@dataclass(frozen=True)
class Prepared:
    """One patient's normalized input, ready for the rules, plus what the pages show with it."""

    patient: PatientInfo
    data: ReconciliationInput
    interview: IntakeInterviewInfo | None
    has_pharmacy_data: bool  # any rows on file, even if every one of them was rejected


def build_input(
    fhir_resources: Iterable[dict[str, Any]],
    identifier: str,
    pharmacy_rows: Iterable[Mapping[str, Any]],
    intake_rows: Iterable[Mapping[str, Any]] | None,
    aliases: AliasConfig,
) -> ReconciliationInput:
    """Map, validate and normalize the three sources; no I/O.

    intake_rows=None means no interview was recorded, so intake stays None (two-source result);
    [] means the patient reports no medications. Rejections from every source are normalized
    too, so the rules can name a rejected counterpart.
    """
    fhir, fhir_rejected = map_medication_requests(fhir_resources, identifier)
    pharmacy_records, pharmacy_rejected = validate(pharmacy_rows, source="pharmacy")
    intake, intake_rejected = None, []
    if intake_rows is not None:
        intake, intake_rejected = validate(intake_rows, source="intake")
        intake = normalize.apply(intake, aliases)
    return ReconciliationInput(
        fhir=normalize.apply(fhir, aliases),
        pharmacy=normalize.apply(pharmacy_records, aliases),
        intake=intake,
        rejected=normalize.apply([*fhir_rejected, *pharmacy_rejected, *intake_rejected], aliases),
    )


def collect(fhir_id: str, session: Session, client: FhirClient, aliases: AliasConfig) -> Prepared:
    """Fetch the patient and their medications from FHIR, pharmacy and intake (no save)."""
    patient = map_patient(client.read_patient(fhir_id))
    resources = client.active_medication_requests(fhir_id)
    latest = repo.latest_intake_for(session, patient.identifier)
    interview, intake_rows = latest if latest else (None, None)
    pharmacy_rows = pharmacy.rows_for(patient.identifier)
    data = build_input(resources, patient.identifier, pharmacy_rows, intake_rows, aliases)
    return Prepared(
        patient=patient, data=data, interview=interview, has_pharmacy_data=bool(pharmacy_rows)
    )


def reconcile(fhir_id: str, session: Session, client: FhirClient, aliases: AliasConfig) -> int:
    """Run the full pipeline for one patient and save it in one transaction; returns the run id."""
    prepared = collect(fhir_id, session, client, aliases)
    if not prepared.has_pharmacy_data:
        raise NoPharmacyData(f"Nothing to compare for {prepared.patient.identifier}.")
    findings = run_rules(prepared.data)
    return repo.save_run(
        session, prepared.patient, client.base_url, __version__, prepared.data, findings
    )
