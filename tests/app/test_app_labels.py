import time
from datetime import UTC, datetime

import pytest

from app.labels import (
    DISCLAIMER,
    NLM_ATTRIBUTION,
    SOURCE_HEADINGS,
    interview_line,
    label_for,
    matched_as,
    no_differences,
)
from contract import Finding, IntakeInterviewInfo, Reason, Rejection
from tests.app.conftest import INTERVIEW, make_run, record


def test_known_types_have_labels():
    assert label_for("dosage_mismatch") == "Dosage mismatch"


def test_unknown_type_from_a_newer_release_renders_as_other():
    assert label_for("route_mismatch") == "Other (route_mismatch)"


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


def test_frequency_mismatch_has_its_own_label():
    """V2's type is known in this release; 1.0.0 still shows it as Other (frequency_mismatch)."""
    assert label_for("frequency_mismatch") == "Frequency mismatch"


def test_nlm_attribution_is_nlms_exact_wording():
    """RxNav's terms require this sentence, so it's pinned here rather than compared to itself."""
    assert NLM_ATTRIBUTION == (
        "This product uses publicly available data from the U.S. National Library of Medicine "
        "(NLM), National Institutes of Health, Department of Health and Human Services; NLM is "
        "not responsible for the product and does not endorse or recommend this or any other "
        "product."
    )


@pytest.mark.parametrize(
    ("name", "normalized", "rxcui", "label"),
    [
        ("Zoloft", "sertraline", "82728", "sertraline"),
        ("Alendronic Acid", "alendronate", "236083", "alendronate"),
        ("sertraline 50 MG Oral Tablet", "sertraline", "312941", None),
        ("Metformin Hydrochloride", "metformin", "235743", None),
        ("Combo Brand", "losartan / hctz", "1", "losartan / hctz"),
        ("losartan 50 MG / hctz 25 MG", "losartan / hctz", "1", None),
        ("losartan 50 MG", "losartan / hctz", "1", "losartan / hctz"),
        ("Zestril", "lisinopril", None, None),  # an alias match, not RxNorm's
    ],
)
def test_matched_as_appears_only_where_it_explains_something(name, normalized, rxcui, label):
    """A brand or renamed drug is labelled; a name already containing the ingredient isn't."""
    item = record("pharmacy", name).model_copy(
        update={"normalized_name": normalized, "rxcui": rxcui}
    )
    assert matched_as(item) == label


def _three_way(**overrides):
    """A run where all three sources list metformin and no finding names it."""
    fields = {
        "intake": [record("intake", "metformin", "0.5", "g", "twice a day")],
        "fhir": [record("fhir", "metformin", "500", frequency="BID")],
        "pharmacy": [record("pharmacy", "metformin", "500", frequency="twice daily")],
        "intake_interview": INTERVIEW,
        "findings": [],
        "rejected": [],
    }
    return make_run(**(fields | overrides))


def test_no_differences_lists_each_source_as_it_states_the_medication():
    """Each source's own dose and frequency wording is kept, so nothing is hidden by the match."""
    assert no_differences(_three_way()) == [
        (
            "metformin",
            {
                "intake": "0.5 g, twice a day",
                "fhir": "500 mg, BID",
                "pharmacy": "500 mg, twice daily",
            },
        )
    ]


def test_no_differences_leaves_out_a_medication_with_a_finding():
    """Any finding on the name, including a type from a newer release, keeps it out."""
    finding = Finding(discrepancy_type="newer_type", medication="metformin", summary="x")
    assert no_differences(_three_way(findings=[finding])) == []


def test_no_differences_leaves_out_a_medication_with_a_rejected_record():
    """A rejected record wasn't compared, so "no differences" would claim too much."""
    reason = Reason(field="dose_amount", code="unreadable_dosage", message="not a number")
    rejected = Rejection(
        source="pharmacy", source_record_id="PH-1", name="Metformin", reasons=[reason]
    )
    assert no_differences(_three_way(rejected=[rejected])) == []


def test_no_differences_needs_every_compared_source():
    """A name one source lacks isn't reported, even if a stored run has no finding for it."""
    assert no_differences(_three_way(pharmacy=[])) == []


def test_no_differences_without_an_interview_compares_fhir_and_pharmacy():
    """With no interview, intake takes no part and has no value."""
    ((name, stated),) = no_differences(_three_way(intake=[], intake_interview=None))
    assert name == "metformin" and set(stated) == {"fhir", "pharmacy"}


def test_no_differences_is_empty_when_the_patient_reports_none():
    """An interview with no medications takes part, so nothing is in every source."""
    assert no_differences(_three_way(intake=[])) == []
