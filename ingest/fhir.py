"""Map FHIR R4 Patient and MedicationRequest JSON to the shared contract (§4.1, §4.5).

Synthea sends no unit on doseQuantity, so the strength comes from the RxNorm display
("lisinopril 10 MG Oral Tablet") times the unitless dose count, which defaults to 1 [R01, R03].
Only the first dosageInstruction is read.
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from contract import MedicationRecord, PatientInfo, Reason, Rejection, normalize_unit
from ingest.checks import (
    ACCEPTED_UNITS,
    ANY_UNIT,
    BRACKETED,
    QUANTITY,
    check_datetime,
    clean,
    missing,
    strength_pattern,
    unreadable,
)

RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SYNTHEA_ID_SYSTEM = "https://github.com/synthetichealth/synthea"
CASE_ID_SYSTEM = "urn:medrec:case"

_STRENGTH = strength_pattern(ANY_UNIT)


class PatientMappingError(ValueError):
    """A Patient resource has no id or no stable identifier, so it can't be keyed."""


def map_patient(resource: dict[str, Any]) -> PatientInfo:
    """Snapshot a Patient. The stable key is the Synthea or case identifier, never the HAPI id."""
    fhir_id = clean(resource.get("id"))
    identifier = next(
        (
            clean(i.get("value"))
            for i in resource.get("identifier") or []
            if i.get("system") in (SYNTHEA_ID_SYSTEM, CASE_ID_SYSTEM) and clean(i.get("value"))
        ),
        "",
    )
    if not fhir_id or not identifier:
        raise PatientMappingError(
            f"Patient {fhir_id or '?'} needs an id and a {SYNTHEA_ID_SYSTEM} or "
            f"{CASE_ID_SYSTEM} identifier"
        )
    return PatientInfo(
        identifier=identifier,
        fhir_patient_id=fhir_id,
        name=_patient_name(resource),
        birth_date=_birth_date(clean(resource.get("birthDate"))),
        gender=clean(resource.get("gender")) or None,
    )


def map_medication_requests(
    resources: Iterable[dict[str, Any]], patient_identifier: str
) -> tuple[list[MedicationRecord], list[Rejection]]:
    """Map a patient's MedicationRequests; inactive ones are skipped, invalid ones rejected."""
    records: list[MedicationRecord] = []
    rejections: list[Rejection] = []
    for resource in resources:
        result = map_medication_request(resource, patient_identifier)
        if isinstance(result, MedicationRecord):
            records.append(result)
        elif result is not None:
            rejections.append(result)
    return records, rejections


def map_medication_request(
    resource: dict[str, Any], patient_identifier: str
) -> MedicationRecord | Rejection | None:
    """One MedicationRequest to a record, a rejection, or None when it isn't an active request."""
    if resource.get("resourceType") != "MedicationRequest" or resource.get("status") != "active":
        return None
    record_id = clean(resource.get("id"))
    name = _medication_name(resource)
    reasons: list[Reason] = []

    if not record_id:
        reasons.append(missing("id"))
    if not name:
        reasons.append(missing("medicationCodeableConcept", "medication name"))
    amount, unit = None, None
    if name:
        amount, unit, dose_reason = _dose(name, _dose_quantity(resource))
        if dose_reason:
            reasons.append(dose_reason)
    recorded, date_reason = check_datetime(clean(resource.get("authoredOn")), "authoredOn")
    if date_reason:
        reasons.append(date_reason)

    if reasons:
        return Rejection(
            source="fhir",
            source_record_id=record_id or None,
            name=name or None,
            raw=resource,
            reasons=reasons,
        )
    return MedicationRecord(
        patient_id=patient_identifier,
        source="fhir",
        source_record_id=record_id,
        name=name,
        dose_amount=amount,
        dose_unit=unit,
        frequency=_frequency(resource),
        date_recorded=recorded,
        raw=resource,
    )


def _patient_name(resource: dict[str, Any]) -> str | None:
    names = resource.get("name") or []
    name = next((n for n in names if n.get("use") == "official"), names[0] if names else None)
    if not name:
        return None
    parts = [*(name.get("given") or []), name.get("family")]
    return " ".join(clean(p) for p in parts if clean(p)) or None


def _birth_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _medication_name(resource: dict[str, Any]) -> str:
    """The RxNorm display, else the concept text, else any coding display; verbatim."""
    concept = resource.get("medicationCodeableConcept") or {}
    codings = concept.get("coding") or []
    rxnorm = next(
        (
            clean(c.get("display"))
            for c in codings
            if c.get("system") == RXNORM and c.get("display")
        ),
        "",
    )
    other = next((clean(c.get("display")) for c in codings if clean(c.get("display"))), "")
    return rxnorm or clean(concept.get("text")) or other


def _obj(value: Any) -> dict[str, Any]:
    """A JSON object, or {} for anything else, so one malformed field can't crash a patient."""
    return value if isinstance(value, dict) else {}


def _first(value: Any) -> dict[str, Any]:
    return _obj(value[0]) if isinstance(value, list) and value else {}


def _finite(value: Any) -> Decimal | None:
    """The value as a finite Decimal, or None for text, NaN and Infinity."""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _dosage(resource: dict[str, Any]) -> dict[str, Any]:
    return _first(resource.get("dosageInstruction"))


def _dose_quantity(resource: dict[str, Any]) -> dict[str, Any]:
    return _obj(_first(_dosage(resource).get("doseAndRate")).get("doseQuantity"))


def _dose(
    display: str, quantity: dict[str, Any]
) -> tuple[Decimal | None, str | None, Reason | None]:
    """Per-administration dose: a real mass/volume unit on doseQuantity, else strength x count."""
    count = None
    if quantity.get("value") is not None:
        count = _finite(quantity["value"])
        if count is None:
            return (
                None,
                None,
                unreadable(
                    "doseQuantity", f"dose count {quantity['value']!r} is not a finite number"
                ),
            )
        if count <= 0:
            return None, None, unreadable("doseQuantity", f"dose count {count} must be positive")
    own_unit = normalize_unit(clean(quantity.get("code")) or clean(quantity.get("unit")))
    if count is not None and own_unit:
        return count, own_unit, None

    text = QUANTITY.sub(" ", BRACKETED.sub(" ", display))
    strengths = _STRENGTH.findall(text)
    if not strengths:
        return None, None, unreadable("medicationCodeableConcept", f"no strength in {display!r}")
    if len(strengths) > 1:
        return (
            None,
            None,
            unreadable(
                "medicationCodeableConcept",
                f"combination product (several strengths) in {display!r}",
            ),
        )
    number, unit_text, per = strengths[0]
    if per:
        return (
            None,
            None,
            unreadable(
                "medicationCodeableConcept",
                f"per-{per.lower()} strength {number} {unit_text}/{per}",
            ),
        )
    unit = normalize_unit(unit_text)
    if unit is None:
        return (
            None,
            None,
            unreadable(
                "medicationCodeableConcept", f"unit {unit_text!r} is not one of {ACCEPTED_UNITS}"
            ),
        )
    return Decimal(number) * (count if count is not None else 1), unit, None


def _frequency(resource: dict[str, Any]) -> str | None:
    """The source's frequency as given: timing.code, else n/period, else text; ' PRN' if as needed.

    An as-needed order with no timing is just "PRN"; Synthea's "Take as needed." is noise.
    """
    dosage = _dosage(resource)
    timing = _obj(dosage.get("timing"))
    code = _obj(timing.get("code"))
    codings = code.get("coding") if isinstance(code.get("coding"), list) else []
    coded = next((clean(_obj(c).get("code")) for c in codings if _obj(c).get("code")), "")
    base = coded or clean(code.get("text"))
    repeat = _obj(timing.get("repeat"))
    period = _finite(repeat.get("period"))
    if not base and repeat.get("frequency") and period and period > 0 and repeat.get("periodUnit"):
        base = f"{repeat['frequency']}/{period.normalize():f}{repeat['periodUnit']}"
    as_needed = dosage.get("asNeededBoolean") is True or dosage.get("asNeededCodeableConcept")
    if as_needed:
        return f"{base} PRN" if base else "PRN"
    return base or clean(dosage.get("text")) or None
