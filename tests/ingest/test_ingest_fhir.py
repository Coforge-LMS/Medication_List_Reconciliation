"""ingest.fhir: MedicationRequest and Patient mapping, on built resources and the recorded data."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from contract import MedicationRecord, Rejection
from ingest.aliases import load_aliases
from ingest.fhir import (
    PatientMappingError,
    map_medication_request,
    map_medication_requests,
    map_patient,
)
from ingest.normalize import apply

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "hapi"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def mr(display="lisinopril 10 MG Oral Tablet", **overrides):
    resource = {
        "resourceType": "MedicationRequest",
        "id": "mr-1",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"system": RXNORM, "code": "314076", "display": display}],
            "text": display,
        },
        "subject": {"reference": "Patient/2178"},
        "authoredOn": "2026-02-10T08:30:00+00:00",
    }
    return resource | overrides


def dosage(**fields):
    return {"dosageInstruction": [{"sequence": 1, **fields}]}


def mapped(resource):
    result = map_medication_request(resource, "CASE-MIXED")
    assert isinstance(result, MedicationRecord), result
    return result


def rejected(resource):
    result = map_medication_request(resource, "CASE-MIXED")
    assert isinstance(result, Rejection), result
    return result


# --- dose: strength from the RxNorm display x the unitless count


def test_strength_comes_from_the_display():
    rec = mapped(mr())
    assert (rec.dose_amount, rec.dose_unit) == (Decimal("10"), "mg")
    assert (rec.source, rec.patient_id, rec.source_record_id) == ("fhir", "CASE-MIXED", "mr-1")
    assert rec.date_recorded == date(2026, 2, 10)
    assert rec.raw["id"] == "mr-1"


def test_a_quantity_prefix_is_not_the_strength():
    rec = mapped(mr("24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet"))
    assert (rec.dose_amount, rec.dose_unit) == (Decimal("500"), "mg")


def test_the_bracketed_brand_is_kept_in_the_name_and_ignored_for_the_dose():
    rec = mapped(mr("atorvastatin 20 MG Oral Tablet [Lipitor]"))
    assert rec.name == "atorvastatin 20 MG Oral Tablet [Lipitor]"
    assert (rec.dose_amount, rec.dose_unit) == (Decimal("20"), "mg")


def test_a_decimal_strength_in_micrograms():
    rec = mapped(mr("levothyroxine 0.125 MG Oral Tablet"))
    assert rec.dose_amount == Decimal("0.125")
    assert mapped(mr("digoxin 250 UG Oral Tablet")).dose_unit == "mcg"


def test_the_unitless_dose_count_multiplies_the_strength():
    resource = mr() | dosage(doseAndRate=[{"doseQuantity": {"value": 2.0}}])
    assert mapped(resource).dose_amount == Decimal("20")


def test_a_real_unit_on_the_dose_quantity_is_used_as_is():
    resource = mr("some drug") | dosage(
        doseAndRate=[{"doseQuantity": {"value": 500, "unit": "mg", "code": "mg"}}]
    )
    rec = mapped(resource)
    assert (rec.dose_amount, rec.dose_unit) == (Decimal("500"), "mg")


def test_a_missing_dosage_instruction_is_accepted_with_no_frequency():
    resource = mr()
    assert "dosageInstruction" not in resource
    rec = mapped(resource)
    assert (rec.dose_amount, rec.frequency) == (Decimal("10"), None)


@pytest.mark.parametrize(
    ("display", "fragment"),
    [
        ("Acetaminophen 300 MG / Hydrocodone Bitartrate 5 MG Oral Tablet", "combination"),
        ("hydrochlorothiazide 25 MG / losartan potassium 100 MG Oral Tablet", "combination"),
        ("albuterol 0.83 MG/ML Inhalation Solution", "per-ml"),
        ("Nitroglycerin 0.4 MG/ACTUAT Mucosal Spray", "per-actuat"),
        (
            "120 ACTUAT fluticasone propionate 0.044 MG/ACTUAT Metered Dose Inhaler [Flovent]",
            "per-actuat",
        ),
        (
            "insulin isophane, human 70 UNT/ML / insulin, regular, human 30 UNT/ML Injectable "
            "Suspension",
            "combination",
        ),
        ("Aspirin Oral Tablet", "no strength"),
        ("heparin 5000 UNT Injectable", "UNT"),
    ],
)
def test_unreadable_strengths_are_rejected(display, fragment):
    rejection = rejected(mr(display))
    assert [(r.field, r.code) for r in rejection.reasons] == [
        ("medicationCodeableConcept", "unreadable_dosage")
    ]
    assert fragment in rejection.reasons[0].message
    assert rejection.name == display  # the readable name is kept for the rules


@pytest.mark.parametrize("count", [0, -1])
def test_a_non_positive_dose_count_is_unreadable(count):
    resource = mr() | dosage(doseAndRate=[{"doseQuantity": {"value": count}}])
    assert [r.code for r in rejected(resource).reasons] == ["unreadable_dosage"]


# --- status


@pytest.mark.parametrize("status", ["completed", "stopped", "on-hold", "cancelled", "draft"])
def test_inactive_requests_are_skipped_not_rejected(status):
    assert map_medication_request(mr(status=status), "P") is None


def test_other_resource_types_are_skipped():
    assert map_medication_request({"resourceType": "Medication", "id": "m"}, "P") is None


def test_map_medication_requests_splits_records_rejections_and_skips():
    resources = [mr(), mr("Aspirin Oral Tablet", id="mr-2"), mr(status="completed", id="mr-3")]
    records, rejections = map_medication_requests(resources, "P")
    assert [r.source_record_id for r in records] == ["mr-1"]
    assert [r.source_record_id for r in rejections] == ["mr-2"]


# --- name


def test_name_falls_back_to_text_then_to_any_coding_display():
    text_only = mr() | {"medicationCodeableConcept": {"text": "Zestril 10 MG Oral Tablet"}}
    assert mapped(text_only).name == "Zestril 10 MG Oral Tablet"
    other = mr() | {
        "medicationCodeableConcept": {
            "coding": [
                {"system": "http://snomed.info/sct", "display": "lisinopril 5 MG Oral Tablet"}
            ]
        }
    }
    assert mapped(other).name == "lisinopril 5 MG Oral Tablet"


def test_a_request_with_no_readable_name_is_rejected_without_a_name():
    rejection = rejected(mr() | {"medicationCodeableConcept": {}})
    assert [(r.field, r.code) for r in rejection.reasons] == [
        ("medicationCodeableConcept", "missing_field")
    ]
    assert rejection.name is None


# --- frequency, as the source gave it


def test_frequency_prefers_the_timing_code():
    timing = {
        "code": {"coding": [{"code": "BID"}]},
        "repeat": {"frequency": 1, "period": 1, "periodUnit": "d"},
    }
    assert mapped(mr() | dosage(timing=timing)).frequency == "BID"


def test_frequency_from_a_repeat_is_n_per_period():
    timing = {"repeat": {"frequency": 4, "period": 1.0, "periodUnit": "d"}}
    assert mapped(mr() | dosage(timing=timing)).frequency == "4/1d"
    timing = {"repeat": {"frequency": 1, "period": 12, "periodUnit": "h"}}
    assert mapped(mr() | dosage(timing=timing)).frequency == "1/12h"


def test_frequency_falls_back_to_the_dosage_text():
    assert mapped(mr() | dosage(text="Take with food")).frequency == "Take with food"


def test_as_needed_adds_prn_to_the_frequency():
    timing = {"code": {"coding": [{"code": "QD"}]}}
    assert mapped(mr() | dosage(timing=timing, asNeededBoolean=True)).frequency == "QD PRN"


def test_as_needed_with_no_timing_is_just_prn():
    resource = mr() | dosage(text="Take as needed.", asNeededBoolean=True)
    assert mapped(resource).frequency == "PRN"


def test_as_needed_false_adds_nothing():
    timing = {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}}
    assert mapped(mr() | dosage(timing=timing, asNeededBoolean=False)).frequency == "1/1d"


# --- date


def test_the_date_is_the_utc_date_of_authored_on():
    assert mapped(mr(authoredOn="2025-12-14T23:30:00-05:00")).date_recorded == date(2025, 12, 15)
    assert mapped(mr(authoredOn="2025-12-14")).date_recorded == date(2025, 12, 14)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (None, "missing_field"),
        ("", "missing_field"),
        ("2025-12", "invalid_date"),
        ("soon", "invalid_date"),
        ("2999-01-01T00:00:00+00:00", "future_date"),
    ],
)
def test_a_bad_authored_on_is_rejected(value, code):
    resource = mr(authoredOn=value)
    assert [(r.field, r.code) for r in rejected(resource).reasons] == [("authoredOn", code)]


def test_a_request_can_carry_several_reasons():
    resource = mr("Aspirin Oral Tablet", authoredOn="2999-01-01T00:00:00+00:00", id="")
    assert [r.code for r in rejected(resource).reasons] == [
        "missing_field",
        "unreadable_dosage",
        "future_date",
    ]


# --- patients


def patient(**overrides):
    resource = {
        "resourceType": "Patient",
        "id": "2178",
        "identifier": [
            {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "999-00-0000"},
            {"system": "urn:medrec:case", "value": "CASE-MIXED"},
        ],
        "name": [{"use": "official", "family": "Mixton", "given": ["Marcus"]}],
        "gender": "male",
        "birthDate": "1951-11-30",
    }
    return resource | overrides


def test_a_patient_is_keyed_by_the_stable_identifier_not_the_hapi_id():
    info = map_patient(patient())
    assert (info.identifier, info.fhir_patient_id) == ("CASE-MIXED", "2178")
    assert (info.name, info.gender, info.birth_date) == (
        "Marcus Mixton",
        "male",
        date(1951, 11, 30),
    )


def test_a_synthea_identifier_is_accepted():
    identifiers = [{"system": "https://github.com/synthetichealth/synthea", "value": "uuid-1"}]
    assert map_patient(patient(identifier=identifiers)).identifier == "uuid-1"


@pytest.mark.parametrize(
    "overrides", [{"identifier": []}, {"identifier": [{"system": "x", "value": "y"}]}, {"id": ""}]
)
def test_a_patient_without_a_stable_key_raises(overrides):
    with pytest.raises(PatientMappingError):
        map_patient(patient(**overrides))


def test_missing_optional_patient_fields_are_none():
    info = map_patient(patient(name=[], gender=None, birthDate="1951"))
    assert (info.name, info.gender, info.birth_date) == (None, None, None)


# --- the recorded HAPI responses and the committed Synthea data


def load(path):
    return json.loads(path.read_text())


def case_inputs(case):
    info = map_patient(load(FIXTURES / case / "patient_read.json"))
    entries = load(FIXTURES / case / "medicationrequest_active.json")["entry"]
    return info, [e["resource"] for e in entries]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (
            "CASE-CLEAN",
            [("lisinopril", "10", "QD"), ("atorvastatin", "20", "QD"), ("amlodipine", "5", "QD")],
        ),
        (
            "CASE-MIXED",
            [
                ("metformin", "500", "BID"),
                ("metoprolol tartrate", "25", "BID"),
                ("acetaminophen", "500", "BID"),
                ("sertraline", "50", "QD"),
                ("warfarin sodium", "5", "QD"),
            ],
        ),
        ("CASE-BRAND", [("rosuvastatin calcium", "10", "QD")]),
    ],
)
def test_the_recorded_case_patients_map_cleanly(case, expected):
    info, resources = case_inputs(case)
    assert info.identifier == case
    records, rejections = map_medication_requests(resources, info.identifier)
    records = apply(records, load_aliases(ROOT / "data" / "aliases.json"))
    assert rejections == []
    assert [
        (r.normalized_name, format(r.dose_amount.normalize(), "f"), r.frequency) for r in records
    ] == expected
    assert all(r.patient_id == case and r.source_record_id.isdigit() for r in records)


def synthea_bundles():
    return sorted((ROOT / "data" / "fhir" / "synthea").glob("*_*-*.json"))


def test_every_active_synthea_medication_is_accepted_or_rejected_never_lost():
    bundles = synthea_bundles()
    assert len(bundles) == 10
    active = accepted = rejected_count = 0
    for path in bundles:
        resources = [e["resource"] for e in load(path)["entry"]]
        info = map_patient(next(r for r in resources if r["resourceType"] == "Patient"))
        requests = [r for r in resources if r["resourceType"] == "MedicationRequest"]
        records, rejections = map_medication_requests(requests, info.identifier)
        active += sum(r["status"] == "active" for r in requests)
        accepted += len(records)
        rejected_count += len(rejections)
        assert {c.code for r in rejections for c in r.reasons} <= {"unreadable_dosage"}
    assert accepted + rejected_count == active == 59
