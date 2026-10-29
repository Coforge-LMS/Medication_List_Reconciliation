import pytest

from rules import DosageMismatchRule

rule = DosageMismatchRule()


def test_different_strength_is_a_mismatch(rec, data):
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
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "amoxicillin", "250")],
            pharmacy=[rec("pharmacy", "amoxicillin", "5", "mL")],
        )
    )
    assert f.details["different_measure"] is True
    assert "different measure" in f.summary


def test_doses_compare_as_sets(rec, data):
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
    assert (
        rule.evaluate(
            data(
                fhir=[rec("fhir", "lisinopril", "10")],
                pharmacy=[rec("pharmacy", "metoprolol", "20")],
            )
        )
        == []
    )
