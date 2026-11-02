"""PDF report of one saved run, in fpdf2 with bundled DejaVu fonts so µ and — render anywhere.

It reads like the run page: count tiles, then finding tables whose cells hold each source's
value or a badge saying why there is none, with a note row only for what the cells can't show.
"""

import re
import unicodedata
from pathlib import Path

from fpdf import FPDF, FontFace
from fpdf.enums import CellBordersLayout

from app.labels import (
    DISCLAIMER,
    LABELS,
    NLM_ATTRIBUTION,
    SOURCE_HEADINGS,
    Cell,
    finding_cells,
    finding_note,
    group_findings,
    interview_line,
    matched_as,
    no_differences,
    no_differences_note,
    utc_time,
)
from app.version import __version__
from contract import MedicationRecord, RunDetail, format_dose

FONTS = Path(__file__).resolve().parent / "fonts"
FAMILY = "DejaVu"
EMPTY = "—"
NEXT_LINE = {"new_x": "LMARGIN", "new_y": "NEXT"}
MAX_CELL_CHARS = 400  # keeps any table row shorter than a page, which fpdf2 requires
TRUNCATED = "… [truncated; full text on the run page]"
BOTTOM_MARGIN = 22  # mm the page body stays above the bottom edge
FOOTER_HEIGHT = 20  # mm the footer starts above the bottom edge, inside that margin
KEEP_WITH_TABLE = 30  # mm a heading needs below it, so it isn't stranded at the foot of a page

RGB = tuple[int, int, int]
INK: RGB = (31, 41, 51)
MUTED: RGB = (95, 107, 122)
LINE: RGB = (230, 233, 238)
HEAD: RGB = (243, 245, 248)
ACCENT: RGB = (15, 124, 134)
ACCENT_SOFT: RGB = (231, 243, 244)
WHITE: RGB = (255, 255, 255)

# The same colours the pages use to tell finding types apart.
TYPE_COLOURS: dict[str, RGB] = {
    "duplicate": (109, 79, 179),
    "missing": (168, 93, 10),
    "dosage_mismatch": (31, 111, 178),
    "frequency_mismatch": (163, 49, 122),
    "no_differences": (46, 125, 79),
}
OTHER: RGB = (102, 112, 124)

# How each kind of cell reads: (text before the cell's own text, text colour, fill).
BADGES: dict[str, tuple[str, RGB, RGB | None]] = {
    "not_listed": ("✕ ", (155, 44, 44), (253, 238, 238)),
    "rejected": ("⚠ ", (138, 75, 0), (255, 244, 224)),
    "no_interview": ("", MUTED, HEAD),
    "listed": ("", MUTED, WHITE),
}
# Every cell names its fill: fpdf2 would otherwise reuse whatever colour was drawn last.
PLAIN = FontFace(color=INK, fill_color=WHITE)
BOLD = FontFace(emphasis="BOLD", color=INK, fill_color=WHITE)
FAINT = FontFace(color=MUTED, fill_color=WHITE)


def _tint(colour: RGB, share: float) -> RGB:
    """The colour mixed into white, so a type's fill stays light behind dark text."""
    return tuple(round(c * share + 255 * (1 - share)) for c in colour)


def _type_colour(discrepancy_type: str) -> RGB:
    """A known type's colour, or neutral grey for one this release doesn't know."""
    return TYPE_COLOURS.get(discrepancy_type, OTHER)


class _Report(FPDF):
    """A4 pages with a footnote on each: who and which run, page numbers, disclaimer, NLM."""

    def __init__(self, run: RunDetail):
        """Keep the run so every page's footnote can name the patient and the run."""
        super().__init__(format="A4")
        self.run = run

    def footer(self) -> None:
        """A thin rule, then the run line with page numbers, the disclaimer and attribution."""
        patient = self.run.patient
        self.set_y(-FOOTER_HEIGHT)
        self.set_draw_color(*LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5)
        self.set_text_color(*MUTED)
        self.set_font(FAMILY, size=7)
        who = f"MedRec {__version__} · {patient.name or patient.identifier} · Run {self.run.run_id}"
        self.cell(0, 3.5, who, align="L")
        self.set_x(self.l_margin)
        self.cell(0, 3.5, f"Page {self.page_no()} of {{nb}}", align="R", **NEXT_LINE)
        self.cell(0, 3.5, DISCLAIMER, align="L", **NEXT_LINE)
        self.set_font(FAMILY, size=5.5)
        self.multi_cell(0, 2.5, NLM_ATTRIBUTION, align="L", **NEXT_LINE)
        self.set_text_color(*INK)


def report_filename(run: RunDetail) -> str:
    """A download name that says whose report it is: MedRec-Marcus-Mixton-CASE-MIXED-run-7-....

    Letters outside ASCII are reduced to their base letter, so every browser keeps the name.
    """
    patient = run.patient
    parts = [
        "MedRec",
        patient.name or "",
        patient.identifier,
        f"run-{run.run_id}",
        f"{run.started_at:%Y-%m-%d}",
    ]
    ascii_text = unicodedata.normalize("NFKD", " ".join(parts)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-") + ".pdf"


def build_report(run: RunDetail) -> bytes:
    """Render a run: patient, counts, findings, what agrees, the three lists and rejections."""
    pdf = _Report(run)
    pdf.add_font(FAMILY, fname=FONTS / "DejaVuSans.ttf")
    pdf.add_font(FAMILY, style="B", fname=FONTS / "DejaVuSans-Bold.ttf")
    pdf.set_auto_page_break(True, margin=BOTTOM_MARGIN)
    name = run.patient.name or run.patient.identifier
    pdf.set_title(f"{name} · Medication reconciliation, run {run.run_id}")
    pdf.set_author("MedRec")
    pdf.add_page()
    rejected_link = pdf.add_link()

    _header(pdf, run)
    _summary(pdf, run)
    _findings(pdf, run, rejected_link)
    _no_differences(pdf, run)
    _heading(pdf, "Medications compared")
    _medications(
        pdf,
        "Patient-reported",
        run.intake,
        empty="None reported" if run.intake_interview else "No interview recorded",
    )
    _medications(pdf, "FHIR", run.fhir)
    _medications(pdf, "Pharmacy", run.pharmacy)
    _rejected(pdf, run, rejected_link)
    return bytes(pdf.output())


def _header(pdf: FPDF, run: RunDetail) -> None:
    """Brand line, the patient's name, who they are and when the run was made, and the interview."""
    patient = run.patient
    top = pdf.get_y()
    # Brand mark: a rounded square holding three list lines, as on the pages.
    pdf.set_fill_color(*ACCENT)
    pdf.rect(pdf.l_margin, top, 6, 6, style="F", round_corners=True, corner_radius=1.5)
    pdf.set_draw_color(*WHITE)
    pdf.set_line_width(0.5)
    for y, length in ((1.9, 2.6), (3.0, 3.4), (4.1, 2.0)):
        pdf.line(pdf.l_margin + 1.6, top + y, pdf.l_margin + 1.6 + length, top + y)
    pdf.set_line_width(0.2)
    pdf.set_xy(pdf.l_margin + 8, top)
    pdf.set_font(FAMILY, "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(30, 6, "MedRec")
    pdf.set_font(FAMILY, size=9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, "Medication reconciliation report", align="R", **NEXT_LINE)
    pdf.ln(5)

    pdf.set_text_color(*INK)
    pdf.set_font(FAMILY, "B", 16)
    pdf.multi_cell(0, 8, patient.name or patient.identifier, **NEXT_LINE)
    details = [patient.identifier]
    if patient.birth_date:
        details.append(f"born {patient.birth_date}")
    if patient.gender:
        details.append(patient.gender)
    details.append(f"Run {run.run_id} · {utc_time(run.started_at)} UTC")
    pdf.set_font(FAMILY, size=9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 5, " · ".join(details), **NEXT_LINE)
    pdf.ln(2)
    _chip(pdf, interview_line(run.intake_interview), ACCENT_SOFT, (22, 78, 86))
    pdf.ln(4)


def _chip(pdf: FPDF, text: str, fill: RGB, colour: RGB) -> None:
    """A short line of text on a rounded tinted background."""
    pdf.set_font(FAMILY, size=9)
    width = pdf.get_string_width(text) + 6
    y = pdf.get_y()
    pdf.set_fill_color(*fill)
    pdf.rect(pdf.l_margin, y, width, 6.5, style="F", round_corners=True, corner_radius=1.5)
    pdf.set_text_color(*colour)
    pdf.set_xy(pdf.l_margin + 3, y)
    pdf.cell(width - 6, 6.5, text, **NEXT_LINE)
    pdf.set_text_color(*INK)


def _summary(pdf: FPDF, run: RunDetail) -> None:
    """A tile per finding type with its count, or the no-discrepancy statement; then the totals."""
    groups = group_findings(run.findings)
    tiles = [(len(fs), label, fs[0].discrepancy_type) for label, fs in groups]
    if groups and (agreeing := no_differences(run)):
        tiles.append((len(agreeing), "No differences", "no_differences"))
    if tiles:
        _tiles(pdf, tiles)
    else:
        _chip(pdf, "No discrepancies found", _tint(TYPE_COLOURS["no_differences"], 0.1), INK)
        pdf.ln(2)
    intake = f"{len(run.intake)} patient-reported, " if run.intake_interview else ""
    pdf.set_font(FAMILY, size=8)
    pdf.set_text_color(*MUTED)
    pdf.cell(
        0,
        5,
        f"Records compared: {intake}{len(run.fhir)} FHIR, {len(run.pharmacy)} pharmacy. "
        f"Rejected: {len(run.rejected)}.",
        **NEXT_LINE,
    )
    pdf.set_text_color(*INK)


def _tiles(pdf: FPDF, tiles: list[tuple[int, str, str]]) -> None:
    """Count tiles in one row, each tinted with its type's colour."""
    gap, height = 3, 17
    width = (pdf.epw - gap * (len(tiles) - 1)) / len(tiles)
    y = pdf.get_y()
    for index, (count, label, discrepancy_type) in enumerate(tiles):
        colour = _type_colour(discrepancy_type)
        x = pdf.l_margin + index * (width + gap)
        pdf.set_fill_color(*_tint(colour, 0.07))
        pdf.set_draw_color(*_tint(colour, 0.25))
        pdf.rect(x, y, width, height, style="DF", round_corners=True, corner_radius=2)
        pdf.set_xy(x + 3, y + 2)
        pdf.set_font(FAMILY, "B", 15)
        pdf.set_text_color(*colour)
        pdf.cell(width - 6, 7, str(count))
        pdf.set_xy(x + 3, y + 9.5)
        pdf.set_font(FAMILY, size=8)
        pdf.set_text_color(*INK)
        pdf.cell(width - 6, 5, label)
    pdf.set_xy(pdf.l_margin, y + height + 2)


def _findings(pdf: FPDF, run: RunDetail, rejected_link: int) -> None:
    """One table per discrepancy type; cells are values or badges, notes only where they add."""
    for label, findings in group_findings(run.findings):
        discrepancy_type = findings[0].discrepancy_type
        _heading(pdf, label, _type_colour(discrepancy_type))
        rows = [
            ([(f.medication, BOLD), *map(_cell_text, finding_cells(f, run))], finding_note(f))
            for f in findings
        ]
        _table(
            pdf,
            ["Medication", *SOURCE_HEADINGS.values()],
            rows,
            widths=(31, 23, 23, 23),
            rejected_link=rejected_link,
            known=discrepancy_type in LABELS,
        )


def _cell_text(cell: Cell) -> tuple[str, FontFace]:
    """What a cell prints and how: a value as stated, or a tinted badge for why there's none."""
    if cell.kind == "value":
        text = cell.text.replace("; ", "\n")
        return (f"{cell.count} records\n{text}" if cell.count else text), PLAIN
    prefix, colour, fill = BADGES.get(cell.kind, ("", MUTED, WHITE))
    return prefix + cell.text, FontFace(color=colour, fill_color=fill)


def _no_differences(pdf: FPDF, run: RunDetail) -> None:
    """Medications every compared source lists with no finding; no section if there are none."""
    agreeing = no_differences(run)
    if not agreeing:
        return
    _heading(pdf, "No differences", TYPE_COLOURS["no_differences"])
    _note(pdf, no_differences_note(agreeing))
    no_interview = _cell_text(Cell("no_interview", "No interview"))
    rows = [
        (
            [(name, BOLD)]
            + [(stated[s], PLAIN) if s in stated else no_interview for s in SOURCE_HEADINGS],
            "",
        )
        for name, stated in agreeing
    ]
    _table(pdf, ["Medication", *SOURCE_HEADINGS.values()], rows, widths=(31, 23, 23, 23))


def _medications(
    pdf: FPDF, title: str, records: list[MedicationRecord], empty: str = "None"
) -> None:
    """One source's accepted records, or why it has none; frequency is shown as stored."""
    _subheading(pdf, title)
    if not records:
        _note(pdf, empty)
        return
    rows = [
        (
            [
                (_named(r), PLAIN),
                (format_dose(r.dose_amount, r.dose_unit), PLAIN),
                (r.frequency or EMPTY, PLAIN if r.frequency else FAINT),
            ],
            "",
        )
        for r in records
    ]
    _table(pdf, ["Name", "Dose", "Frequency"], rows, widths=(55, 15, 30))


def _named(record: MedicationRecord) -> str:
    """The record's own name, plus what RxNorm matched it to when that isn't plain from the name."""
    matched = matched_as(record)
    return f"{record.name} (matched as {matched})" if matched else record.name


def _rejected(pdf: FPDF, run: RunDetail, link: int) -> None:
    """Records that failed validation, kept with their reasons; no section when there are none."""
    if not run.rejected:
        return
    _heading(pdf, "Rejected records")
    pdf.set_link(link, y=max(pdf.get_y() - 10, 0), page=pdf.page_no())
    rows = [
        (
            [
                (SOURCE_HEADINGS.get(r.source, r.source), PLAIN),
                (r.name or EMPTY, PLAIN if r.name else FAINT),
                ("; ".join(f"{reason.field}: {reason.message}" for reason in r.reasons), PLAIN),
            ],
            "",
        )
        for r in run.rejected
    ]
    _table(pdf, ["Source", "Name", "Reason"], rows, widths=(17, 28, 55))


def _heading(pdf: FPDF, text: str, dot: RGB | None = None) -> None:
    """A section heading, with its type's dot, moved on if its table wouldn't start on this page."""
    if pdf.will_page_break(KEEP_WITH_TABLE):
        pdf.add_page()
    pdf.ln(4)
    y = pdf.get_y()
    x = pdf.l_margin
    if dot:
        pdf.set_fill_color(*dot)
        pdf.circle(x + 1.3, y + 4, 1.3, style="F")
        x += 4.5
    pdf.set_xy(x, y)
    pdf.set_font(FAMILY, "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 8, text, **NEXT_LINE)
    pdf.ln(0.5)


def _subheading(pdf: FPDF, text: str) -> None:
    """A smaller heading for one source's list inside a section."""
    if pdf.will_page_break(KEEP_WITH_TABLE - 8):
        pdf.add_page()
    pdf.ln(1.5)
    pdf.set_font(FAMILY, "B", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, text, **NEXT_LINE)
    pdf.set_text_color(*INK)


def _note(pdf: FPDF, text: str) -> None:
    """A short grey line under a heading."""
    pdf.set_font(FAMILY, size=8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4.5, text, align="L", **NEXT_LINE)
    pdf.set_text_color(*INK)
    pdf.ln(1)


def _table(
    pdf: FPDF,
    header: list[str],
    rows: list[tuple[list[tuple[str, FontFace]], str]],
    widths: tuple[int, ...],
    rejected_link: int | None = None,
    known: bool = True,
) -> None:
    """Rows of styled cells under light rules, each followed by its note row when it has one.

    A note from a type this release doesn't know is its whole stored summary, so it's printed
    in ink rather than grey: it may be the only explanation of the row.
    """
    pdf.set_font(FAMILY, size=8)
    pdf.set_draw_color(*LINE)
    note_style = FontFace(color=MUTED if known else INK, size_pt=7, fill_color=WHITE)
    with pdf.table(
        col_widths=widths,
        text_align="LEFT",
        borders_layout="HORIZONTAL_LINES",
        headings_style=FontFace(emphasis="BOLD", color=MUTED, size_pt=7, fill_color=HEAD),
        line_height=4.2,
        padding=(1.6, 1.8),
        v_align="TOP",
    ) as table:
        heading = table.row()
        for text in header:
            heading.cell(text)
        for cells, note in rows:
            row = table.row()
            # A row with a note keeps no rule under it, so the note reads as part of the row.
            border = CellBordersLayout.TOP if note else CellBordersLayout.INHERIT
            for text, style in cells:
                link = rejected_link if rejected_link and text.endswith("Rejected") else None
                row.cell(_fit(text), style=style, link=link, border=border)
            if note:
                table.row().cell(
                    _fit(note),
                    style=note_style,
                    colspan=len(header),
                    border=CellBordersLayout.BOTTOM,
                    padding=(0, 1.8, 1.6, 1.8),
                )
    pdf.set_draw_color(*INK)


def _fit(value: str) -> str:
    """The cell text, visibly cut if it's so long that its row couldn't fit on one page."""
    return value if len(value) <= MAX_CELL_CHARS else value[:MAX_CELL_CHARS] + TRUNCATED
