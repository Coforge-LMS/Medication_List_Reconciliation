import csv

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.seed import seed

TABLES = (
    "patient",
    "intake_interview",
    "intake_medication",
    "reconciliation_run",
    "medication_record",
    "finding",
    "rejected_record",
)
INTERVIEW = {
    "interview_ref": "INT-1",
    "patient_identifier": "CASE-MIXED",
    "taken_at": "2026-10-01T09:30:00+00:00",
    "taken_by": "RN Okafor",
    "informant": "patient",
    "no_medications": "false",
}
MEDICATION = {
    "interview_ref": "INT-1",
    "record_id": "IN-1",
    "medication_name": "metformin",
    "dose_amount": "500",
    "dose_unit": "mg",
    "frequency": "twice daily",
}


@pytest.fixture
def row_counts(db):
    def counts():
        with db.connect() as conn:  # fresh connection: what any other reader sees
            return {t: conn.scalar(text(f"SELECT count(*) FROM {t}")) for t in TABLES}

    return counts


@pytest.fixture
def seed_intake(db, tmp_path):
    """Write the two intake CSVs from partial rows (defaults fill the rest) and run db.seed."""

    def write(name, defaults, rows):
        with (tmp_path / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(defaults))
            writer.writeheader()
            writer.writerows(defaults | row for row in rows)

    def run(interviews=({},), medications=()):
        write("intake_interviews.csv", INTERVIEW, interviews)
        write("intake_medications.csv", MEDICATION, medications)
        with Session(db) as session:
            return seed(session, tmp_path)

    return run
