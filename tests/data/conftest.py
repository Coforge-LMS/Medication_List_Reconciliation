"""Fixtures for the generated datasets: the committed files, and the real pipeline over them."""

import csv
import json

import pytest

from contract import ReconciliationInput
from data.generators.common import (
    INTAKE_DIR,
    PHARMACY_FILE,
    load_cases,
    load_config,
    load_synthea,
)
from ingest.normalize import apply
from ingest.pharmacy import validate
from rules.runner import run_rules


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture(scope="session")
def synthea(config):
    """Accepted, normalized FHIR medications per Synthea patient."""
    return load_synthea(config)


@pytest.fixture(scope="session")
def cases(config):
    return load_cases(config)


@pytest.fixture(scope="session")
def pharmacy_rows():
    return json.loads(PHARMACY_FILE.read_text(encoding="utf-8"))


def _read_csv(name):
    with (INTAKE_DIR / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def interviews():
    return _read_csv("intake_interviews.csv")


@pytest.fixture(scope="session")
def intake_rows():
    return _read_csv("intake_medications.csv")


@pytest.fixture(scope="session")
def reconcile(config, synthea, cases, pharmacy_rows, interviews, intake_rows):
    """reconcile(patient_id) -> (ReconciliationInput, findings), the way app.service will do it."""
    fhir = synthea | cases

    def run(patient_id, with_intake=True):
        pharmacy, pharmacy_rejected = validate(
            [r for r in pharmacy_rows if r["patient_id"] == patient_id], "pharmacy"
        )
        intake, intake_rejected = None, []
        interview = next((i for i in interviews if i["patient_identifier"] == patient_id), None)
        if with_intake and interview:
            rows = [
                {**r, "patient_id": patient_id, "date_recorded": interview["taken_at"][:10]}
                for r in intake_rows
                if r["interview_ref"] == interview["interview_ref"]
            ]
            intake, intake_rejected = validate(rows, "intake")
            intake = apply(intake, config)
        data = ReconciliationInput(
            fhir=fhir[patient_id],
            pharmacy=apply(pharmacy, config),
            intake=intake,
            rejected=apply(pharmacy_rejected + intake_rejected, config),
        )
        return data, run_rules(data)

    return run
