"""Frequency normalizer table and FrequencyMismatchRule."""

import pytest

from rules import FrequencyMismatchRule, run_rules
from rules.frequency import normalize_frequency, plain_text

rule = FrequencyMismatchRule()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        # The ticket's table.
        ("BID", "BID"),
        ("twice daily", "BID"),
        ("2/1d", "BID"),
        ("Q12H", "BID"),
        # Once a day, including time-of-day collapses.
        ("QD", "QD"),
        ("once daily", "QD"),
        ("once a day", "QD"),
        ("Once daily", "QD"),
        ("1/1d", "QD"),
        ("Q24H", "QD"),
        ("QAM", "QD"),
        ("QPM", "QD"),
        ("AM", "QD"),
        ("PM", "QD"),
        ("QHS", "QD"),
        ("BED", "QD"),
        ("at bedtime", "QD"),
        ("every morning", "QD"),
        ("every evening", "QD"),
        ("every night", "QD"),
        ("nightly", "QD"),
        ("daily", "QD"),
        ("every day", "QD"),
        ("every 24 hours", "QD"),
        ("24/1d", "24/D"),
        ("1/24h", "QD"),
        # More often.
        ("twice a day", "BID"),
        ("every 12 hours", "BID"),
        ("TID", "TID"),
        ("three times daily", "TID"),
        ("three times a day", "TID"),
        ("3/1d", "TID"),
        ("Q8H", "TID"),
        ("QID", "QID"),
        ("four times daily", "QID"),
        ("four times a day", "QID"),
        ("4/1d", "QID"),
        ("Q6H", "QID"),
        ("every 6 hours", "QID"),
        # Less often.
        ("QOD", "QOD"),
        ("every other day", "QOD"),
        ("1/2d", "QOD"),
        ("QW", "QW"),
        ("WK", "QW"),
        ("weekly", "QW"),
        ("once a week", "QW"),
        ("once weekly", "QW"),
        ("1/1wk", "QW"),
        ("1/7d", "QW"),
        # Other whole doses a day.
        ("5/1d", "5/D"),
        ("Q4H", "6/D"),
        ("Q2H", "12/D"),
        ("every 1 hour", "24/D"),
        # Spelling and spacing don't matter.
        ("bid", "BID"),
        ("b.i.d.", "BID"),
        ("  Twice   Daily ", "BID"),
        ("1/1.0d", "QD"),
        # As needed.
        ("PRN", "PRN"),
        ("as needed", "PRN"),
        ("Take as needed.", "PRN"),
        ("BID PRN", "PRN"),
        ("1/1d PRN", "PRN"),
    ],
)
def test_normalizer_table(text, code):
    """Known wording maps to its code."""
    assert normalize_frequency(text) == code


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "Every four to six hours (qualifier value)",
        "sometimes",
        "MO",
        "1/1mo",
        "1/3d",
        "0/1d",
        "1/0d",
        "q0h",
        "twice",
        # A dot in a number must not vanish and leave a different number.
        "q1.2h",
        "q2.4h",
        "q0.8h",
        "every 1.2 hours",
        # Only the whole text counts, so extra words stay unknown.
        "q12h and more",
        "take q12h",
        "bidprn",
        "prn pain",
    ],
)
def test_anything_else_is_unknown(text):
    """Nothing is guessed: ranges, monthly codes and unreadable rates aren't comparable."""
    assert normalize_frequency(text) is None


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("QD", "once daily"),
        ("BID", "twice daily"),
        ("TID", "three times daily"),
        ("QID", "four times daily"),
        ("QOD", "every other day"),
        ("QW", "once weekly"),
        ("PRN", "as needed"),
        ("6/D", "6 times daily"),
    ],
)
def test_plain_text(code, text):
    """Each code has wording that doesn't rely on an abbreviation."""
    assert plain_text(code) == text


def _with_frequency(rec, source, name, frequency):
    """A record of name with this stored frequency."""
    return rec(source, name).model_copy(update={"frequency": frequency})


def test_different_schedules_are_a_mismatch(rec, data):
    """Once daily vs twice daily is one finding, in plain language."""
    (f,) = rule.evaluate(
        data(
            fhir=[_with_frequency(rec, "fhir", "sertraline", "QD")],
            pharmacy=[_with_frequency(rec, "pharmacy", "sertraline", "twice daily")],
        )
    )
    assert f.discrepancy_type == "frequency_mismatch" and f.medication == "sertraline"
    assert f.summary == "FHIR frequency once daily; pharmacy frequency twice daily."
    assert (f.fhir_value, f.pharmacy_value, f.intake_value) == (
        "once daily",
        "twice daily",
        None,
    )
    assert f.details == {"fhir_codes": ["QD"], "pharmacy_codes": ["BID"], "not_compared": []}


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("QD", "once daily"),
        ("1/1d", "once a day"),
        ("QHS", "once daily"),
        ("Q12H", "twice daily"),
        ("4/1d", "four times daily"),
    ],
)
def test_same_schedule_in_other_wording_is_not_a_mismatch(rec, data, first, second):
    """Codes are compared, not words."""
    assert (
        rule.evaluate(
            data(
                fhir=[_with_frequency(rec, "fhir", "x", first)],
                pharmacy=[_with_frequency(rec, "pharmacy", "x", second)],
            )
        )
        == []
    )


@pytest.mark.parametrize("other", ["PRN", "as needed", "BID PRN", None, "", "whenever"])
def test_as_needed_or_unknown_is_not_comparable(rec, data, other):
    """A source without a schedule never counts as different."""
    assert (
        rule.evaluate(
            data(
                fhir=[_with_frequency(rec, "fhir", "x", other)],
                pharmacy=[_with_frequency(rec, "pharmacy", "x", "twice daily")],
            )
        )
        == []
    )


def test_three_way_mismatch_names_every_compared_source(rec, data):
    """Two agreeing sources don't outvote a third; all three are stated."""
    (f,) = rule.evaluate(
        data(
            intake=[_with_frequency(rec, "intake", "x", "once a day")],
            fhir=[_with_frequency(rec, "fhir", "x", "QD")],
            pharmacy=[_with_frequency(rec, "pharmacy", "x", "twice daily")],
        )
    )
    assert f.summary == (
        "Patient-reported frequency once daily; FHIR frequency once daily; "
        "pharmacy frequency twice daily."
    )


def test_source_without_a_schedule_is_listed_as_not_compared(rec, data):
    """As-needed intake stays out of the summary and values, but the details record it."""
    (f,) = rule.evaluate(
        data(
            intake=[_with_frequency(rec, "intake", "x", "as needed")],
            fhir=[_with_frequency(rec, "fhir", "x", "QD")],
            pharmacy=[_with_frequency(rec, "pharmacy", "x", "twice daily")],
        )
    )
    assert f.intake_value == "as needed (not compared)"
    assert "Patient-reported" not in f.summary
    assert f.details["not_compared"] == ["intake"]


def test_only_one_scheduled_source_left_gives_no_finding(rec, data):
    """Comparing needs two sources that state a schedule."""
    assert (
        rule.evaluate(
            data(
                intake=[_with_frequency(rec, "intake", "x", "as needed")],
                fhir=[_with_frequency(rec, "fhir", "x", None)],
                pharmacy=[_with_frequency(rec, "pharmacy", "x", "twice daily")],
            )
        )
        == []
    )


def test_frequencies_compare_as_sets(rec, data):
    """Equal wording repeated is one schedule; an extra schedule is a difference."""
    same = data(
        intake=[
            _with_frequency(rec, "intake", "x", "once a day"),
            _with_frequency(rec, "intake", "x", "at bedtime"),
        ],
        fhir=[_with_frequency(rec, "fhir", "x", "QD")],
    )
    assert rule.evaluate(same) == []
    extra = data(
        fhir=[_with_frequency(rec, "fhir", "x", "QD")],
        pharmacy=[
            _with_frequency(rec, "pharmacy", "x", "once daily"),
            _with_frequency(rec, "pharmacy", "x", "twice daily"),
        ],
    )
    (f,) = rule.evaluate(extra)
    assert f.pharmacy_value == "twice daily, once daily"


def test_scheduled_record_still_counts_beside_an_as_needed_one(rec, data):
    """A source's as-needed record doesn't hide its scheduled one."""
    (f,) = rule.evaluate(
        data(
            fhir=[_with_frequency(rec, "fhir", "x", "QD")],
            pharmacy=[
                _with_frequency(rec, "pharmacy", "x", "as needed"),
                _with_frequency(rec, "pharmacy", "x", "twice daily"),
            ],
        )
    )
    assert f.details["pharmacy_codes"] == ["BID"]
    assert f.pharmacy_value == "twice daily, as needed (not compared)"


def test_extra_schedule_in_one_source_is_a_difference(rec, data):
    """Sets differ even when the first code agrees: {BID, QD} isn't {BID}."""
    (f,) = rule.evaluate(
        data(
            fhir=[
                _with_frequency(rec, "fhir", "x", "BID"),
                _with_frequency(rec, "fhir", "x", "QD"),
            ],
            pharmacy=[_with_frequency(rec, "pharmacy", "x", "twice daily")],
        )
    )
    assert f.details["fhir_codes"] == ["BID", "QD"]


@pytest.mark.parametrize(
    ("stored", "value"),
    [
        ("PRN", "as needed (not compared)"),
        ("as needed", "as needed (not compared)"),
        ("Take as needed.", "as needed (not compared)"),
        ("BID PRN", "BID PRN (not compared)"),
        ("whenever", "whenever (not compared)"),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_non_compared_source_shows_what_it_says(rec, data, stored, value):
    """Stated wording stays visible and marked; a source that states nothing shows nothing."""
    (f,) = rule.evaluate(
        data(
            intake=[_with_frequency(rec, "intake", "x", stored)],
            fhir=[_with_frequency(rec, "fhir", "x", "QD")],
            pharmacy=[_with_frequency(rec, "pharmacy", "x", "twice daily")],
        )
    )
    assert f.intake_value == value
    assert f.details["not_compared"] == ["intake"]
    assert f.summary == "FHIR frequency once daily; pharmacy frequency twice daily."


def test_repeated_non_compared_wording_appears_once(rec, data):
    """Two as-needed records are one statement."""
    (f,) = rule.evaluate(
        data(
            intake=[
                _with_frequency(rec, "intake", "x", "as needed"),
                _with_frequency(rec, "intake", "x", "PRN"),
            ],
            fhir=[_with_frequency(rec, "fhir", "x", "QD")],
            pharmacy=[_with_frequency(rec, "pharmacy", "x", "BID")],
        )
    )
    assert f.intake_value == "as needed (not compared)"


def test_name_in_one_source_only_is_not_compared(rec, data):
    """Different drugs are never compared."""
    assert (
        rule.evaluate(
            data(
                fhir=[_with_frequency(rec, "fhir", "a", "QD")],
                pharmacy=[_with_frequency(rec, "pharmacy", "b", "twice daily")],
            )
        )
        == []
    )


def test_intake_none_and_empty_leave_it_out(rec, data):
    """No interview, or a patient reporting nothing, gives no intake schedule to compare."""
    fhir = [_with_frequency(rec, "fhir", "x", "QD")]
    pharmacy = [_with_frequency(rec, "pharmacy", "x", "twice daily")]
    for intake in (None, []):
        (f,) = rule.evaluate(data(fhir=fhir, pharmacy=pharmacy, intake=intake))
        assert f.intake_value is None and f.details["not_compared"] == []


def test_medication_can_also_have_a_dose_finding(rec, data):
    """Frequency is reported beside the other rules, last in the run."""
    findings = run_rules(
        data(
            fhir=[_with_frequency(rec, "fhir", "x", "QD")],
            pharmacy=[
                rec("pharmacy", "x", "20").model_copy(update={"frequency": "twice daily"}),
            ],
        )
    )
    assert [f.discrepancy_type for f in findings] == ["dosage_mismatch", "frequency_mismatch"]


def _product(rec, source, frequency, form=None, salt=None):
    """A metoprolol record with a frequency and, as RxNorm would set, a form or salt."""
    return rec(source, "metoprolol", form=form, salt=salt).model_copy(
        update={"frequency": frequency}
    )


def test_different_salts_are_named_on_the_frequency_finding(rec, data):
    """Tartrate twice daily vs succinate once daily may be right: the row says they differ."""
    (f,) = rule.evaluate(
        data(
            fhir=[_product(rec, "fhir", "BID", salt="metoprolol tartrate")],
            pharmacy=[_product(rec, "pharmacy", "once daily", salt="metoprolol succinate")],
        )
    )
    assert f.summary == (
        "Different salt: FHIR metoprolol tartrate; pharmacy metoprolol succinate. "
        "FHIR frequency twice daily; pharmacy frequency once daily."
    )
    assert f.details["different_salt"]["fhir"] == "metoprolol tartrate"
    assert "different_form" not in f.details


def test_different_forms_are_named_on_the_frequency_finding(rec, data):
    """ER once daily vs IR twice daily: the form difference leads the summary."""
    (f,) = rule.evaluate(
        data(
            fhir=[_product(rec, "fhir", "QD", form="Extended Release Oral Tablet")],
            pharmacy=[_product(rec, "pharmacy", "BID", form="Oral Tablet")],
        )
    )
    assert f.summary == (
        "Different form: FHIR Extended Release Oral Tablet; pharmacy Oral Tablet. "
        "FHIR frequency once daily; pharmacy frequency twice daily."
    )
    assert f.details["different_form"]["pharmacy"] == "Oral Tablet"


def test_same_product_keeps_the_plain_summary(rec, data):
    """No form or salt difference, or none stated, adds nothing."""
    (f,) = rule.evaluate(
        data(
            fhir=[_product(rec, "fhir", "QD", form="Oral Tablet", salt="metoprolol tartrate")],
            pharmacy=[_product(rec, "pharmacy", "BID", salt="metoprolol tartrate")],
        )
    )
    assert f.summary == "FHIR frequency once daily; pharmacy frequency twice daily."
    assert "different_form" not in f.details and "different_salt" not in f.details


def test_product_difference_without_a_schedule_difference_is_not_a_frequency_finding(rec, data):
    """Equal schedules give no finding here; the dosage rule reports the product difference."""
    assert (
        rule.evaluate(
            data(
                fhir=[_product(rec, "fhir", "QD", salt="metoprolol tartrate")],
                pharmacy=[_product(rec, "pharmacy", "once daily", salt="metoprolol succinate")],
            )
        )
        == []
    )
