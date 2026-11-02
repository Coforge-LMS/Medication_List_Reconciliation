"""Display text shared by pages and the PDF.

Unknown finding types render as "Other (x)" so an older release can still show findings
written by a newer one (tolerant reader).
"""

import re
from datetime import UTC, datetime
from typing import NamedTuple

from contract import (
    Finding,
    IntakeInterviewInfo,
    MedicationRecord,
    ReconciliationInput,
    RunDetail,
    format_dose,
)
from rules.base import by_name, identity, participating
from rules.frequency import PRN, normalize_frequency

DISCLAIMER = "For clinician review; does not recommend treatment."

# Required wherever RxNorm data from RxNav is used, in NLM's own words.
NLM_ATTRIBUTION = (
    "This product uses publicly available data from the U.S. National Library of Medicine (NLM), "
    "National Institutes of Health, Department of Health and Human Services; NLM is not "
    "responsible for the product and does not endorse or recommend this or any other product."
)

LABELS: dict[str, str] = {
    "duplicate": "Duplicate medication",
    "missing": "Missing medication",
    "dosage_mismatch": "Dosage mismatch",
    "frequency_mismatch": "Frequency mismatch",
}


def label_for(discrepancy_type: str) -> str:
    return LABELS.get(discrepancy_type, f"Other ({discrepancy_type})")


def matched_as(record: MedicationRecord) -> str | None:
    """The ingredient RxNorm matched this record to, when its own name doesn't make that plain.

    "Zoloft" gives "sertraline"; "sertraline 50 MG Oral Tablet" gives None, so the label appears
    only where it explains something.
    """
    if not record.rxcui or not record.normalized_name:
        return None
    name = record.name.lower()
    plain = all(ingredient in name for ingredient in record.normalized_name.split(" / "))
    return None if plain else record.normalized_name


NO_DIFFERENCES_NOTE = "In every source compared, with no finding; no source is treated as correct."
NOT_COMPARED_NOTE = "A frequency marked (not compared) had no schedule to compare; it may differ."


def no_differences_note(rows: list[tuple[str, dict[str, str]]]) -> str:
    """The note under No differences, naming (not compared) only when a row shows it."""
    if any("(not compared)" in value for _, stated in rows for value in stated.values()):
        return f"{NO_DIFFERENCES_NOTE} {NOT_COMPARED_NOTE}"
    return NO_DIFFERENCES_NOTE


# Medication column headings in display order.
SOURCE_HEADINGS: dict[str, str] = {
    "intake": "Patient-reported",
    "fhir": "FHIR",
    "pharmacy": "Pharmacy",
}


class Cell(NamedTuple):
    """What one source shows in a finding row: its value, or a badge saying why there is none.

    kind is "value", "not_listed", "rejected", "no_interview" or "listed": the source lists the
    medication but isn't part of this finding, like the single-record side of a duplicate.
    """

    kind: str
    text: str
    count: int | None = None


def finding_cells(finding: Finding, run: RunDetail) -> list[Cell]:
    """One cell per source, in column order, so a row reads at a glance without its summary.

    A source left out of a missing finding is "Rejected" when a record of its with this name was
    rejected, else "Not listed". Runs saved before details named those sources fall back to the
    records and rejections the run kept.
    """
    details = finding.details or {}
    missing_from = details.get("missing_from") or []
    missing_from = [missing_from] if isinstance(missing_from, str) else missing_from
    rejected_ids = set(details.get("rejected_record_ids") or [])
    cells = []
    for source in SOURCE_HEADINGS:
        value = getattr(finding, f"{source}_value")
        rejected = any(
            r.source == source
            and (r.source_record_id in rejected_ids or identity(r) == finding.medication)
            for r in run.rejected
        )
        listed = sum(identity(r) == finding.medication for r in getattr(run, source))
        if value:
            count = details.get("count") if details.get("source") == source else None
            cells.append(Cell("value", value, count))
        elif source == "intake" and run.intake_interview is None:
            cells.append(Cell("no_interview", "No interview"))
        elif rejected and (source in missing_from or not listed):
            cells.append(Cell("rejected", "Rejected"))
        elif source in missing_from or not listed:
            cells.append(Cell("not_listed", "Not listed"))
        elif finding.discrepancy_type == "frequency_mismatch":
            cells.append(Cell("listed", "No frequency"))
        else:
            cells.append(Cell("listed", f"{listed} record{'s' if listed > 1 else ''}"))
    return cells


# Summary sentences that say more than a row's cells and badges already do.
EXTRA_NOTES = ("Different ", "Same ingredient")
DIFFERENT_MEASURE = "Doses are recorded in a different measure"


def finding_note(finding: Finding) -> str:
    """The part of a summary the row doesn't already show: salt, form and measure differences.

    "On the FHIR list; not reported by the patient ..." repeats what the cells say, so it's
    dropped. A type this release doesn't know keeps its whole stored summary.
    """
    if finding.discrepancy_type not in LABELS:
        return finding.summary
    kept = []
    for part in re.split(r"(?<=\.)\s+", finding.summary.strip()):
        if part.startswith(EXTRA_NOTES):
            kept.append(part)
        elif part.startswith(DIFFERENT_MEASURE):
            kept.append("Doses are recorded in different measures.")
    return " ".join(kept)


def interview_line(interview: IntakeInterviewInfo | None) -> str:
    """One line describing the intake interview a run compared, or its absence."""
    if interview is None:
        return "No intake history recorded"
    if interview.no_medications:
        return "Patient reports no medications"
    # Local date, the same day latest_intake_for puts on the intake rows.
    taken_on = interview.taken_at.astimezone()
    return f"Intake taken {taken_on:%Y-%m-%d} by {interview.taken_by} ({interview.informant})"


def group_findings(findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    """(label, findings) per discrepancy type, types in first-seen order; unknown -> Other (x)."""
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        groups.setdefault(f.discrepancy_type, []).append(f)
    return [(label_for(t), fs) for t, fs in groups.items()]


def no_differences(run: RunDetail) -> list[tuple[str, dict[str, str]]]:
    """(medication, {source: what it states}) for those every compared source lists, unflagged.

    A rejected record with the name leaves it out, since that source's record wasn't compared.
    This reports only that no finding was raised: no source is treated as correct.
    """
    data = ReconciliationInput(
        fhir=run.fhir,
        pharmacy=run.pharmacy,
        intake=run.intake if run.intake_interview else None,
        rejected=run.rejected,
    )
    groups = {source: by_name(records) for source, records in participating(data).items()}
    flagged = {f.medication for f in run.findings} | {identity(r) for r in run.rejected}
    shared = set.intersection(*(set(group) for group in groups.values())) - flagged
    return [
        (name, {source: _stated(group[name]) for source, group in groups.items()})
        for name in sorted(shared)
    ]


def _stated(records: list[MedicationRecord]) -> str:
    """Dose and frequency as one source states them: "0.5 g, twice a day"."""
    return "; ".join(
        f"{format_dose(r.dose_amount, r.dose_unit)}, {_frequency(r.frequency)}" for r in records
    )


def _frequency(text: str | None) -> str:
    """Stored frequency wording, marked when the frequency rule doesn't compare it.

    A blank is marked too: "10 mg" beside "10 mg, twice daily" would otherwise read as agreement.
    """
    if not text:
        return "no frequency (not compared)"
    return f"{text} (not compared)" if normalize_frequency(text) in (None, PRN) else text


def utc_time(moment: datetime) -> str:
    """'2026-10-30 14:05' in UTC, whatever zone the database session returned."""
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M}"
