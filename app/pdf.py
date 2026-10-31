"""PDF report of one saved run, in fpdf2 with bundled DejaVu fonts so µ and — render anywhere."""

from pathlib import Path

from fpdf import FPDF

from app.labels import DISCLAIMER, SOURCE_HEADINGS, group_findings, interview_line, utc_time
from contract import MedicationRecord, RunDetail, format_dose

FONTS = Path(__file__).resolve().parent / "fonts"
FAMILY = "DejaVu"
EMPTY = "—"
NEXT_LINE = {"new_x": "LMARGIN", "new_y": "NEXT"}
KEEP_WITH_TABLE = 30  # mm a heading needs below it, so it isn't stranded at the foot of a page


class _Report(FPDF):
    """A4 pages whose footer carries the disclaimer and the page number."""

    def footer(self) -> None:
        """Print the exact disclaimer on every page, not only the first."""
        self.set_y(-15)
        self.set_font(FAMILY, size=8)
        self.cell(0, 4, DISCLAIMER, align="C", **NEXT_LINE)
        self.cell(0, 4, f"Page {self.page_no()}", align="C")


def build_report(run: RunDetail) -> bytes:
    """Render a run: patient, interview, summary, findings, the three lists and rejections."""
    pdf = _Report(format="A4")
    pdf.add_font(FAMILY, fname=FONTS / "DejaVuSans.ttf")
    pdf.add_font(FAMILY, style="B", fname=FONTS / "DejaVuSans-Bold.ttf")
    pdf.set_auto_page_break(True, margin=20)
    pdf.set_title(f"Reconciliation run {run.run_id}")
    pdf.add_page()

    _header(pdf, run)
    _summary(pdf, run)
    _findings(pdf, run)
    _medications(
        pdf,
        "Patient-reported medications",
        run.intake,
        empty="(none)" if run.intake_interview else "No data",
    )
    _medications(pdf, "FHIR medications", run.fhir)
    _medications(pdf, "Pharmacy medications", run.pharmacy)
    _rejected(pdf, run)
    return bytes(pdf.output())


def _header(pdf: FPDF, run: RunDetail) -> None:
    """Title, patient details, when and by which version the run was made, and the interview."""
    patient = run.patient
    pdf.set_font(FAMILY, "B", 16)
    pdf.cell(0, 10, "Medication Reconciliation Report", **NEXT_LINE)
    _lines(
        pdf,
        f"Patient: {patient.name or patient.identifier}",
        f"Identifier: {patient.identifier}",
        f"Birth date: {patient.birth_date or EMPTY}",
        f"Gender: {patient.gender or EMPTY}",
        f"FHIR id: {patient.fhir_patient_id}",
        f"Run {run.run_id}, started {utc_time(run.started_at)} UTC, app version {run.app_version}",
        DISCLAIMER,
        interview_line(run.intake_interview),
    )


def _summary(pdf: FPDF, run: RunDetail) -> None:
    """Finding counts per type, or the no-discrepancy statement, and what was compared."""
    _heading(pdf, "Summary")
    groups = group_findings(run.findings)
    counts = [f"{label}: {len(findings)}" for label, findings in groups]
    intake = f"{len(run.intake)} patient-reported, " if run.intake_interview else ""
    _lines(
        pdf,
        *(counts or ["No discrepancies found"]),
        f"Records compared: {intake}{len(run.fhir)} FHIR, {len(run.pharmacy)} pharmacy. "
        f"Rejected: {len(run.rejected)}.",
    )


def _findings(pdf: FPDF, run: RunDetail) -> None:
    """One table per discrepancy type, each finding with its three compared values."""
    for label, findings in group_findings(run.findings):
        _heading(pdf, label)
        _table(
            pdf,
            ["Medication", "Summary", *SOURCE_HEADINGS.values()],
            [
                [
                    f.medication,
                    f.summary,
                    f.intake_value or EMPTY,
                    f.fhir_value or EMPTY,
                    f.pharmacy_value or EMPTY,
                ]
                for f in findings
            ],
            widths=(16, 33, 19, 16, 16),
        )


def _medications(
    pdf: FPDF, title: str, records: list[MedicationRecord], empty: str = "(none)"
) -> None:
    """One source's accepted records, or empty when it has none; frequency is shown as stored."""
    _heading(pdf, title)
    _table(
        pdf,
        ["Medication", "Dose", "Frequency"],
        [[r.name, format_dose(r.dose_amount, r.dose_unit), r.frequency or EMPTY] for r in records],
        widths=(55, 15, 30),
        empty=empty,
    )


def _rejected(pdf: FPDF, run: RunDetail) -> None:
    """Records that failed validation, kept with their reasons so none is silently dropped."""
    _heading(pdf, "Rejected records")
    _table(
        pdf,
        ["Source", "Name", "Reasons"],
        [
            [
                SOURCE_HEADINGS.get(r.source, r.source),
                r.name or EMPTY,
                "; ".join(f"{reason.field}: {reason.message}" for reason in r.reasons),
            ]
            for r in run.rejected
        ],
        widths=(17, 33, 50),
    )


def _heading(pdf: FPDF, text: str) -> None:
    """A bold section heading, moved to the next page if its table wouldn't start on this one."""
    if pdf.will_page_break(KEEP_WITH_TABLE):
        pdf.add_page()
    pdf.ln(3)
    pdf.set_font(FAMILY, "B", 12)
    pdf.cell(0, 8, text, **NEXT_LINE)


def _lines(pdf: FPDF, *lines: str) -> None:
    """Plain body text, one wrapped paragraph per line."""
    pdf.set_font(FAMILY, size=10)
    for line in lines:
        pdf.multi_cell(0, 5, line, align="L", **NEXT_LINE)


def _table(
    pdf: FPDF,
    header: list[str],
    rows: list[list[str]],
    widths: tuple[int, ...],
    empty: str = "(none)",
) -> None:
    """A table with wrapping cells and headings repeated per page, or the empty text."""
    if not rows:
        _lines(pdf, empty)
        return
    pdf.set_font(FAMILY, size=8)
    with pdf.table(col_widths=widths, text_align="LEFT") as table:
        for values in (header, *rows):
            row = table.row()
            for value in values:
                row.cell(value)
