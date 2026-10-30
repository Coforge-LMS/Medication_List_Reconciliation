"""Field checks shared by the pharmacy/intake validator and the FHIR mapper (§4.5)."""

import re
from datetime import date, datetime
from typing import Any

from contract import Reason

ACCEPTED_UNITS = "mg, g, mcg, mL"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Medication-name patterns shared by the FHIR mapper and the normalizer, so they can't drift.
BRACKETED = re.compile(r"\[[^\]]*\]")
_NUMBER = r"\d+(?:\.\d+)?"
ANY_UNIT = r"[^\W\d_]+"  # the mapper must see unknown units to reject them
KNOWN_UNITS = "mg|mcg|ug|µg|μg|g|ml|unt|iu|meq|hr|actuat"  # free text: only words that are units
# a package quantity ("24 HR", "120 ACTUAT", "1 ML"), not a strength; "5 MG/ML" is left alone
QUANTITY = re.compile(rf"(?<!/)\b{_NUMBER}\s*(?:hr|actuat|ml)\b(?!\s*/)", re.IGNORECASE)


def strength_pattern(unit: str, flags: int = 0) -> re.Pattern[str]:
    """Number, unit and an optional attached denominator: "10 MG", "5 MG/ML", "250 MG/5ML".

    Groups: number, unit, denominator unit (empty when absent). A spaced slash, as in
    "25 MG / losartan 100 MG", is not a denominator.
    """
    return re.compile(rf"\b({_NUMBER})\s*({unit})(?:/(?:{_NUMBER})?({unit}))?\b", flags)


def clean(value: Any) -> str:
    """Trimmed text of a raw field; None becomes an empty string."""
    return "" if value is None else str(value).strip()


def missing(field: str, label: str | None = None) -> Reason:
    return Reason(
        field=field, code="missing_field", message=f"{label or field} is missing or blank"
    )


def unreadable(field: str, message: str) -> Reason:
    return Reason(field=field, code="unreadable_dosage", message=message)


def check_date(text: str, field: str) -> tuple[date | None, Reason | None]:
    """Parse an ISO date (YYYY-MM-DD). Blank, malformed or future dates return a reason."""
    if not text:
        return None, missing(field)
    try:
        if not _ISO_DATE.fullmatch(text):
            raise ValueError
        parsed = date.fromisoformat(text)
    except ValueError:
        return None, Reason(
            field=field, code="invalid_date", message=f"{text!r} is not an ISO date"
        )
    return _not_future(parsed, text, field)


def check_datetime(text: str, field: str) -> tuple[date | None, Reason | None]:
    """Like check_date, but also accepts a full ISO date-time, e.g. authoredOn.

    A date-time becomes the date on the local clock, the one date.today() and the contract's
    future-date check use, so an evening timestamp isn't "tomorrow" in UTC.
    """
    if not text:
        return None, missing(field)
    if _ISO_DATE.fullmatch(text):
        return check_date(text, field)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None, Reason(
            field=field, code="invalid_date", message=f"{text!r} is not an ISO date"
        )
    parsed = (moment.astimezone() if moment.tzinfo else moment).date()
    return _not_future(parsed, text, field)


def _not_future(parsed: date, text: str, field: str) -> tuple[date | None, Reason | None]:
    if parsed > date.today():
        return None, Reason(field=field, code="future_date", message=f"{text!r} is in the future")
    return parsed, None
