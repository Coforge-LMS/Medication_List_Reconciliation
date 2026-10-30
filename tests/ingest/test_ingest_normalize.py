"""ingest.normalize: identity keys from TECHNICAL_PLAN §4.3, applied to records and rejections."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from contract import MedicationRecord, Reason, Rejection
from ingest.aliases import load_aliases
from ingest.normalize import apply, normalize_name

CONFIG = load_aliases(Path(__file__).parents[2] / "data" / "aliases.json")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet", "metformin"),
        ("atorvastatin 20 MG Oral Tablet [Lipitor]", "atorvastatin"),
        ("Zestril", "lisinopril"),
        ("Norvasc 5 mg", "amlodipine"),
        ("warfarin sodium 5 MG Oral Tablet", "warfarin"),
        ("metoprolol tartrate 25 MG Oral Tablet", "metoprolol"),
        ("Warfarin", "warfarin"),
        ("metoprolol", "metoprolol"),
        ("24 HR metoprolol succinate 100 MG Extended Release Oral Tablet", "metoprolol succinate"),
        ("LISINOPRIL 10 MG Oral Tablet", "lisinopril"),
        ("hydrochlorothiazide 25 MG Oral Tablet", "hydrochlorothiazide"),
        ("Vitamin B12 Injectable Solution", "vitamin b12 injectable"),  # b12 is not a bare number
        ("Crestor 10 mg", "crestor"),  # a brand outside the alias list stays as it is
        ("rosuvastatin calcium 10 MG Oral Tablet [Crestor]", "rosuvastatin calcium"),
    ],
)
def test_names_normalize_as_documented(name, expected):
    assert normalize_name(name, CONFIG) == expected


def test_name_made_only_of_strengths_is_empty():
    assert normalize_name("500 MG Oral Tablet", CONFIG) == ""


def record(name):
    return MedicationRecord(
        patient_id="P1",
        source="pharmacy",
        source_record_id="r1",
        name=name,
        dose_amount=Decimal("10"),
        dose_unit="mg",
        date_recorded=date(2026, 3, 2),
    )


def test_apply_sets_normalized_name_and_keeps_the_original():
    [result] = apply([record("Zestril 10 mg")], CONFIG)
    assert result.normalized_name == "lisinopril"
    assert result.name == "Zestril 10 mg"


def test_apply_normalizes_rejections_so_counterparts_can_match():
    rejected = Rejection(
        source="pharmacy",
        name="Zestril",
        reasons=[Reason(field="dose_amount", code="unreadable_dosage", message="x")],
    )
    [result] = apply([rejected], CONFIG)
    assert isinstance(result, Rejection)
    assert result.normalized_name == "lisinopril"


def test_apply_leaves_a_nameless_rejection_without_a_key():
    rejected = Rejection(
        source="pharmacy",
        reasons=[Reason(field="medication_name", code="missing_field", message="x")],
    )
    assert apply([rejected], CONFIG)[0].normalized_name is None


def test_apply_returns_new_objects_and_does_not_touch_the_input():
    original = record("Zestril")
    [result] = apply([original], CONFIG)
    assert original.normalized_name is None
    assert result is not original
