"""Validate flat medication rows into records and rejections (TECHNICAL_PLAN §4.5, §16).

Serves the pharmacy dataset and, with source="intake", the patient interview rows.
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from contract import MedicationRecord, Reason, Rejection, Source, normalize_unit
from ingest.checks import ACCEPTED_UNITS, check_date, clean, missing, unreadable

UNSURE = "patient unsure of dose"


def validate(
    rows: Iterable[Mapping[str, Any]], source: Source = "pharmacy"
) -> tuple[list[MedicationRecord], list[Rejection]]:
    """Turn rows into accepted records and rejections; nothing is silently dropped.

    Row keys: record_id, patient_id, medication_name, dose_amount, dose_unit, frequency,
    date_recorded. A record can carry several reasons. For source="intake" a blank or
    non-numeric dose is unreadable_dosage ("patient unsure of dose"), not missing_field.
    """
    records: list[MedicationRecord] = []
    rejections: list[Rejection] = []
    for row in rows:
        result = _validate_row(row, source)
        (rejections if isinstance(result, Rejection) else records).append(result)
    return records, rejections


def _validate_row(row: Mapping[str, Any], source: Source) -> MedicationRecord | Rejection:
    record_id = clean(row.get("record_id"))
    patient_id = clean(row.get("patient_id"))
    name = clean(row.get("medication_name"))
    reasons: list[Reason] = []

    if not record_id:
        reasons.append(missing("record_id"))
    if not patient_id:
        reasons.append(missing("patient_id"))
    if not name:
        reasons.append(missing("medication_name", "medication name"))

    amount, dose_reason = _parse_dose(clean(row.get("dose_amount")), source)
    if dose_reason:
        reasons.append(dose_reason)
    unit = None
    unit_text = clean(row.get("dose_unit"))
    if unit_text:
        unit = normalize_unit(unit_text)
        if unit is None:
            reasons.append(
                unreadable("dose_unit", f"unit {unit_text!r} is not one of {ACCEPTED_UNITS}")
            )
    elif not (source == "intake" and dose_reason):  # no unit to ask about without a dose
        reasons.append(missing("dose_unit", "dose unit"))

    recorded, date_reason = check_date(clean(row.get("date_recorded")), "date_recorded")
    if date_reason:
        reasons.append(date_reason)

    if reasons:
        return Rejection(
            source=source,
            source_record_id=record_id or None,
            name=name or None,
            raw=dict(row),
            reasons=reasons,
        )
    return MedicationRecord(
        patient_id=patient_id,
        source=source,
        source_record_id=record_id,
        name=name,
        dose_amount=amount,
        dose_unit=unit,
        frequency=clean(row.get("frequency")) or None,
        date_recorded=recorded,
        raw=dict(row),
    )


def _parse_dose(text: str, source: Source) -> tuple[Decimal | None, Reason | None]:
    if not text:
        if source == "intake":
            return None, unreadable("dose_amount", UNSURE)
        return None, missing("dose_amount", "dose amount")
    try:
        amount = Decimal(text)
        if not amount.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        message = UNSURE if source == "intake" else f"dose {text!r} is not a number"
        return None, unreadable("dose_amount", message)
    if amount <= 0:
        return None, unreadable("dose_amount", f"dose {text!r} must be a positive number")
    return amount, None
