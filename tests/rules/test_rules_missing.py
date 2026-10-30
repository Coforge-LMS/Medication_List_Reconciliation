"""MissingMedicationRule: both directions, negatives and rejected-counterpart wording."""

import pytest

from rules import MissingMedicationRule

rule = MissingMedicationRule()


def test_fhir_only_medication_is_missing_from_pharmacy(rec, data):
    """A FHIR-only name is missing from pharmacy."""
    (f,) = rule.evaluate(data(fhir=[rec("fhir", "metoprolol", "25")]))
    assert f.discrepancy_type == "missing" and f.medication == "metoprolol"
    assert f.details["missing_from"] == "pharmacy" and f.details["rejected_count"] == 0
    assert f.summary == "Listed in FHIR; no pharmacy record."
    assert f.fhir_value == "25 mg" and f.pharmacy_value is None


def test_pharmacy_only_medication_is_missing_from_fhir(rec, data):
    """A pharmacy-only name is missing from FHIR."""
    (f,) = rule.evaluate(data(pharmacy=[rec("pharmacy", "amlodipine", "5")]))
    assert f.details["missing_from"] == "fhir"
    assert f.summary == "Listed in pharmacy; no FHIR record."


def test_medication_in_both_sources_is_not_missing(rec, data):
    """A name in both sources is never missing, whatever the dose."""
    assert (
        rule.evaluate(
            data(fhir=[rec("fhir", "lisinopril")], pharmacy=[rec("pharmacy", "lisinopril", "20")])
        )
        == []
    )


def test_one_finding_per_name_even_with_several_records(rec, data):
    """Two records of the absent name still give one missing finding."""
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
    """A rejected record in the other source is named in the summary, singular or plural."""
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
    """Rejections in the same source or under another name keep the plain wording."""
    (f,) = rule.evaluate(
        data(
            fhir=[rec("fhir", "amlodipine")],
            rejected=[rejected("fhir", "amlodipine"), rejected("pharmacy", "lisinopril")],
        )
    )
    assert f.summary == "Listed in FHIR; no pharmacy record."


def test_intake_only_drug_is_missing_from_fhir_and_pharmacy(rec, data):
    """A drug only the patient reports is missing from both other sources."""
    (f,) = rule.evaluate(data(intake=[rec("intake", "ibuprofen", "200")]))
    assert f.medication == "ibuprofen"
    assert f.details["present_in"] == ["intake"]
    assert f.details["missing_from"] == ["fhir", "pharmacy"]
    assert f.summary == "Reported by the patient; not on the FHIR list and not in pharmacy records."
    assert f.intake_value == "200 mg" and f.fhir_value is None and f.pharmacy_value is None


def test_drug_not_reported_by_the_patient(rec, data):
    """A drug on the FHIR list and in pharmacy records but not reported by the patient."""
    findings = rule.evaluate(
        data(
            intake=[rec("intake", "ibuprofen")],
            fhir=[rec("fhir", "metoprolol", "25")],
            pharmacy=[rec("pharmacy", "metoprolol", "25")],
        )
    )
    assert [f.medication for f in findings] == ["ibuprofen", "metoprolol"]
    f = findings[1]
    assert f.details["present_in"] == ["fhir", "pharmacy"]
    assert f.details["missing_from"] == ["intake"]
    assert f.summary == "On the FHIR list and in pharmacy records; not reported by the patient."
    assert (f.fhir_value, f.pharmacy_value, f.intake_value) == ("25 mg", "25 mg", None)


def test_fhir_only_drug_with_intake_names_both_absent_sources(rec, data):
    """The ticket's example: on the FHIR list only, with an interview recorded."""
    (f,) = rule.evaluate(data(intake=[], fhir=[rec("fhir", "metoprolol")]))
    assert f.summary == (
        "On the FHIR list; not reported by the patient (patient reports no medications) "
        "and not in pharmacy records."
    )


def test_intake_and_pharmacy_present_but_missing_from_fhir(rec, data):
    """Reported by the patient and in pharmacy records, but not on the FHIR list."""
    (f,) = rule.evaluate(
        data(
            intake=[rec("intake", "amlodipine", "5")], pharmacy=[rec("pharmacy", "amlodipine", "5")]
        )
    )
    assert f.details["present_in"] == ["intake", "pharmacy"]
    assert f.details["missing_from"] == ["fhir"]
    assert f.summary == "Reported by the patient and in pharmacy records; not on the FHIR list."
    assert (f.intake_value, f.pharmacy_value, f.fhir_value) == ("5 mg", "5 mg", None)


def test_drug_in_all_three_sources_is_not_missing(rec, data):
    """A name every participating source has is never missing, whatever the dose."""
    assert (
        rule.evaluate(
            data(
                intake=[rec("intake", "lisinopril", "5")],
                fhir=[rec("fhir", "lisinopril")],
                pharmacy=[rec("pharmacy", "lisinopril", "20")],
            )
        )
        == []
    )


def test_rejected_intake_counterpart_is_named(rec, rejected, data):
    """A rejected patient-reported record ("not sure" dose) is named, not shown as an omission."""
    rejection = rejected("intake", "Metoprolol", normalized_name="metoprolol")
    (f,) = rule.evaluate(
        data(
            intake=[],
            fhir=[rec("fhir", "metoprolol", "25")],
            pharmacy=[rec("pharmacy", "metoprolol", "25")],
            rejected=[rejection],
        )
    )
    assert f.summary == (
        "On the FHIR list and in pharmacy records; not reported by the patient. "
        "1 patient-reported record with this name was rejected (see Rejected records)."
    )
    assert f.details["rejected_count"] == 1
    assert f.details["rejected_record_ids"] == [rejection.source_record_id]


def test_rejected_intake_entry_drops_reports_no_medications_note(rec, rejected, data):
    """An empty intake with a rejected intake entry (another drug) omits the reports-none note."""
    (f,) = rule.evaluate(
        data(
            intake=[],
            fhir=[rec("fhir", "ibuprofen")],
            pharmacy=[rec("pharmacy", "ibuprofen")],
            rejected=[rejected("intake", "aspirin")],
        )
    )
    assert f.summary == "On the FHIR list and in pharmacy records; not reported by the patient."


def test_rejections_in_several_absent_sources_are_each_named(rec, rejected, data):
    """Rejections in two absent sources are both counted, each with its own label."""
    (f,) = rule.evaluate(
        data(
            intake=[rec("intake", "ibuprofen")],
            rejected=[
                rejected("fhir", "ibuprofen"),
                rejected("pharmacy", "ibuprofen"),
                rejected("pharmacy", "ibuprofen"),
            ],
        )
    )
    assert f.summary == (
        "Reported by the patient; not on the FHIR list and not in pharmacy records. "
        "1 FHIR record with this name was rejected (see Rejected records); "
        "2 pharmacy records with this name were rejected (see Rejected records)."
    )
    assert f.details["rejected_count"] == 3


def test_intake_rejection_is_ignored_without_an_interview(rec, rejected, data):
    """With intake=None, intake rejections are not counterparts and wording is two-source."""
    (f,) = rule.evaluate(
        data(fhir=[rec("fhir", "metoprolol")], rejected=[rejected("intake", "metoprolol")])
    )
    assert f.summary == "Listed in FHIR; no pharmacy record."
    assert f.details == {"missing_from": "pharmacy", "rejected_count": 0, "rejected_record_ids": []}
