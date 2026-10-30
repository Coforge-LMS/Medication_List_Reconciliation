"""data/intake/*.csv: deterministic, loadable by db.seed, valid, no accidental false 'missing'."""

import csv
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from data.generators import make_intake
from data.generators.common import END_DATE, INTAKE_DIR
from db.seed import seed
from ingest.normalize import normalize_name
from ingest.pharmacy import validate

CASE_IDS = {"CASE-CLEAN", "CASE-MIXED", "CASE-BRAND"}
FILES = ("intake_interviews.csv", "intake_medications.csv")


def test_regenerating_gives_the_committed_files_byte_for_byte():
    interviews, medications, _ = make_intake.build(42)
    assert make_intake.render(interviews, make_intake.INTERVIEW_FIELDS) == (
        (INTAKE_DIR / FILES[0]).read_text(encoding="utf-8")
    )
    assert make_intake.render(medications, make_intake.MEDICATION_FIELDS) == (
        (INTAKE_DIR / FILES[1]).read_text(encoding="utf-8")
    )


def test_two_builds_are_identical():
    assert make_intake.build(42) == make_intake.build(42)


def test_the_cli_writes_the_same_bytes(tmp_path):
    make_intake.main(["--seed", "42", "--out", str(tmp_path)])
    for name in FILES:
        assert (tmp_path / name).read_bytes() == (INTAKE_DIR / name).read_bytes()


def test_a_different_seed_changes_the_data():
    assert make_intake.build(7)[:2] != make_intake.build(42)[:2]


# --- structure: what db.seed requires


def test_headers_match_the_seed_format():
    for name, fields in zip(
        FILES, (make_intake.INTERVIEW_FIELDS, make_intake.MEDICATION_FIELDS), strict=True
    ):
        with (INTAKE_DIR / name).open(newline="", encoding="utf-8") as f:
            assert next(csv.reader(f)) == list(fields)


def test_interviews_are_well_formed(interviews):
    refs = [i["interview_ref"] for i in interviews]
    assert len(set(refs)) == len(refs)
    for i in interviews:
        assert i["no_medications"] in ("true", "false")
        assert i["informant"] in ("patient", "caregiver")
        taken = datetime.fromisoformat(i["taken_at"])
        assert taken.tzinfo is not None
        assert taken.date() <= END_DATE


def test_medications_belong_to_an_interview_and_have_unique_ids(interviews, intake_rows):
    refs = {i["interview_ref"] for i in interviews}
    assert {m["interview_ref"] for m in intake_rows} <= refs
    keys = [(m["interview_ref"], m["record_id"]) for m in intake_rows]
    assert len(set(keys)) == len(keys)


def test_a_no_medications_interview_has_no_rows(interviews, intake_rows):
    empty = [i for i in interviews if i["no_medications"] == "true"]
    assert len(empty) == 1
    assert not [m for m in intake_rows if m["interview_ref"] == empty[0]["interview_ref"]]


def test_exactly_one_synthea_patient_has_no_interview(interviews, synthea):
    interviewed = {i["patient_identifier"] for i in interviews}
    assert set(synthea) - interviewed != set()
    assert len(set(synthea) - interviewed) == 1
    assert CASE_IDS <= interviewed
    assert interviewed <= set(synthea) | CASE_IDS


def test_the_seed_loads_the_files_and_is_idempotent(db):
    from sqlalchemy import text

    with Session(db) as session:
        first = seed(session, INTAKE_DIR)
    with Session(db) as session:
        assert seed(session, INTAKE_DIR) == first
    with db.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM intake_interview")) == first[0]
        assert conn.scalar(text("SELECT count(*) FROM intake_medication")) == first[1]


# --- patterns and validity


@pytest.mark.parametrize("pattern", make_intake.PATTERNS)
def test_every_patient_report_pattern_appears(pattern):
    assert make_intake.build(42)[2][pattern] >= 1


def test_unsure_doses_are_the_only_synthea_rejections(interviews, intake_rows):
    by_ref = {i["interview_ref"]: i for i in interviews}
    for ref, interview in by_ref.items():
        if interview["patient_identifier"] in CASE_IDS:
            continue
        rows = [
            {
                **m,
                "patient_id": interview["patient_identifier"],
                "date_recorded": interview["taken_at"][:10],
            }
            for m in intake_rows
            if m["interview_ref"] == ref
        ]
        _, rejections = validate(rows, "intake")
        unsure = [m for m in rows if m["dose_amount"] == "not sure"]
        assert len(rejections) == len(unsure)
        assert all(r.reasons[0].message == "patient unsure of dose" for r in rejections)


def test_there_are_no_ml_rows(intake_rows):
    assert "ml" not in {m["dose_unit"].strip().lower() for m in intake_rows}


def test_every_intake_name_matches_another_source_or_is_a_deliberate_otc_drug(
    intake_rows, interviews, synthea, cases, pharmacy_rows, config
):
    patient_of = {i["interview_ref"]: i["patient_identifier"] for i in interviews}
    otc = {normalize_name(name, config) for name in make_intake.OTC_NAMES}
    fhir = synthea | cases
    for row in intake_rows:
        patient = patient_of[row["interview_ref"]]
        known = {r.normalized_name for r in fhir[patient]}
        known |= {
            normalize_name(p["medication_name"], config)
            for p in pharmacy_rows
            if p["patient_id"] == patient and p["medication_name"]
        }
        name = normalize_name(row["medication_name"], config)
        assert name in known | otc, (
            f"{patient}: {row['medication_name']!r} would be a false 'missing'"
        )
