"""DosageMismatchRule: strength, unit equivalence, measure and set semantics."""

import pytest

from rules import DosageMismatchRule, run_rules

rule = DosageMismatchRule()


def test_different_strength_is_a_mismatch(rec, data):
    """10 mg vs 20 mg is a dosage mismatch."""
    (f,) = rule.evaluate(
        data(fhir=[rec("fhir", "lisinopril", "10")], pharmacy=[rec("pharmacy", "lisinopril", "20")])
    )
    assert f.discrepancy_type == "dosage_mismatch" and f.medication == "lisinopril"
    assert f.summary == "FHIR dose 10 mg; pharmacy dose 20 mg."
    assert (f.fhir_value, f.pharmacy_value) == ("10 mg", "20 mg")
    assert f.details["different_measure"] is False


@pytest.mark.parametrize(
    ("fhir", "pharmacy"),
    [(("500", "mg"), ("0.5", "g")), (("1", "mg"), ("1000", "mcg")), (("5", "mL"), ("5.0", "mL"))],
)
def test_equivalent_doses_in_other_units_are_not_a_mismatch(rec, data, fhir, pharmacy):
    """500 mg vs 0.5 g (and similar) give no finding."""
    assert (
        rule.evaluate(
            data(
                fhir=[rec("fhir", "metformin", *fhir)],
                pharmacy=[rec("pharmacy", "metformin", *pharmacy)],
            )
        )
        == []
    )


def test_mass_vs_volume_is_a_different_measure(rec, data):
    """mg vs mL is a mismatch whose summary says different measure."""
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "amoxicillin", "250")],
            pharmacy=[rec("pharmacy", "amoxicillin", "5", "mL")],
        )
    )
    assert f.details["different_measure"] is True
    assert "different measure" in f.summary


def test_doses_compare_as_sets(rec, data):
    """Repeated equivalent doses match; an extra distinct dose is a mismatch."""
    same = data(
        fhir=[rec("fhir", "metformin", "500")],
        pharmacy=[rec("pharmacy", "metformin", "500"), rec("pharmacy", "metformin", "0.5", "g")],
    )
    assert rule.evaluate(same) == []
    extra = data(
        fhir=[rec("fhir", "metformin", "500")],
        pharmacy=[rec("pharmacy", "metformin", "500"), rec("pharmacy", "metformin", "1000")],
    )
    (f,) = rule.evaluate(extra)
    assert f.pharmacy_value == "500 mg, 1000 mg"


def test_name_in_one_source_only_is_not_a_dosage_mismatch(rec, data):
    """Different names are never compared for dose."""
    assert (
        rule.evaluate(
            data(
                fhir=[rec("fhir", "lisinopril", "10")],
                pharmacy=[rec("pharmacy", "metoprolol", "20")],
            )
        )
        == []
    )


def test_three_way_mismatch_names_every_source(rec, data):
    """Intake, FHIR and pharmacy doses that differ give one finding naming all three."""
    (f,) = rule.evaluate(
        data(
            intake=[rec("intake", "lisinopril", "5")],
            fhir=[rec("fhir", "lisinopril", "10")],
            pharmacy=[rec("pharmacy", "lisinopril", "20")],
        )
    )
    assert f.summary == "Patient-reported dose 5 mg; FHIR dose 10 mg; pharmacy dose 20 mg."
    assert (f.intake_value, f.fhir_value, f.pharmacy_value) == ("5 mg", "10 mg", "20 mg")
    assert f.details["intake_doses_base"] == ["5 mg"]
    assert f.details["different_measure"] is False


def test_intake_differing_from_two_agreeing_sources_is_a_mismatch(rec, data):
    """Two agreeing sources do not outvote intake; any difference is reported."""
    (f,) = rule.evaluate(
        data(
            intake=[rec("intake", "metformin", "1", "g")],
            fhir=[rec("fhir", "metformin", "500")],
            pharmacy=[rec("pharmacy", "metformin", "0.5", "g")],
        )
    )
    assert f.summary == "Patient-reported dose 1 g; FHIR dose 500 mg; pharmacy dose 0.5 g."


def test_intake_and_one_source_are_compared(rec, data):
    """A name in intake and pharmacy only (2 sources) is still compared; FHIR stays empty."""
    (f,) = rule.evaluate(
        data(
            intake=[rec("intake", "ibuprofen", "400")],
            pharmacy=[rec("pharmacy", "ibuprofen", "200")],
        )
    )
    assert f.summary == "Patient-reported dose 400 mg; pharmacy dose 200 mg."
    assert f.fhir_value is None and "fhir_doses_base" not in f.details


def test_equivalent_doses_in_all_three_sources_are_not_a_mismatch(rec, data):
    """500 mg, 0.5 g and 500 mg across the three sources give no finding."""
    assert (
        rule.evaluate(
            data(
                intake=[rec("intake", "metformin", "500")],
                fhir=[rec("fhir", "metformin", "0.5", "g")],
                pharmacy=[rec("pharmacy", "metformin", "500")],
            )
        )
        == []
    )


def test_intake_in_a_different_measure_is_flagged(rec, data):
    """Patient-reported mL against FHIR mg is a different measure."""
    (f,) = rule.evaluate(
        data(intake=[rec("intake", "amoxicillin", "5", "mL")], fhir=[rec("fhir", "amoxicillin")])
    )
    assert f.details["different_measure"] is True
    assert f.summary.startswith("Doses are recorded in a different measure: Patient-reported")


ER = "Extended Release Oral Tablet"
IR = "Oral Tablet"


def test_strength_difference_with_the_same_form_is_still_a_mismatch(rec, data):
    """10 mg vs 20 mg of one tablet form: a plain dose mismatch, with nothing about form."""
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "lisinopril", "10", form=IR)],
            pharmacy=[rec("pharmacy", "lisinopril", "20", form=IR)],
        )
    )
    assert f.summary == "FHIR dose 10 mg; pharmacy dose 20 mg."
    assert "different_form" not in f.details


def test_er_vs_ir_with_equal_doses_is_reported_not_merged(rec, data):
    """Same ingredient and dose but a different release form is one finding, naming both forms."""
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "metformin", "500", form=ER)],
            pharmacy=[rec("pharmacy", "metformin", "500", form=IR)],
        )
    )
    assert f.discrepancy_type == "dosage_mismatch" and f.medication == "metformin"
    assert f.summary == (
        f"Different form: FHIR {ER}; pharmacy {IR}. FHIR dose 500 mg; pharmacy dose 500 mg."
    )
    assert f.details["different_form"] == {"fhir": ER, "pharmacy": IR}


def test_form_and_strength_can_differ_together(rec, data):
    """Both differences are stated in one finding."""
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "metoprolol", "50", form=ER)],
            pharmacy=[rec("pharmacy", "metoprolol", "25", form=IR)],
        )
    )
    assert f.summary == (
        f"Different form: FHIR {ER}; pharmacy {IR}. FHIR dose 50 mg; pharmacy dose 25 mg."
    )


def test_three_sources_compare_only_those_stating_a_form(rec, data):
    """A bare name says nothing about form, so only the two that state one are listed."""
    (f,) = rule.evaluate(
        data(
            intake=[rec("intake", "metformin", "500")],
            fhir=[rec("fhir", "metformin", "500", form=ER)],
            pharmacy=[rec("pharmacy", "metformin", "500", form=IR)],
        )
    )
    assert f.details["different_form"] == {"fhir": ER, "pharmacy": IR}
    assert "Patient-reported" not in f.summary.split(". ")[0]


def test_unknown_form_is_neither_equal_nor_different(rec, data):
    """A coded record against a bare name, same dose: nothing to report."""
    assert (
        rule.evaluate(
            data(
                fhir=[rec("fhir", "metformin", "500", form=ER)],
                pharmacy=[rec("pharmacy", "metformin", "500")],
            )
        )
        == []
    )


def test_different_salt_is_reported_even_with_equal_doses(rec, data):
    """Metoprolol tartrate and succinate share an ingredient but aren't the same product."""
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "metoprolol", "25", form=IR, salt="metoprolol tartrate")],
            pharmacy=[rec("pharmacy", "metoprolol", "25", salt="metoprolol succinate")],
        )
    )
    assert f.summary == (
        "Different salt: FHIR metoprolol tartrate; pharmacy metoprolol succinate. "
        "FHIR dose 25 mg; pharmacy dose 25 mg."
    )
    assert f.details["different_salt"]["pharmacy"] == "metoprolol succinate"
    assert "different_form" not in f.details


def test_unstated_salt_on_one_side_is_not_a_difference(rec, data):
    """A code whose basis is just the ingredient states no salt, so a named salt can't conflict."""
    assert (
        rule.evaluate(
            data(
                fhir=[rec("fhir", "rosuvastatin", "20", form=IR)],
                pharmacy=[rec("pharmacy", "rosuvastatin", "20", salt="rosuvastatin calcium")],
            )
        )
        == []
    )


def test_form_difference_never_becomes_two_missing_findings(rec, data):
    """Across all rules, ER vs IR of one ingredient gives only the dosage mismatch."""
    findings = run_rules(
        data(
            fhir=[rec("fhir", "metformin", "500", form=ER)],
            pharmacy=[rec("pharmacy", "metformin", "500", form=IR)],
        )
    )
    assert [f.discrepancy_type for f in findings] == ["dosage_mismatch"]
