"""Finding summaries state facts only, never treatment advice (TECHNICAL_PLAN §4.6)."""

import re

from rules import run_rules

BANNED = re.compile(r"\b(increase|decrease|stop|start|discontinue|should|recommend)", re.IGNORECASE)


def test_no_summary_recommends_treatment(rec, rejected, data):
    """No summary from any rule contains a banned word."""
    findings = run_rules(
        data(
            fhir=[
                rec("fhir", "lisinopril", "10"),
                rec("fhir", "metoprolol", "25"),
                rec("fhir", "amlodipine", "5"),
                rec("fhir", "amoxicillin", "250"),
                rec("fhir", "metformin", "500"),
                rec("fhir", "metformin", "1000"),
            ],
            pharmacy=[
                rec("pharmacy", "lisinopril", "20"),
                rec("pharmacy", "atorvastatin", "20"),
                rec("pharmacy", "Lipitor", "20", normalized_name="atorvastatin"),
                rec("pharmacy", "amoxicillin", "5", "mL"),
                rec("pharmacy", "metformin", "500"),
            ],
            rejected=[rejected("pharmacy", "amlodipine"), rejected("pharmacy", "amlodipine")],
        )
    )
    assert {f.discrepancy_type for f in findings} == {"duplicate", "missing", "dosage_mismatch"}
    assert len(findings) >= 6
    for f in findings:
        assert not BANNED.search(f.summary), f.summary


def test_no_three_way_summary_recommends_treatment(rec, rejected, data):
    """Three-way summaries (intake patterns, rejections, dose lists) contain no banned word."""
    findings = run_rules(
        data(
            intake=[
                rec("intake", "ibuprofen", "200"),
                rec("intake", "Advil", "400", normalized_name="ibuprofen"),
                rec("intake", "lisinopril", "5"),
                rec("intake", "amlodipine", "5"),
                rec("intake", "amoxicillin", "5", "mL"),
            ],
            fhir=[
                rec("fhir", "lisinopril", "10"),
                rec("fhir", "metoprolol", "25"),
                rec("fhir", "amoxicillin", "250"),
            ],
            pharmacy=[
                rec("pharmacy", "lisinopril", "20"),
                rec("pharmacy", "amlodipine", "5"),
                rec("pharmacy", "metoprolol", "25"),
            ],
            rejected=[rejected("intake", "metoprolol"), rejected("fhir", "ibuprofen")],
        )
    )
    findings += run_rules(data(intake=[], fhir=[rec("fhir", "metformin")]))
    assert {f.discrepancy_type for f in findings} == {"duplicate", "missing", "dosage_mismatch"}
    summaries = " ".join(f.summary for f in findings)
    for pattern in ("Patient-reported", "not reported by the patient", "patient reports no"):
        assert pattern in summaries
    for f in findings:
        assert not BANNED.search(f.summary), f.summary
