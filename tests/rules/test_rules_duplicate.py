"""DuplicateMedicationRule: positive and negative cases."""

from rules import DuplicateMedicationRule

rule = DuplicateMedicationRule()


def test_brand_and_generic_in_one_source_is_a_duplicate(rec, data):
    """Lipitor and atorvastatin in the pharmacy list are one duplicate finding."""
    findings = rule.evaluate(
        data(
            fhir=[rec("fhir", "atorvastatin", "20")],
            pharmacy=[
                rec("pharmacy", "Lipitor", "20", normalized_name="atorvastatin"),
                rec("pharmacy", "atorvastatin", "20"),
            ],
        )
    )
    assert len(findings) == 1
    (f,) = findings
    assert f.discrepancy_type == "duplicate" and f.medication == "atorvastatin"
    assert f.summary == "Pharmacy has 2 records for atorvastatin."
    assert f.pharmacy_value == "Lipitor 20 mg; atorvastatin 20 mg" and f.fhir_value is None
    assert f.details["source"] == "pharmacy" and f.details["count"] == 2


def test_duplicate_counts_any_dose_and_is_per_source(rec, data):
    """Different doses still count, and each source gets its own finding."""
    findings = rule.evaluate(
        data(
            fhir=[rec("fhir", "metformin", "500"), rec("fhir", "metformin", "1000")],
            pharmacy=[rec("pharmacy", "metformin", "500"), rec("pharmacy", "metformin", "500")],
        )
    )
    assert [f.details["source"] for f in findings] == ["fhir", "pharmacy"]
    assert findings[0].summary == "FHIR has 2 records for metformin."


def test_one_record_per_source_is_not_a_duplicate(rec, data):
    """The same name once in each source is not a duplicate."""
    assert (
        rule.evaluate(
            data(fhir=[rec("fhir", "lisinopril")], pharmacy=[rec("pharmacy", "lisinopril")])
        )
        == []
    )


def test_intake_duplicate_is_reported_per_source(rec, data):
    """Two patient-reported records of one name give a patient-reported duplicate."""
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "ibuprofen", "200")],
            intake=[
                rec("intake", "Advil", "200", normalized_name="ibuprofen"),
                rec("intake", "ibuprofen", "400"),
            ],
        )
    )
    assert f.summary == "Patient-reported has 2 records for ibuprofen."
    assert f.intake_value == "Advil 200 mg; ibuprofen 400 mg"
    assert f.fhir_value is None and f.pharmacy_value is None
    assert f.details["source"] == "intake" and f.details["count"] == 2
