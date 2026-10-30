from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.repo import latest_intake_for
from db.seed import main

TWO_INTERVIEWS = (
    {"interview_ref": "INT-OLD", "taken_at": "2026-09-01T09:00:00+00:00"},
    {"interview_ref": "INT-NEW", "taken_at": "2026-10-01T09:30:00+00:00"},
)
ROWS = (
    {"interview_ref": "INT-OLD", "record_id": "IN-1", "medication_name": "aspirin"},
    {"interview_ref": "INT-NEW", "record_id": "IN-1"},
    {"interview_ref": "INT-NEW", "record_id": "IN-2", "dose_amount": "not sure", "frequency": ""},
)


def test_seeding_twice_is_idempotent(db, row_counts, seed_intake):
    assert seed_intake(TWO_INTERVIEWS, ROWS) == (2, 3)
    first = row_counts()
    seed_intake([{**TWO_INTERVIEWS[0], "taken_by": "Dr Rao"}, TWO_INTERVIEWS[1]], ROWS)
    assert row_counts() == first
    assert first["patient"] == 1 and first["intake_interview"] == 2
    with db.connect() as conn:
        assert conn.scalar(text("SELECT taken_by FROM intake_interview ORDER BY id LIMIT 1")) == (
            "Dr Rao"
        )


def test_seed_creates_patient_without_fhir_columns(db, seed_intake):
    seed_intake([{"patient_identifier": "SYN-123"}])
    with db.connect() as conn:
        assert conn.execute(
            text("SELECT identifier, fhir_patient_id, fetched_at FROM patient")
        ).all() == [("SYN-123", None, None)]


@pytest.mark.parametrize(
    "interviews, medications, message",
    [
        ([{"no_medications": "true"}], [{}], "INT-1 is no_medications but has row IN-1"),
        ([{}], [{"interview_ref": "INT-9"}], "unknown interview_ref INT-9"),
        ([{"no_medications": "yes"}], [], "no_medications must be true or false"),
    ],
    ids=["no_medications_with_rows", "unknown_interview", "bad_flag"],
)
def test_invalid_seed_is_refused_whole(
    db, row_counts, seed_intake, interviews, medications, message
):
    with pytest.raises(ValueError, match=message):
        seed_intake([*TWO_INTERVIEWS, *interviews], medications)
    assert set(row_counts().values()) == {0}


def test_latest_intake_for_returns_newest_interview_as_pharmacy_shaped_rows(db, seed_intake):
    seed_intake(TWO_INTERVIEWS, ROWS)
    with Session(db) as session:
        interview, rows = latest_intake_for(session, "CASE-MIXED")
        assert latest_intake_for(session, "CASE-OTHER") is None
    assert interview.taken_by == "RN Okafor" and not interview.no_medications
    assert interview.taken_at == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    base = {
        "patient_id": "CASE-MIXED",
        "medication_name": "metformin",
        "dose_amount": "500",
        "dose_unit": "mg",
        "frequency": "twice daily",
        "date_recorded": "2026-10-01",
    }
    assert rows == [
        {"record_id": "IN-1", **base},
        {**base, "record_id": "IN-2", "dose_amount": "not sure", "frequency": ""},
    ]


def test_latest_intake_for_takes_nothing(db, seed_intake):
    seed_intake([{"no_medications": "TRUE"}])
    with Session(db) as session:
        interview, rows = latest_intake_for(session, "CASE-MIXED")
    assert interview.no_medications and rows == []


def test_cli_seeds_and_reports(db, row_counts, seed_intake, tmp_path, capsys):
    seed_intake(TWO_INTERVIEWS, ROWS)  # writes the CSVs into tmp_path
    main([str(tmp_path)])
    assert "Seeded 2 interviews and 3 medication rows" in capsys.readouterr().out
    assert row_counts()["intake_medication"] == 3
    with pytest.raises(SystemExit, match="db.seed: .*No such file"):
        main([str(tmp_path / "missing")])
