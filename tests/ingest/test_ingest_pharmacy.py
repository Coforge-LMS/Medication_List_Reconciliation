"""ingest.pharmacy.validate: every rejection code, multi-reason rows and the intake variant."""

from datetime import date
from decimal import Decimal

import pytest

from ingest.pharmacy import validate


def row(**overrides):
    base = {
        "record_id": "r1",
        "patient_id": "CASE-CLEAN",
        "medication_name": "Zestril",
        "dose_amount": "10",
        "dose_unit": "mg",
        "frequency": "once daily",
        "date_recorded": "2026-03-02",
    }
    return base | overrides


def only_rejection(rows, source="pharmacy"):
    records, rejections = validate(rows, source)
    assert records == []
    assert len(rejections) == 1
    return rejections[0]


def codes(rejection):
    return [(r.field, r.code) for r in rejection.reasons]


def test_valid_row_becomes_a_record():
    records, rejections = validate([row()])
    assert rejections == []
    [rec] = records
    assert (rec.source, rec.source_record_id, rec.patient_id) == ("pharmacy", "r1", "CASE-CLEAN")
    assert (rec.name, rec.dose_amount, rec.dose_unit) == ("Zestril", Decimal("10"), "mg")
    assert (rec.frequency, rec.date_recorded) == ("once daily", date(2026, 3, 2))
    assert rec.raw["record_id"] == "r1"


@pytest.mark.parametrize(
    ("unit", "expected"), [("MG", "mg"), ("µg", "mcg"), ("Grams", "g"), ("ml", "mL")]
)
def test_unit_spellings_are_normalized(unit, expected):
    [rec], _ = validate([row(dose_unit=unit)])
    assert rec.dose_unit == expected


def test_half_a_gram_and_five_hundred_mg_are_both_accepted():
    records, rejections = validate([row(dose_amount="0.5", dose_unit="g"), row(record_id="r2")])
    assert len(records) == 2 and rejections == []


def test_values_are_trimmed_and_blank_frequency_is_none():
    [rec], _ = validate([row(medication_name="  Zestril ", frequency="  ", patient_id=" P1 ")])
    assert (rec.name, rec.frequency, rec.patient_id) == ("Zestril", None, "P1")


@pytest.mark.parametrize(
    "field",
    ["patient_id", "medication_name", "record_id", "dose_unit", "date_recorded", "dose_amount"],
)
def test_a_blank_required_field_is_missing_field(field):
    rejection = only_rejection([row(**{field: " "})])
    assert codes(rejection) == [(field, "missing_field")]


def test_none_counts_as_blank():
    assert codes(only_rejection([row(dose_amount=None)])) == [("dose_amount", "missing_field")]


@pytest.mark.parametrize("dose", ["ten", "0", "-5", "NaN", "Infinity"])
def test_unreadable_doses(dose):
    rejection = only_rejection([row(dose_amount=dose)])
    assert codes(rejection) == [("dose_amount", "unreadable_dosage")]


@pytest.mark.parametrize("unit", ["tab", "units", "IU"])
def test_units_outside_the_accepted_four_are_unreadable(unit):
    rejection = only_rejection([row(dose_unit=unit)])
    assert codes(rejection) == [("dose_unit", "unreadable_dosage")]
    assert "mg, g, mcg, mL" in rejection.reasons[0].message


@pytest.mark.parametrize("value", ["03/02/2026", "2026-13-01", "yesterday", "2026-3-2", "20260302"])
def test_bad_dates_are_invalid_date(value):
    assert codes(only_rejection([row(date_recorded=value)])) == [("date_recorded", "invalid_date")]


def test_a_future_date_is_future_date():
    assert codes(only_rejection([row(date_recorded="2999-01-01")])) == [
        ("date_recorded", "future_date")
    ]


def test_one_row_can_carry_several_reasons():
    rejection = only_rejection(
        [row(medication_name="", dose_amount="ten", dose_unit="tab", date_recorded="2999-01-01")]
    )
    assert codes(rejection) == [
        ("medication_name", "missing_field"),
        ("dose_amount", "unreadable_dosage"),
        ("dose_unit", "unreadable_dosage"),
        ("date_recorded", "future_date"),
    ]


def test_a_rejection_keeps_the_readable_name_id_and_raw_row():
    source_row = row(dose_amount="ten")
    rejection = only_rejection([source_row])
    assert rejection.name == "Zestril"
    assert rejection.source_record_id == "r1"
    assert rejection.source == "pharmacy"
    assert rejection.raw == source_row


def test_valid_and_invalid_rows_are_split_and_none_is_dropped():
    records, rejections = validate(
        [row(), row(record_id="r2", dose_amount="ten"), row(record_id="r3")]
    )
    assert [r.source_record_id for r in records] == ["r1", "r3"]
    assert [r.source_record_id for r in rejections] == ["r2"]


def test_extra_keys_are_ignored():
    records, _ = validate([row(unexpected="x")])
    assert len(records) == 1


def test_an_empty_input_gives_empty_results():
    assert validate([]) == ([], [])


# intake: patient-reported rows, dated by the interview


def test_an_intake_row_is_an_intake_record_dated_by_its_interview():
    [rec], rejections = validate([row(date_recorded="2026-03-01")], source="intake")
    assert rejections == []
    assert (rec.source, rec.date_recorded) == ("intake", date(2026, 3, 1))


@pytest.mark.parametrize("dose", ["not sure", "", None, "   "])
def test_an_unknown_intake_dose_is_rejected_as_patient_unsure(dose):
    rejection = only_rejection([row(dose_amount=dose, dose_unit="")], source="intake")
    assert codes(rejection) == [("dose_amount", "unreadable_dosage")]
    assert rejection.reasons[0].message == "patient unsure of dose"
    assert rejection.source == "intake"


def test_an_intake_row_with_a_dose_but_no_unit_still_needs_the_unit():
    assert codes(only_rejection([row(dose_unit="")], source="intake")) == [
        ("dose_unit", "missing_field")
    ]


def test_a_pharmacy_dose_that_is_not_a_number_is_not_called_patient_unsure():
    rejection = only_rejection([row(dose_amount="ten")])
    assert "unsure" not in rejection.reasons[0].message
