import time
from datetime import UTC, datetime

import pytest

from app.labels import DISCLAIMER, SOURCE_HEADINGS, interview_line, label_for
from contract import IntakeInterviewInfo


def test_known_types_have_labels():
    assert label_for("dosage_mismatch") == "Dosage mismatch"


def test_unknown_type_from_a_newer_release_renders_as_other():
    assert label_for("frequency_mismatch") == "Other (frequency_mismatch)"


def test_disclaimer_never_recommends():
    assert "does not recommend treatment" in DISCLAIMER


def _interview(no_medications=False):
    """An interview taken by RN Okafor with the patient as informant."""
    return IntakeInterviewInfo(
        taken_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        taken_by="RN Okafor",
        informant="patient",
        no_medications=no_medications,
    )


def test_interview_line_names_date_taker_and_informant():
    """A recorded interview with medications gives date, taker and informant."""
    assert interview_line(_interview()) == "Intake taken 2026-10-01 by RN Okafor (patient)"


def test_interview_line_for_patient_reporting_no_medications():
    """An interview flagged no_medications says so."""
    assert interview_line(_interview(no_medications=True)) == "Patient reports no medications"


def test_interview_line_without_an_interview():
    """No interview at all is stated plainly."""
    assert interview_line(None) == "No intake history recorded"


def test_source_headings_are_in_column_order():
    """Patient-reported, FHIR, Pharmacy."""
    assert list(SOURCE_HEADINGS.values()) == ["Patient-reported", "FHIR", "Pharmacy"]


@pytest.fixture
def kolkata(monkeypatch):
    """Run the process at UTC+05:30, then restore the original zone."""
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_interview_date_is_the_local_day_like_the_intake_rows(kolkata):
    """20:00 UTC is 01:30 the next day in Kolkata: the line shows the date the rows carry."""
    late = _interview().model_copy(update={"taken_at": datetime(2026, 10, 1, 20, 0, tzinfo=UTC)})
    assert interview_line(late).startswith("Intake taken 2026-10-02 ")
