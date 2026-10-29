import pytest

from rules import MissingMedicationRule

rule = MissingMedicationRule()


def test_fhir_only_medication_is_missing_from_pharmacy(rec, data):
    (f,) = rule.evaluate(data(fhir=[rec("fhir", "metoprolol", "25")]))
    assert f.discrepancy_type == "missing" and f.medication == "metoprolol"
    assert f.details["missing_from"] == "pharmacy" and f.details["rejected_count"] == 0
    assert f.summary == "Listed in FHIR; no pharmacy record."
    assert f.fhir_value == "25 mg" and f.pharmacy_value is None


def test_pharmacy_only_medication_is_missing_from_fhir(rec, data):
    (f,) = rule.evaluate(data(pharmacy=[rec("pharmacy", "amlodipine", "5")]))
    assert f.details["missing_from"] == "fhir"
    assert f.summary == "Listed in pharmacy; no FHIR record."


def test_medication_in_both_sources_is_not_missing(rec, data):
    assert (
        rule.evaluate(
            data(fhir=[rec("fhir", "lisinopril")], pharmacy=[rec("pharmacy", "lisinopril", "20")])
        )
        == []
    )


def test_one_finding_per_name_even_with_several_records(rec, data):
    assert (
        len(rule.evaluate(data(fhir=[rec("fhir", "metoprolol"), rec("fhir", "metoprolol")]))) == 1
    )


@pytest.mark.parametrize(
    ("n", "wording"),
    [
        (1, "1 pharmacy record with this name was rejected"),
        (2, "2 pharmacy records with this name were rejected"),
    ],
)
def test_rejected_counterpart_is_named_in_summary(rec, rejected, data, n, wording):
    rejections = [rejected("pharmacy", "Amlodipine", normalized_name="amlodipine")] + [
        rejected("pharmacy", "amlodipine")
        for _ in range(n - 1)  # name-only fallback
    ]
    (f,) = rule.evaluate(data(fhir=[rec("fhir", "amlodipine", "5")], rejected=rejections))
    assert f.discrepancy_type == "missing"
    assert (
        f.summary == f"Listed in FHIR. No valid pharmacy record; {wording} (see Rejected records)."
    )
    assert f.details["rejected_count"] == n
    assert f.details["rejected_record_ids"] == [r.source_record_id for r in rejections]


def test_rejection_in_the_same_source_or_other_name_is_not_a_counterpart(rec, rejected, data):
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "amlodipine")],
            rejected=[rejected("fhir", "amlodipine"), rejected("pharmacy", "lisinopril")],
        )
    )
    assert f.summary == "Listed in FHIR; no pharmacy record."
