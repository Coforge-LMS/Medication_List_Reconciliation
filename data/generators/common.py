"""Shared inputs and helpers for the pharmacy and intake generators (TECHNICAL_PLAN §16.3).

Base medications are the Synthea and case FHIR medications that pass ingest validation, so every
perturbation starts from something the app can actually read. Nothing here reads the clock or a
global random state: output depends only on the committed data and the seed.
"""

import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from contract import AliasConfig, MedicationRecord
from ingest.aliases import load_aliases
from ingest.fhir import map_medication_requests, map_patient
from ingest.normalize import apply

ROOT = Path(__file__).resolve().parents[2]
SYNTHEA_DIR = ROOT / "data" / "fhir" / "synthea"
CASES_FILE = ROOT / "data" / "fhir" / "cases" / "medrec-cases.json"
ALIASES_FILE = ROOT / "data" / "aliases.json"
PHARMACY_FILE = ROOT / "data" / "pharmacy" / "pharmacy_records.json"
INTAKE_DIR = ROOT / "data" / "intake"

END_DATE = date(2026, 10, 29)  # Synthea's pinned end date (-e 20261029): never in the future
FUTURE_DATE = "2999-01-01"  # always in the future, whenever the tests run

# How the pharmacy writes the frequency, by what the FHIR record said (None = FHIR was silent).
PHARMACY_FREQUENCY = {
    "QD": "once daily",
    "1/1d": "once daily",
    "BID": "twice daily",
    "2/1d": "twice daily",
    "TID": "three times daily",
    "3/1d": "three times daily",
    "4/1d": "four times daily",
    "PRN": "as needed",
}
# How a patient says it at the interview.
PATIENT_FREQUENCY = {
    "once daily": "once a day",
    "twice daily": "twice a day",
    "three times daily": "three times a day",
    "four times daily": "four times a day",
    "as needed": "as needed",
}


def load_config() -> AliasConfig:
    return load_aliases(ALIASES_FILE)


def alternates(config: AliasConfig) -> dict[str, list[str]]:
    """Generic name -> the other names the alias list knows it by, sorted (brands, salt forms)."""
    result: dict[str, list[str]] = {}
    for alias, generic in sorted(config.aliases.items()):
        result.setdefault(generic, []).append(alias)
    return result


def _bundle_medications(path: Path, config: AliasConfig) -> dict[str, list[MedicationRecord]]:
    """Accepted, normalized FHIR medications per patient identifier, in bundle order."""
    entries = [e["resource"] for e in json.loads(path.read_text())["entry"]]
    requests = [r for r in entries if r["resourceType"] == "MedicationRequest"]
    result = {}
    for patient in (r for r in entries if r["resourceType"] == "Patient"):
        info = map_patient(patient)
        mine = [r for r in requests if r["subject"]["reference"] == f"urn:uuid:{patient['id']}"]
        records, _ = map_medication_requests(mine, info.identifier)
        result[info.identifier] = apply(records, config)
    return result


def load_synthea(config: AliasConfig) -> dict[str, list[MedicationRecord]]:
    """The ten Synthea patients, sorted by identifier."""
    result: dict[str, list[MedicationRecord]] = {}
    for path in sorted(SYNTHEA_DIR.glob("*_*-*.json")):
        result |= _bundle_medications(path, config)
    return dict(sorted(result.items()))


def load_cases(config: AliasConfig) -> dict[str, list[MedicationRecord]]:
    return _bundle_medications(CASES_FILE, config)


def patient_rng(seed: int, identifier: str, purpose: str) -> random.Random:
    """One independent, reproducible stream per (seed, patient, purpose)."""
    return random.Random(f"{seed}:{purpose}:{identifier}")


def display_name(key: str) -> str:
    """'metoprolol succinate' -> 'Metoprolol Succinate': how a clerk or patient might write it."""
    return key.title()


def fmt(amount: Decimal) -> str:
    """A dose as plain text: '500', '0.5', '0.125' (no exponent, no trailing zeros)."""
    return format(amount.normalize(), "f")


def drugs_by_key(records: list[MedicationRecord]) -> dict[str, MedicationRecord]:
    """One record per identity key (a renewal can leave two active), first one wins."""
    result: dict[str, MedicationRecord] = {}
    for record in records:
        result.setdefault(record.normalized_name or record.name.lower(), record)
    return result


def recent_date(rng: random.Random, within_days: int) -> date:
    """A date 0..within_days before END_DATE: a recent fill or interview, never in the future."""
    return END_DATE - timedelta(days=rng.randint(0, within_days))
