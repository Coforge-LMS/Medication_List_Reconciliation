"""data/pharmacy/pharmacy_records.json: deterministic, valid, and every scenario present."""

import json
from decimal import Decimal

import pytest

from contract import to_base
from data.generators import make_pharmacy
from data.generators.common import END_DATE, PHARMACY_FILE
from ingest.normalize import normalize_name
from ingest.pharmacy import validate

CASE_IDS = {"CASE-CLEAN", "CASE-MIXED", "CASE-BRAND"}


def test_regenerating_gives_the_committed_file_byte_for_byte():
    rows, _ = make_pharmacy.build(42)
    assert make_pharmacy.render(rows) == PHARMACY_FILE.read_text(encoding="utf-8")


def test_two_builds_are_identical():
    assert make_pharmacy.build(42) == make_pharmacy.build(42)


def test_the_cli_writes_the_same_bytes(tmp_path):
    out = tmp_path / "pharmacy_records.json"
    make_pharmacy.main(["--seed", "42", "--out", str(out)])
    assert out.read_bytes() == PHARMACY_FILE.read_bytes()


def test_a_different_seed_changes_the_data():
    assert make_pharmacy.build(7)[0] != make_pharmacy.build(42)[0]


def test_rows_have_the_documented_string_fields(pharmacy_rows):
    fields = list(make_pharmacy.FIELDS)
    assert fields == [
        "record_id",
        "patient_id",
        "medication_name",
        "dose_amount",
        "dose_unit",
        "frequency",
        "date_recorded",
    ]
    for row in pharmacy_rows:
        assert list(row) == fields
        assert all(isinstance(value, str) for value in row.values())


def test_record_ids_are_unique(pharmacy_rows):
    ids = [r["record_id"] for r in pharmacy_rows]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "PH-0001"


def test_every_patient_in_the_file_exists_in_the_fhir_data(pharmacy_rows, synthea, cases):
    assert {r["patient_id"] for r in pharmacy_rows} <= set(synthea) | CASE_IDS
    assert CASE_IDS <= {r["patient_id"] for r in pharmacy_rows}


# --- validity: Synthea rows pass B4, the case patients' invalid rows fail for the planned reasons


def test_every_synthea_row_passes_validation(pharmacy_rows):
    rows = [r for r in pharmacy_rows if r["patient_id"] not in CASE_IDS]
    records, rejections = validate(rows)
    assert rejections == []
    assert len(records) == len(rows)
    assert all(r.date_recorded <= END_DATE for r in records)


def test_the_case_patients_invalid_rows_are_rejected_for_the_planned_reasons(pharmacy_rows):
    def rejected(patient):
        rows = [r for r in pharmacy_rows if r["patient_id"] == patient]
        _, rejections = validate(rows)
        return [(r.name, [x.code for x in r.reasons]) for r in rejections]

    assert rejected("CASE-CLEAN") == []
    assert rejected("CASE-BRAND") == []
    assert rejected("CASE-MIXED") == [
        ("Warfarin Sodium", ["unreadable_dosage"]),
        (None, ["missing_field"]),
        ("Pravastatin", ["unreadable_dosage"]),
        ("Tamsulosin", ["invalid_date"]),
        ("Famotidine", ["future_date"]),
    ]


def test_there_are_no_ml_rows(pharmacy_rows):
    assert "mL" not in {r["dose_unit"].strip() for r in pharmacy_rows}
    assert "ml" not in {r["dose_unit"].strip().lower() for r in pharmacy_rows}


# --- scenarios: each one the ticket asks for appears at least once


@pytest.mark.parametrize("scenario", [*make_pharmacy.SCENARIOS, "pharmacy_only"])
def test_every_scenario_is_applied_at_least_once(scenario):
    _, scenarios = make_pharmacy.build(42)
    assert scenarios[scenario] >= 1, scenarios


def test_a_dropped_medication_shows_as_missing_from_the_pharmacy(synthea, reconcile):
    found = {
        (f.discrepancy_type, f.details.get("missing_from"))
        for patient in synthea
        for f in reconcile(patient, with_intake=False)[1]
    }
    assert ("missing", "pharmacy") in found
    assert ("missing", "fhir") in found  # a pharmacy-only drug
    assert {t for t, _ in found} >= {"duplicate", "dosage_mismatch"}


def test_brand_names_in_the_file_come_only_from_the_alias_list(pharmacy_rows, synthea, config):
    brand_rows = [
        r
        for r in pharmacy_rows
        if r["patient_id"] in synthea and r["medication_name"].lower() in config.aliases
    ]
    assert brand_rows, "no brand-name row from aliases.json"
    for row in brand_rows:
        assert (
            normalize_name(row["medication_name"], config)
            == config.aliases[row["medication_name"].lower()]
        )


def test_a_gram_row_equals_its_fhir_milligram_dose_and_is_not_a_mismatch(
    pharmacy_rows, synthea, reconcile, config
):
    gram_rows = [r for r in pharmacy_rows if r["dose_unit"] == "g" and r["patient_id"] in synthea]
    assert gram_rows
    for row in gram_rows:
        key = normalize_name(row["medication_name"], config)
        fhir = next(r for r in synthea[row["patient_id"]] if r.normalized_name == key)
        assert to_base(Decimal(row["dose_amount"]), "g") == to_base(
            fhir.dose_amount, fhir.dose_unit
        )
        findings = reconcile(row["patient_id"], with_intake=False)[1]
        assert not [
            f for f in findings if f.discrepancy_type == "dosage_mismatch" and f.medication == key
        ]


def test_the_file_is_plain_json_with_a_trailing_newline():
    text = PHARMACY_FILE.read_text(encoding="utf-8")
    assert text.endswith("]\n")
    assert isinstance(json.loads(text), list)
