"""Pharmacy dataset reader: grouping by patient, unknown patient, missing file."""

import json

import pytest

from app.pharmacy import PharmacyDataError, rows_for


def _row(record_id, patient_id, name):
    """One string-valued pharmacy row in the B3 shape."""
    return {
        "record_id": record_id,
        "patient_id": patient_id,
        "medication_name": name,
        "dose_amount": "10",
        "dose_unit": "mg",
        "frequency": "once daily",
        "date_recorded": "2026-09-15",
    }


@pytest.fixture
def dataset(tmp_path):
    """A small dataset file with rows for two patients, interleaved."""
    path = tmp_path / "pharmacy_records.json"
    path.write_text(
        json.dumps(
            [
                _row("PH-1", "CASE-MIXED", "metformin"),
                _row("PH-2", "CASE-CLEAN", "Zestril"),
                _row("PH-3", "CASE-MIXED", "omeprazole"),
            ]
        )
    )
    return path


def test_rows_are_grouped_by_patient_in_file_order(dataset):
    """Only this patient's rows come back, raw and in file order."""
    rows = rows_for("CASE-MIXED", dataset)
    assert [r["record_id"] for r in rows] == ["PH-1", "PH-3"]
    assert rows[0]["dose_amount"] == "10"  # raw strings; validation is ingest's job


def test_unknown_patient_has_no_rows(dataset):
    """A patient absent from the dataset gives an empty list."""
    assert rows_for("CASE-NONE", dataset) == []


def test_env_var_selects_the_dataset(dataset, monkeypatch):
    """PHARMACY_DATA points the reader at another file."""
    monkeypatch.setenv("PHARMACY_DATA", str(dataset))
    assert len(rows_for("CASE-CLEAN")) == 1


def test_missing_file_names_the_path(tmp_path):
    """A missing dataset raises with the path in the message."""
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError, match="nope.json"):
        rows_for("CASE-MIXED", missing)


@pytest.mark.parametrize("content", ["{not json", '{"rows": []}', '["a row as text"]'])
def test_corrupt_dataset_names_the_path(tmp_path, content):
    """Invalid JSON, or JSON that isn't a list of rows, raises PharmacyDataError with the path."""
    path = tmp_path / "corrupt.json"
    path.write_text(content)
    with pytest.raises(PharmacyDataError, match="corrupt.json"):
        rows_for("CASE-MIXED", path)
