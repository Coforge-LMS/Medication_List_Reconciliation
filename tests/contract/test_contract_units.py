from decimal import Decimal

import pytest

from contract import format_dose, normalize_unit, to_base


@pytest.mark.parametrize(
    ("raw", "unit"),
    [
        ("mg", "mg"),
        ("MG", "mg"),
        (" g ", "g"),
        ("mcg", "mcg"),
        ("ug", "mcg"),
        ("µg", "mcg"),
        ("μg", "mcg"),
        ("ML", "mL"),
        ("ml", "mL"),
        ("tab", None),
        ("units", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_unit(raw, unit):
    assert normalize_unit(raw) == unit


def test_500_mg_equals_half_gram():
    assert to_base(Decimal("500"), "mg") == to_base(Decimal("0.5"), "g")


def test_mcg_converts_to_mg():
    assert to_base(Decimal("1000"), "mcg") == (Decimal("1"), "mg")


def test_mass_never_equals_volume():
    assert to_base(Decimal("5"), "mg") != to_base(Decimal("5"), "mL")


def test_base_doses_compare_as_sets():
    # Rules compare sets of base doses; equal Decimals must hash equal.
    assert {to_base(Decimal("500"), "mg")} == {to_base(Decimal("0.500"), "g")}


@pytest.mark.parametrize(
    ("amount", "unit", "text"),
    [
        (Decimal("500"), "mg", "500 mg"),
        (Decimal("0.50"), "g", "0.5 g"),
        (Decimal("10.0"), "mg", "10 mg"),
    ],
)
def test_format_dose(amount, unit, text):
    assert format_dose(amount, unit) == text
