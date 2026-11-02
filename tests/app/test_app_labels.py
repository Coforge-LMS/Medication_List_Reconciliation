import time
from datetime import UTC, datetime

import pytest

from app.labels import (
    DISCLAIMER,
    NLM_ATTRIBUTION,
    NO_DIFFERENCES_NOTE,
    NOT_COMPARED_NOTE,
    SOURCE_HEADINGS,
    Cell,
    finding_cells,
    finding_note,
    interview_line,
    label_for,
    matched_as,
    no_differences,
    no_differences_note,
)
from contract import Finding, IntakeInterviewInfo, Reason, Rejection
from tests.app.conftest import INTERVIEW, make_run, record


def test_known_types_have_labels():
    assert label_for("dosage_mismatch") == "Dosage mismatch"


def test_unknown_type_from_a_newer_release_renders_as_other():
    assert label_for("route_mismatch") == "Other (route_mismatch)"


def test_disclaimer_never_recommends():
    assert "does not recommend treatment" in DISCLAIMER


def test_no_differences_note_explains_not_compared_only_when_a_row_shows_it():
    """The (not compared) caveat appears only beside a value that carries the mark."""
    compared = [("metformin", {"fhir": "500 mg, twice daily", "pharmacy": "500 mg, twice daily"})]
    unscheduled = [("ibuprofen", {"fhir": "200 mg, as needed (not compared)"})]
    assert no_differences_note(compared) == NO_DIFFERENCES_NOTE
    assert no_differences_note(compared + unscheduled).endswith(NOT_COMPARED_NOTE)
    assert "no source is treated as correct" in no_differences_note(compared)


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


@pytest.mark.parametrize(
    ("frequency", "shown"),
    [
        ("BID", "500 mg, BID"),
        ("as needed", "500 mg, as needed (not compared)"),
        ("PRN", "500 mg, PRN (not compared)"),
        ("when my knee hurts", "500 mg, when my knee hurts (not compared)"),
        (None, "500 mg, no frequency (not compared)"),
        ("", "500 mg, no frequency (not compared)"),
    ],
)
def test_no_differences_marks_a_frequency_that_was_not_compared(frequency, shown):
    """As-needed, unreadable or blank can hide a difference, so it can't read as agreement."""
    fhir = [record("fhir", "metformin", "500", frequency=frequency)]
    ((_, stated),) = no_differences(_three_way(fhir=fhir))
    assert stated["fhir"] == shown


def _missing(medication, missing_from, rejected_ids=(), **values):
    """A missing finding with the details the rule writes."""
    return Finding(
        discrepancy_type="missing",
        medication=medication,
        summary="On the FHIR list; not reported by the patient and not in pharmacy records.",
        details={"missing_from": missing_from, "rejected_record_ids": list(rejected_ids)},
        **values,
    )


def test_cells_mark_a_rejected_source_apart_from_one_that_lacks_the_medication():
    """Pharmacy's warfarin was rejected; the patient never named it."""
    finding = _missing("warfarin", ["intake", "pharmacy"], ["PH-9"], fhir_value="5 mg")
    assert finding_cells(finding, make_run()) == [
        Cell("not_listed", "Not listed"),
        Cell("value", "5 mg"),
        Cell("rejected", "Rejected"),
    ]


def test_cells_say_no_interview_rather_than_not_listed_for_the_patient():
    """Without an interview nothing was asked, so the patient can't have left it out."""
    run = make_run(intake_interview=None, intake=[])
    finding = _missing("omeprazole", "fhir", pharmacy_value="20 mg")
    assert [c.kind for c in finding_cells(finding, run)] == ["no_interview", "not_listed", "value"]


def test_cells_fall_back_to_the_run_records_when_details_are_missing():
    """A run saved before details named sources still gets badges, from what each source lists."""
    finding = Finding(
        discrepancy_type="missing", medication="ibuprofen", summary="", intake_value="200 mg"
    )
    assert [c.kind for c in finding_cells(finding, make_run())] == [
        "value",
        "not_listed",
        "not_listed",
    ]


def test_duplicate_cells_count_records_on_every_side():
    """The duplicated source shows its count; a source with one record says so, not a dash."""
    finding = Finding(
        discrepancy_type="duplicate",
        medication="metformin",
        summary="FHIR has 2 records for metformin.",
        fhir_value="Metformin 500 mg; Metformin 1000 mg",
        details={"source": "fhir", "count": 2},
    )
    intake, fhir, pharmacy = finding_cells(finding, make_run())
    assert intake == Cell("not_listed", "Not listed")
    assert fhir.count == 2 and pharmacy == Cell("listed", "1 record")


@pytest.mark.parametrize(
    ("summary", "note"),
    [
        (
            "On the FHIR list; not in pharmacy records. 1 pharmacy record with this name was "
            "rejected (see Rejected records).",
            "",
        ),
        (
            "On the FHIR list; not in pharmacy records. Same ingredient, other salt: pharmacy "
            "metoprolol tartrate.",
            "Same ingredient, other salt: pharmacy metoprolol tartrate.",
        ),
        (
            "Different salt: FHIR metoprolol tartrate; pharmacy metoprolol succinate. FHIR dose "
            "0.5 g; pharmacy dose 500 mg.",
            "Different salt: FHIR metoprolol tartrate; pharmacy metoprolol succinate.",
        ),
        (
            "Doses are recorded in a different measure: FHIR dose 5 mL; pharmacy dose 5 mg.",
            "Doses are recorded in different measures.",
        ),
    ],
    ids=["rejection", "other-salt", "different-salt", "measure"],
)
def test_note_keeps_only_what_the_cells_cannot_show(summary, note):
    """Presence, absence and rejections are in the cells; product differences aren't."""
    assert finding_note(Finding(discrepancy_type="missing", medication="x", summary=summary)) == (
        note
    )


def test_note_for_an_unknown_type_is_its_whole_stored_summary():
    """A newer release's finding can't be shortened safely, so it's shown as stored."""
    finding = Finding(discrepancy_type="route_mismatch", medication="x", summary="FHIR route oral.")
    assert finding_note(finding) == "FHIR route oral."
