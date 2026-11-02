"""PDF report: pypdf text covers patient, disclaimer, interview, three values and unicode."""

import io

import pytest
from pypdf import PdfReader
from sqlalchemy.exc import OperationalError

from app.labels import DISCLAIMER, NLM_ATTRIBUTION
from app.pdf import (
    BOTTOM_MARGIN,
    FOOTER_HEIGHT,
    MAX_CELL_CHARS,
    TRUNCATED,
    build_report,
    report_filename,
)
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
    """Output starts with %PDF- and names the patient, the run and its time, and the disclaimer."""
    report = build_report(make_run())
    assert report.startswith(b"%PDF-")
    content = " ".join(pages(report))
    assert "Marcus Mixton CASE-MIXED · Run 7 · 2026-10-30 14:05 UTC" in content
    assert DISCLAIMER in content


def test_disclaimer_is_a_footnote_not_part_of_the_header():
    """The disclaimer sits once per page at the foot, after the page's content."""
    first = pages(build_report(make_run()))[0]
    assert first.count(DISCLAIMER) == 1
    assert first.index("Medications compared") < first.index(DISCLAIMER)


def test_report_names_neither_the_fhir_id_nor_synthetic_data():
    """The FHIR id is an internal number and the data's origin isn't the clinician's concern."""
    content = text(make_run())
    assert "FHIR id" not in content and "2178" not in content
    assert "ynthetic" not in content


def test_zero_findings_says_no_discrepancies_found():
    """A clean run states it plainly."""
    assert "No discrepancies found" in text(make_run(findings=[]))


def test_findings_never_claim_no_discrepancies():
    """A run with findings gives counts per type instead of the clean statement."""
    content = text(make_run())
    assert "No discrepancies found" not in content
    assert "2 Missing medication" in content and "1 Dosage mismatch" in content


def test_unknown_type_renders_as_other_with_its_stored_summary():
    """A type from a newer release is labelled Other (x) and keeps its summary and values."""
    content = text(make_run())
    assert "Other (route_mismatch)" in content
    assert "FHIR route oral; pharmacy route topical." in content
    assert "sertraline ✕ Not listed oral topical" in content  # cells, then the stored summary


def test_micro_signs_and_em_dash_render():
    """Both micro characters and an em dash survive; core PDF fonts would raise on these."""
    finding = Finding(
        discrepancy_type="dosage_mismatch",
        medication="cyanocobalamin",
        summary="Different form: FHIR Oral Tablet — coated; pharmacy Oral Tablet.",
        intake_value="50 µg",  # U+00B5 micro sign
        fhir_value="100 μg",  # U+03BC Greek mu
    )
    content = text(make_run(findings=[finding]))
    assert "Different form: FHIR Oral Tablet — coated; pharmacy Oral Tablet." in content
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
    compared = content[content.index("Medications compared") :]
    assert compared.index("Patient-reported Name") < compared.index("FHIR Name")
    assert compared.index("FHIR Name") < compared.index("Pharmacy Name")
    assert "ibuprofen 200 mg once daily" in content
    assert "metoprolol tartrate 25 mg once daily" in content
    assert "metformin 1000 mg once daily" in content


def test_empty_medication_table_says_none_reported():
    """A source with no accepted records says so rather than printing an empty table."""
    assert "Patient-reported None reported FHIR" in text(make_run(intake=[]))


def test_each_finding_shows_all_three_values():
    """Findings carry the three value columns; a source without one says so, with no sentence."""
    content = text(make_run())
    assert "Medication Patient-reported FHIR Pharmacy" in content
    assert "ibuprofen 200 mg ✕ Not listed ✕ Not listed" in content
    assert "Reported by the patient; not on the FHIR list" not in content


def test_a_rejected_record_shows_as_a_badge_in_its_source_column():
    """Pharmacy's rejected warfarin reads Rejected, not Not listed, and needs no sentence."""
    finding = Finding(
        discrepancy_type="missing",
        medication="warfarin",
        summary="On the FHIR list; not in pharmacy records. 1 pharmacy record with this name was "
        "rejected (see Rejected records).",
        fhir_value="5 mg",
        details={"missing_from": ["intake", "pharmacy"], "rejected_record_ids": ["PH-9"]},
    )
    content = text(make_run(findings=[finding]))
    assert "warfarin ✕ Not listed 5 mg ⚠ Rejected" in content
    assert "see Rejected records" not in content


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
        'attachment; filename="MedRec-Marcus-Mixton-CASE-MIXED-run-7-2026-10-30.pdf"'
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
    assert "Patient-reported No interview recorded FHIR" in content
    assert "metformin No interview 500 mg 1000 mg" in content
    assert "Records compared: 2 FHIR, 1 pharmacy. Rejected: 1." in content


def test_report_with_a_no_medications_interview_keeps_the_count_and_none():
    """The patient was asked and reports nothing, so that source did take part."""
    interview = INTERVIEW.model_copy(update={"no_medications": True})
    content = text(make_run(intake_interview=interview, intake=[]))
    assert "Patient-reported None reported FHIR" in content
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
    over = Finding(discrepancy_type="route_mismatch", medication="x", summary="words " * 200)
    assert " ".join(TRUNCATED.split()) in text(make_run(findings=[over]))
    under = Finding(discrepancy_type="route_mismatch", medication="x", summary=at_cap)
    assert "truncated" not in text(make_run(findings=[under]))


def test_frequency_finding_has_its_own_label_in_the_report():
    """The report labels it and its cells print the plain wording, not an abbreviation."""
    finding = Finding(
        discrepancy_type="frequency_mismatch",
        medication="sertraline",
        summary="FHIR frequency once daily; pharmacy frequency twice daily.",
        fhir_value="once daily",
        pharmacy_value="twice daily",
    )
    content = text(make_run(findings=[finding]))
    assert "1 Frequency mismatch" in content and "Other (" not in content
    assert "sertraline ✕ Not listed once daily twice daily" in content


def test_every_page_of_the_report_has_the_nlm_attribution():
    """The attribution travels with the report on every page, in NLM's exact words."""
    many = [
        Finding(discrepancy_type="missing", medication=f"drug{i}", summary="Listed in FHIR.")
        for i in range(80)
    ]
    report = pages(build_report(make_run(findings=many)))
    assert len(report) > 1
    assert all(NLM_ATTRIBUTION in page and DISCLAIMER in page for page in report)


def test_footer_stays_inside_the_bottom_margin():
    """The longer footer starts below where the page body stops, so they can't overlap."""
    assert FOOTER_HEIGHT <= BOTTOM_MARGIN


def test_report_labels_a_brand_with_its_ingredient():
    """The report shows the match beside the source's own name."""
    brand = record("pharmacy", "Zoloft", "50").model_copy(
        update={"normalized_name": "sertraline", "rxcui": "82728"}
    )
    content = text(make_run(pharmacy=[brand]))
    assert "Zoloft (matched as sertraline) 50 mg" in content
    assert content.count("matched as") == 1


def test_report_lists_medications_with_no_differences():
    """The section and its summary count appear when findings exist too."""
    content = text(
        make_run(
            intake=[record("intake", "metformin", "0.5", "g", "twice a day")],
            fhir=[record("fhir", "metformin", "500", frequency="BID")],
            pharmacy=[record("pharmacy", "metformin", "500", frequency="twice daily")],
            intake_interview=INTERVIEW,
            rejected=[],
            findings=[Finding(discrepancy_type="missing", medication="x", summary="y")],
        )
    )
    assert "1 No differences" in content
    assert "no source is treated as correct" in content
    for value in ("0.5 g, twice a day", "500 mg, BID", "500 mg, twice daily"):
        assert value in content


def test_report_omits_no_differences_when_nothing_agrees():
    """A run with nothing in common has no empty section."""
    assert "No differences" not in text(make_run())


@pytest.mark.parametrize(
    ("name", "identifier", "expected"),
    [
        ("Marcus Mixton", "CASE-MIXED", "MedRec-Marcus-Mixton-CASE-MIXED-run-7-2026-10-30.pdf"),
        ("José O'Brien", "CASE-X", "MedRec-Jose-O-Brien-CASE-X-run-7-2026-10-30.pdf"),
        (None, "CASE-X", "MedRec-CASE-X-run-7-2026-10-30.pdf"),
    ],
    ids=["plain", "accents-and-quote", "no-name"],
)
def test_download_name_says_whose_report_it_is(name, identifier, expected):
    """The file name carries the patient, identifier, run and date, in characters any OS keeps."""
    patient = make_run().patient.model_copy(update={"name": name, "identifier": identifier})
    assert report_filename(make_run(patient=patient)) == expected


def test_report_title_names_the_patient_and_run():
    """A PDF viewer's title bar shows whose report it is."""
    reader = PdfReader(io.BytesIO(build_report(make_run())))
    assert reader.metadata.title == "Marcus Mixton · Medication reconciliation, run 7"


def test_every_table_cell_names_its_own_fill(monkeypatch):
    """Without one, fpdf2 reuses the last colour drawn and a whole row came out in a type colour."""
    from fpdf.table import Row

    styles = []
    original = Row.cell

    def recording_cell(self, text="", *args, style=None, **kwargs):
        """Row.cell, noting the style each body cell asked for."""
        styles.append((text, style))
        return original(self, text, *args, style=style, **kwargs)

    monkeypatch.setattr(Row, "cell", recording_cell)
    build_report(make_run(intake=[record("intake", "ibuprofen", "200", frequency=None)]))
    body = [(text, style) for text, style in styles if style is not None]
    assert body and all(style.fill_color is not None for _, style in body)
    headings = {"Medication", "Patient-reported", "FHIR", "Pharmacy", "Name", "Dose", "Frequency"}
    headings |= {"Source", "Reason"}
    assert {text for text, style in styles if style is None} <= headings
