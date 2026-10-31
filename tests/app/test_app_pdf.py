"""PDF report: pypdf text covers patient, disclaimer, interview, three values and unicode."""

import io

import pytest
from pypdf import PdfReader

from app.labels import DISCLAIMER
from app.pdf import build_report
from contract import Finding
from tests.app.conftest import INTERVIEW, make_run


def pages(pdf: bytes) -> list[str]:
    """Text per page with whitespace collapsed, since wrapping changes the line breaks."""
    return [" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages]


def text(run) -> str:
    """The whole report's text."""
    return " ".join(pages(build_report(run)))


def test_report_is_a_pdf_with_patient_details_and_the_exact_disclaimer():
    """Output starts with %PDF- and names the patient, the run time, the version and disclaimer."""
    report = build_report(make_run())
    assert report.startswith(b"%PDF-")
    content = " ".join(pages(report))
    assert "Marcus Mixton" in content and "CASE-MIXED" in content
    assert "Run 7, started 2026-10-30 14:05 UTC, app version 1.0.0" in content
    assert DISCLAIMER in content


def test_zero_findings_says_no_discrepancies_found():
    """A clean run states it plainly."""
    assert "No discrepancies found" in text(make_run(findings=[]))


def test_findings_never_claim_no_discrepancies():
    """A run with findings gives counts per type instead of the clean statement."""
    content = text(make_run())
    assert "No discrepancies found" not in content
    assert "Missing medication: 2" in content and "Dosage mismatch: 1" in content


def test_unknown_type_renders_as_other_with_its_stored_summary():
    """A type from a newer release is labelled Other (x) and keeps its summary and values."""
    content = text(make_run())
    assert "Other (frequency_mismatch)" in content
    assert "FHIR frequency QD; pharmacy frequency BID." in content


def test_micro_signs_and_em_dash_render():
    """Both micro characters and an em dash survive; core PDF fonts would raise on these."""
    finding = Finding(
        discrepancy_type="dosage_mismatch",
        medication="cyanocobalamin",
        summary="Doses differ — see values.",
        intake_value="50 µg",  # U+00B5 micro sign
        fhir_value="100 μg",  # U+03BC Greek mu
    )
    content = text(make_run(findings=[finding]))
    assert "Doses differ — see values." in content
    assert "50 µg" in content and "100 μg" in content


@pytest.mark.parametrize(
    ("interview", "line"),
    [
        (INTERVIEW, "Intake taken 2026-10-01 by RN Okafor (patient)"),
        (INTERVIEW.model_copy(update={"no_medications": True}), "Patient reports no medications"),
        (None, "No intake history recorded"),
    ],
    ids=["taken", "no-medications", "none"],
)
def test_interview_line_states(interview, line):
    """Each interview state appears in the report."""
    assert line in text(make_run(intake_interview=interview))


def test_each_source_has_a_medication_table():
    """Patient-reported, FHIR and Pharmacy tables list their records, frequency as stored."""
    content = text(make_run())
    assert content.index("Patient-reported medications") < content.index("FHIR medications")
    assert content.index("FHIR medications") < content.index("Pharmacy medications")
    assert "ibuprofen 200 mg once daily" in content
    assert "metoprolol tartrate 25 mg once daily" in content
    assert "metformin 1000 mg once daily" in content


def test_empty_medication_table_says_none():
    """A source with no accepted records prints (none) rather than an empty table."""
    assert "Patient-reported medications (none)" in text(make_run(intake=[]))


def test_each_finding_shows_all_three_values():
    """Findings carry the three value columns, with a dash for a source without one."""
    content = text(make_run())
    assert "Medication Summary Patient-reported FHIR Pharmacy" in content
    assert "200 mg — —" in content  # ibuprofen: only the intake value


def test_rejected_records_are_listed_with_reasons():
    """Rejections show source, name and reason."""
    content = text(make_run())
    assert "Rejected records" in content
    assert "Pharmacy warfarin dose_amount: not a number" in content


def test_every_page_of_a_long_report_carries_the_disclaimer():
    """A run that spans pages repeats the disclaimer and numbers each page."""
    many = [
        Finding(
            discrepancy_type="missing",
            medication=f"drug{i}",
            summary="On the FHIR list; not reported by the patient and not in pharmacy records.",
            fhir_value="10 mg",
        )
        for i in range(80)
    ]
    report = pages(build_report(make_run(findings=many)))
    assert len(report) > 1
    for number, page in enumerate(report, start=1):
        assert DISCLAIMER in page and f"Page {number}" in page
