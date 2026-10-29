"""Accepted dose units and base-unit conversion (TECHNICAL_PLAN §4.2)."""

from decimal import Decimal
from typing import Literal

Unit = Literal["mg", "g", "mcg", "mL"]

_SPELLINGS: dict[str, Unit] = {
    "mg": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "mcg": "mcg",
    "ug": "mcg",
    "µg": "mcg",  # micro sign U+00B5
    "μg": "mcg",  # Greek mu U+03BC
    "microgram": "mcg",
    "micrograms": "mcg",
    "ml": "mL",
    "milliliter": "mL",
    "milliliters": "mL",
    "millilitre": "mL",
}

_TO_BASE: dict[str, tuple[Decimal, str]] = {
    "mg": (Decimal(1), "mg"),
    "g": (Decimal(1000), "mg"),
    "mcg": (Decimal("0.001"), "mg"),
    "mL": (Decimal(1), "mL"),
}


def normalize_unit(raw: str | None) -> Unit | None:
    """Map an input spelling (MG, ug, µg, ML, ...) to an accepted unit, or None if not accepted."""
    return _SPELLINGS.get(raw.strip().lower()) if raw else None


def to_base(amount: Decimal, unit: Unit) -> tuple[Decimal, str]:
    """Convert to mg (mass) or mL (volume) so 500 mg == 0.5 g compares equal."""
    factor, base = _TO_BASE[unit]
    return amount * factor, base


def format_dose(amount: Decimal, unit: str) -> str:
    """'500 mg', '0.5 g': no trailing zeros, no exponent."""
    return f"{amount.normalize():f} {unit}"
