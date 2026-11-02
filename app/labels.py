"""Display text shared by pages and the PDF.

Unknown finding types render as "Other (x)" so an older release can still show findings
written by a newer one (tolerant reader).
"""

from datetime import UTC, datetime

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

DISCLAIMER = (
    "Synthetic data. Reports discrepancies between sources for clinician review; "
    "does not recommend treatment."
)

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


NO_DIFFERENCES_NOTE = (
    "Each of these is in every source compared and has no finding. "
    "Values are as each source states them; no source is treated as correct. "
    "A frequency marked (not compared) gives no schedule to compare, so it may still differ."
)

# Medication column headings in display order.
SOURCE_HEADINGS: dict[str, str] = {
    "intake": "Patient-reported",
    "fhir": "FHIR",
    "pharmacy": "Pharmacy",
}


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
