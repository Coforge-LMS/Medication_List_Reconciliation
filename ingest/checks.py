"""Field checks shared by the pharmacy/intake validator and the FHIR mapper (§4.5)."""

import re
from datetime import UTC, date, datetime
from typing import Any

from contract import Reason

ACCEPTED_UNITS = "mg, g, mcg, mL"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    """Like check_date, but also accepts a full ISO date-time (UTC date taken), e.g. authoredOn."""
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
    parsed = (moment.astimezone(UTC) if moment.tzinfo else moment).date()
    return _not_future(parsed, text, field)


def _not_future(parsed: date, text: str, field: str) -> tuple[date | None, Reason | None]:
    if parsed > date.today():
        return None, Reason(field=field, code="future_date", message=f"{text!r} is in the future")
    return parsed, None
