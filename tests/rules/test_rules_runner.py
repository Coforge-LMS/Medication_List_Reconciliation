"""run_rules and DEFAULT_RULES: multi-finding, clean patient and rejected counterpart."""

from rules import DEFAULT_RULES, run_rules


def test_default_rules_are_the_three_v1_rules():
    """DEFAULT_RULES holds the three V1 rules in order."""
    assert [r.discrepancy_type for r in DEFAULT_RULES] == [
        "duplicate",
        "missing",
        "dosage_mismatch",
    ]


def test_one_medication_can_yield_two_findings(rec, data):
    """A pharmacy duplicate plus a dose difference gives two findings for one medication."""
    findings = run_rules(
        data(
            fhir=[rec("fhir", "atorvastatin", "40")],
            pharmacy=[
                rec("pharmacy", "Lipitor", "20", normalized_name="atorvastatin"),
                rec("pharmacy", "atorvastatin", "20"),
            ],
        )
    )
    assert [(f.discrepancy_type, f.medication) for f in findings] == [
        ("duplicate", "atorvastatin"),
        ("dosage_mismatch", "atorvastatin"),
    ]


def test_no_discrepancy_patient_yields_no_findings(rec, data):
    """Matching names and equivalent doses give no findings."""
    clean = data(
        fhir=[
            rec("fhir", "lisinopril 10 MG Oral Tablet", "10", normalized_name="lisinopril"),
            rec("fhir", "metformin", "500"),
        ],
        pharmacy=[
            rec("pharmacy", "Zestril", "10", normalized_name="lisinopril"),
            rec("pharmacy", "metformin", "0.5", "g"),
        ],
    )
    assert run_rules(clean) == []


def test_rejected_counterpart_stays_missing_not_omitted(rec, rejected, data):
    """A rejected counterpart is reported as missing with the rejection wording."""
    (f,) = run_rules(
        data(fhir=[rec("fhir", "amlodipine")], rejected=[rejected("pharmacy", "amlodipine")])
    )
    assert f.discrepancy_type == "missing" and "was rejected" in f.summary


def test_custom_rule_list_is_honoured(rec, data):
    """An explicit rule list replaces DEFAULT_RULES."""
    assert run_rules(data(fhir=[rec("fhir", "metoprolol")]), rules=[]) == []


def test_intake_none_and_empty_intake_differ(rec, data):
    """None (no interview) gives the two-source result; [] reports every drug as unreported."""
    fhir = [rec("fhir", "lisinopril", "10"), rec("fhir", "metoprolol", "25")]
    pharmacy = [rec("pharmacy", "lisinopril", "10")]
    no_interview = run_rules(data(fhir=fhir, pharmacy=pharmacy))
    reports_none = run_rules(data(fhir=fhir, pharmacy=pharmacy, intake=[]))

    assert [(f.medication, f.details["missing_from"]) for f in no_interview] == [
        ("metoprolol", "pharmacy")
    ]
    assert no_interview[0].summary == "Listed in FHIR; no pharmacy record."

    assert [(f.medication, f.details["missing_from"]) for f in reports_none] == [
        ("lisinopril", ["intake"]),
        ("metoprolol", ["intake", "pharmacy"]),
    ]
    assert all("(patient reports no medications)" in f.summary for f in reports_none)
    assert all(f.intake_value is None for f in reports_none)
