"""PDF report: pypdf text covers patient, disclaimer, interview, three values and unicode."""

import io

import pytest
from pypdf import PdfReader
from sqlalchemy.exc import OperationalError

from app.labels import DISCLAIMER
from app.pdf import MAX_CELL_CHARS, TRUNCATED, build_report
from contract import Finding, Reason, Rejection
from db import repo
from tests.app.conftest import INTERVIEW, make_run, record


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
    assert "— QD BID" in content  # no intake value, then the stored FHIR and pharmacy values


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


def test_report_route_returns_a_pdf_download(client, serve_run):
    """GET /runs/{id}/report.pdf is a PDF attachment with the run's content."""
    serve_run(make_run())
    response = client.get("/runs/7/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="reconciliation-run-7.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert "Marcus Mixton" in " ".join(pages(response.content))


def test_report_of_a_missing_run_is_the_404_page(client, serve_run):
    """An unknown run id gives the readable 404 page, not a PDF."""
    serve_run(None)
    response = client.get("/runs/999/report.pdf")
    assert response.status_code == 404
    assert "Run not found" in response.text and DISCLAIMER in response.text


def test_run_page_links_to_the_report(client, serve_run):
    """The run page offers the PDF download."""
    serve_run(make_run())
    assert 'href="/runs/7/report.pdf"' in client.get("/runs/7").text


def test_report_with_the_database_down_is_a_503_page(client, serve_run, monkeypatch):
    """A database outage reaches the shared 503 page rather than a broken download."""

    def down(session, run_id):
        """Stand-in for repo.get_run when Postgres refuses connections."""
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))

    serve_run(None)
    monkeypatch.setattr(repo, "get_run", down)
    response = client.get("/runs/7/report.pdf")
    assert response.status_code == 503 and "Database unavailable" in response.text


def test_report_without_an_interview_says_no_data_for_the_patient_side():
    """No interview isn't an empty list: the table says No data and the count isn't a false 0."""
    content = text(make_run(intake_interview=None, intake=[]))
    assert "Patient-reported medications No data" in content
    assert "Records compared: 2 FHIR, 1 pharmacy. Rejected: 1." in content


def test_report_with_a_no_medications_interview_keeps_the_count_and_none():
    """The patient was asked and reports nothing, so that source did take part."""
    interview = INTERVIEW.model_copy(update={"no_medications": True})
    content = text(make_run(intake_interview=interview, intake=[]))
    assert "Patient-reported medications (none)" in content
    assert "Records compared: 0 patient-reported, 2 FHIR, 1 pharmacy." in content


@pytest.mark.parametrize("length", [MAX_CELL_CHARS, MAX_CELL_CHARS + 1, 5000])
def test_very_long_values_in_every_table_column_still_build_a_report(length):
    """Wide unbroken text in every cell can't make a row taller than a page, which would raise."""
    long = "W" * length
    finding = Finding(
        discrepancy_type="missing",
        medication=long,
        summary=long,
        intake_value=long,
        fhir_value=long,
        pharmacy_value=long,
    )
    rejection = Rejection(
        source="pharmacy",
        name=long,
        reasons=[Reason(field="dose_amount", code="unreadable_dosage", message=long)],
    )
    run = make_run(
        findings=[finding] * 3,
        intake=[record("intake", long, frequency=long)],
        fhir=[record("fhir", long, frequency=long)],
        pharmacy=[record("pharmacy", long, frequency=long)],
        rejected=[rejection],
    )
    assert build_report(run).startswith(b"%PDF-")


def test_long_cell_is_visibly_truncated_and_short_ones_are_not():
    """A cut value says so, so nothing disappears silently; values under the cap are untouched."""
    at_cap = "words " * (MAX_CELL_CHARS // 6)
    over = Finding(discrepancy_type="missing", medication="x", summary="words " * 200)
    assert " ".join(TRUNCATED.split()) in text(make_run(findings=[over]))
    under = Finding(discrepancy_type="missing", medication="x", summary=at_cap)
    assert "truncated" not in text(make_run(findings=[under]))
