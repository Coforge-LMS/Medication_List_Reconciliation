"""The three case patients through the real ingest and rules: what data/README.md promises."""

import pytest

from data.generators.common import load_config


def summary(findings):
    """Comparable view: type, medication, and for missing the three-way pattern."""
    result = []
    for f in findings:
        if f.discrepancy_type == "missing":
            result.append(
                (
                    f.discrepancy_type,
                    f.medication,
                    tuple(f.details["present_in"]),
                    tuple(f.details["missing_from"]),
                    f.details["rejected_count"],
                )
            )
        else:
            result.append((f.discrepancy_type, f.medication))
    return sorted(result)


def test_case_clean_has_no_findings(reconcile):
    data, findings = reconcile("CASE-CLEAN")
    assert findings == []
    assert data.rejected == []
    assert (len(data.fhir), len(data.pharmacy), len(data.intake)) == (3, 3, 3)


def test_case_mixed_three_way_findings(reconcile):
    data, findings = reconcile("CASE-MIXED")
    assert summary(findings) == sorted(
        [
            ("duplicate", "acetaminophen"),  # pharmacy lists 500 mg and 1000 mg
            ("duplicate", "sertraline"),  # intake lists it twice
            ("dosage_mismatch", "acetaminophen"),  # 500 / 500+1000 / 1000
            ("frequency_mismatch", "sertraline"),  # FHIR, intake QD; pharmacy Zoloft twice daily
            ("missing", "ibuprofen", ("intake",), ("fhir", "pharmacy"), 0),
            ("missing", "metoprolol", ("fhir",), ("intake", "pharmacy"), 0),
            ("missing", "omeprazole", ("pharmacy",), ("intake", "fhir"), 0),
            # warfarin: the pharmacy row and the intake entry were both rejected
            ("missing", "warfarin", ("fhir",), ("intake", "pharmacy"), 2),
        ]
    )
    assert len(data.rejected) == 6  # five invalid pharmacy rows + the "not sure" warfarin dose


def test_case_mixed_metformin_is_equal_across_sources(reconcile):
    _, findings = reconcile("CASE-MIXED")
    assert not [f for f in findings if f.medication == "metformin"]  # 500 mg == 0.5 g


def test_case_mixed_without_an_interview_is_the_two_source_result(reconcile):
    _, findings = reconcile("CASE-MIXED", with_intake=False)
    assert {f.discrepancy_type for f in findings} == {
        "duplicate",
        "missing",
        "dosage_mismatch",
        "frequency_mismatch",
    }
    assert all("intake_value" not in f.model_fields_set for f in findings)
    missing = {
        f.medication: f.details["missing_from"] for f in findings if f.discrepancy_type == "missing"
    }
    assert missing == {"metoprolol": "pharmacy", "omeprazole": "fhir", "warfarin": "pharmacy"}


def test_case_brand_matches_through_rxnorm(reconcile):
    """FHIR's rosuvastatin calcium and everyone else's Crestor are one ingredient: no findings."""
    data, findings = reconcile("CASE-BRAND")
    assert findings == []
    assert {r.normalized_name for r in [*data.fhir, *data.pharmacy, *data.intake]} == {
        "rosuvastatin"
    }


def test_case_mixed_pharmacy_zoloft_matches_sertraline_only_through_rxnorm(reconcile, config):
    """The brand isn't an alias, so the frequency finding depends on RxNorm matching it."""
    assert "zoloft" not in config.aliases
    data, findings = reconcile("CASE-MIXED")
    (zoloft,) = [r for r in data.pharmacy if r.name == "Zoloft"]
    assert zoloft.normalized_name == "sertraline" and zoloft.rxcui
    (frequency,) = [f for f in findings if f.discrepancy_type == "frequency_mismatch"]
    assert frequency.medication == "sertraline" and frequency.pharmacy_value == "twice daily"


def test_case_brand_crestor_is_deliberately_not_in_the_alias_list():
    assert "crestor" not in load_config().aliases


@pytest.mark.parametrize("patient", ["CASE-CLEAN", "CASE-MIXED", "CASE-BRAND"])
def test_every_case_patient_has_an_interview(reconcile, patient):
    data, _ = reconcile(patient)
    assert data.intake is not None
