"""Seed intake interviews from CSV: python -m db.seed data/intake (TECHNICAL_PLAN §16.1)."""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db import models
from db.repo import init_db
from db.session import get_engine


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def seed(session: Session, seed_dir: Path) -> tuple[int, int]:
    """Upsert intake_interviews.csv and intake_medications.csv in one transaction.

    Idempotent: interviews by interview_ref, rows by (interview, record_id); patients are
    created by identifier when missing. Rows removed from the CSVs are not deleted.
    Refuses the whole seed if a no_medications interview has rows. Returns the CSV row counts.
    """
    interviews = _read(seed_dir / "intake_interviews.csv")
    medications = _read(seed_dir / "intake_medications.csv")

    takes_nothing: set[str] = set()
    for i in interviews:
        flag = i["no_medications"].strip().lower()
        if flag not in ("true", "false"):
            raise ValueError(f"{i['interview_ref']}: no_medications must be true or false")
        if flag == "true":
            takes_nothing.add(i["interview_ref"])
    known = {i["interview_ref"] for i in interviews}
    for m in medications:
        if m["interview_ref"] not in known:
            raise ValueError(f"{m['record_id']}: unknown interview_ref {m['interview_ref']}")
        if m["interview_ref"] in takes_nothing:
            raise ValueError(f"{m['interview_ref']} is no_medications but has row {m['record_id']}")

    with session.begin():
        interview_ids: dict[str, int] = {}
        for i in interviews:
            identifier = i["patient_identifier"]
            patient_id = session.scalar(
                insert(models.Patient)
                .values(identifier=identifier)
                # no-op update so RETURNING also yields an existing patient's id
                .on_conflict_do_update(
                    index_elements=["identifier"], set_={"identifier": identifier}
                )
                .returning(models.Patient.id)
            )
            values = {
                "patient_id": patient_id,
                "interview_ref": i["interview_ref"],
                "taken_at": datetime.fromisoformat(i["taken_at"]),
                "taken_by": i["taken_by"],
                "informant": i["informant"],
                "no_medications": i["interview_ref"] in takes_nothing,
            }
            interview_ids[i["interview_ref"]] = session.scalar(
                insert(models.IntakeInterview)
                .values(values)
                .on_conflict_do_update(index_elements=["interview_ref"], set_=values)
                .returning(models.IntakeInterview.id)
            )
        for m in medications:
            values = {
                "interview_id": interview_ids[m["interview_ref"]],
                "record_id": m["record_id"],
                "medication_name": m["medication_name"],
                "dose_amount": m["dose_amount"],
                "dose_unit": m["dose_unit"],
                "frequency": m["frequency"],
                "raw": m,
            }
            session.execute(
                insert(models.IntakeMedication)
                .values(values)
                .on_conflict_do_update(index_elements=["interview_id", "record_id"], set_=values)
            )
    return len(interviews), len(medications)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m db.seed", description=__doc__)
    parser.add_argument("seed_dir", type=Path, help="folder holding the two intake CSVs")
    seed_dir = parser.parse_args(argv).seed_dir
    engine = get_engine()
    init_db(engine)
    try:
        with Session(engine) as session:
            interviews, medications = seed(session, seed_dir)
    except (OSError, ValueError) as exc:
        sys.exit(f"db.seed: {exc}")
    print(f"Seeded {interviews} interviews and {medications} medication rows from {seed_dir}")


if __name__ == "__main__":
    main()
