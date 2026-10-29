from rules import DEFAULT_RULES, run_rules


def test_default_rules_are_the_three_v1_rules():
    assert [r.discrepancy_type for r in DEFAULT_RULES] == [
        "duplicate",
        "missing",
        "dosage_mismatch",
    ]


def test_one_medication_can_yield_two_findings(rec, data):
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
    (f,) = run_rules(
        data(fhir=[rec("fhir", "amlodipine")], rejected=[rejected("pharmacy", "amlodipine")])
    )
    assert f.discrepancy_type == "missing" and "was rejected" in f.summary


def test_custom_rule_list_is_honoured(rec, data):
    assert run_rules(data(fhir=[rec("fhir", "metoprolol")]), rules=[]) == []
