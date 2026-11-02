"""service.build_input / collect / reconcile over the committed data and recorded HAPI fixtures.

The DB calls (latest_intake_for, save_run) are replaced; everything else is the real pipeline.
"""

from pathlib import Path

import pytest

from app import service
from app.version import __version__
from db import repo
from ingest.aliases import load_aliases
from ingest.fhir import RXNORM
from rules import run_rules
from tests.app.conftest import BASE, INTERVIEW, case_intake

ALIASES = load_aliases(Path(__file__).resolve().parents[2] / "data" / "aliases.json")
CASE_IDS = {"CASE-CLEAN": "2174", "CASE-MIXED": "2178", "CASE-BRAND": "2184"}


@pytest.fixture
def intake(monkeypatch):
    """Control what latest_intake_for returns: 'case' (committed CSVs), None, or a tuple."""
    state = {"value": "case"}

    def latest(session, identifier):
        """Stand-in for repo.latest_intake_for."""
        return case_intake(identifier) if state["value"] == "case" else state["value"]

    monkeypatch.setattr(repo, "latest_intake_for", latest)
    return state


@pytest.fixture
def saved(monkeypatch):
    """Capture save_run's arguments instead of writing to a database; returns run id 42."""
    calls = []

    def save_run(session, patient, fhir_base_url, app_version, data, findings):
        """Stand-in for repo.save_run."""
        calls.append(locals())
        return 42

    monkeypatch.setattr(repo, "save_run", save_run)
    return calls


def _found(case, recorded_client, saved):
    """Reconcile a case patient; returns its findings as (type, medication) pairs plus the call."""
    assert service.reconcile(CASE_IDS[case], None, recorded_client, ALIASES) == 42
    (call,) = saved
    return [(f.discrepancy_type, f.medication) for f in call["findings"]], call


def test_case_mixed_gives_the_documented_findings(recorded_client, intake, saved):
    """data/README's CASE-MIXED table, plus V2's frequency mismatch: 8 findings."""
    found, call = _found("CASE-MIXED", recorded_client, saved)
    assert sorted(found) == [
        ("dosage_mismatch", "acetaminophen"),
        ("duplicate", "acetaminophen"),
        ("duplicate", "sertraline"),
        ("frequency_mismatch", "sertraline"),
        ("missing", "ibuprofen"),
        ("missing", "metoprolol"),
        ("missing", "omeprazole"),
        ("missing", "warfarin"),
    ]
    warfarin = next(f for f in call["findings"] if f.medication == "warfarin")
    assert warfarin.details["rejected_count"] == 2  # the pharmacy row and the intake entry
    assert "1 patient-reported record" in warfarin.summary
    assert "1 pharmacy record" in warfarin.summary
    assert all(f.medication != "metformin" for f in call["findings"])  # 500 mg == 0.5 g
    frequency = next(f for f in call["findings"] if f.discrepancy_type == "frequency_mismatch")
    assert frequency.summary == (
        "Patient-reported frequency once daily; FHIR frequency once daily; "
        "pharmacy frequency twice daily."
    )


def test_save_run_gets_patient_base_url_and_version(recorded_client, intake, saved):
    """The run is saved under the stable identifier with the FHIR base URL and app version."""
    _, call = _found("CASE-MIXED", recorded_client, saved)
    assert call["patient"].identifier == "CASE-MIXED"
    assert call["patient"].fhir_patient_id == "2178"
    assert (call["fhir_base_url"], call["app_version"]) == (BASE, __version__)


def test_without_an_interview_the_result_is_two_source(recorded_client, intake, saved):
    """No interview: intake is None and missing findings name a single source."""
    intake["value"] = None
    found, call = _found("CASE-MIXED", recorded_client, saved)
    assert call["data"].intake is None
    missing = [f for f in call["findings"] if f.discrepancy_type == "missing"]
    assert missing and all(isinstance(f.details["missing_from"], str) for f in missing)
    assert ("missing", "ibuprofen") not in found


def test_patient_reporting_no_medications_gives_empty_intake(recorded_client, intake, saved):
    """A no_medications interview gives intake == [] and every drug is unreported."""
    intake["value"] = (INTERVIEW.model_copy(update={"no_medications": True}), [])
    _, call = _found("CASE-CLEAN", recorded_client, saved)
    assert call["data"].intake == []
    assert {f.medication for f in call["findings"]} == {"lisinopril", "atorvastatin", "amlodipine"}
    assert all("patient reports no medications" in f.summary for f in call["findings"])


def test_case_clean_has_no_findings(recorded_client, intake, saved):
    """Alias matches and equal schedules across all three sources leave nothing to report."""
    assert _found("CASE-CLEAN", recorded_client, saved)[0] == []


def test_case_brand_matches_through_rxnorm(recorded_client, intake, saved):
    """Crestor isn't an alias, but RxNorm matches it to FHIR's rosuvastatin: 2 missing become 0."""
    found, call = _found("CASE-BRAND", recorded_client, saved)
    assert found == []
    (fhir,), (pharmacy,) = call["data"].fhir, call["data"].pharmacy
    assert fhir.normalized_name == pharmacy.normalized_name == "rosuvastatin"
    assert pharmacy.name == "Crestor" and fhir.rxcui and pharmacy.rxcui


def _medication_request(code, display):
    """An active coded MedicationRequest, as HAPI returns it."""
    return {
        "resourceType": "MedicationRequest",
        "id": code,
        "status": "active",
        "subject": {"reference": "Patient/1"},
        "authoredOn": "2026-09-01",
        "medicationCodeableConcept": {
            "coding": [{"system": RXNORM, "code": code, "display": display}],
            "text": display,
        },
    }


def _pharmacy_row(name, dose):
    """A valid pharmacy row for the test patient."""
    return {
        "record_id": f"PH-{name}-{dose}",
        "patient_id": "CASE-TEST",
        "medication_name": name,
        "dose_amount": dose,
        "dose_unit": "mg",
        "frequency": "once daily",
        "date_recorded": "2026-09-01",
    }


def _findings(fhir, pharmacy):
    """The real mapping, validation, aliases, committed RxNorm cache and rules, for one pair."""
    data = service.build_input(
        [_medication_request(*fhir)], "CASE-TEST", [_pharmacy_row(*pharmacy)], None, ALIASES
    )
    return run_rules(data)


def test_er_vs_ir_is_reported_not_merged_through_the_pipeline():
    """Metformin ER on FHIR vs a pharmacy row naming the plain tablet, same dose: one finding."""
    (f,) = _findings(
        ("860975", "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet"),
        ("metformin hydrochloride 500 MG Oral Tablet", "500"),
    )
    assert (f.discrepancy_type, f.medication) == ("dosage_mismatch", "metformin")
    assert f.details["different_form"] == {
        "fhir": "Extended Release Oral Tablet",
        "pharmacy": "Oral Tablet",
    }
    assert f.summary.startswith("Different form:")


def test_strength_difference_is_still_a_mismatch_through_the_pipeline():
    """A brand matched to its generic at another strength is a dose mismatch, not a match."""
    (f,) = _findings(("314076", "lisinopril 10 MG Oral Tablet"), ("Zestril", "20"))
    assert (f.discrepancy_type, f.medication) == ("dosage_mismatch", "lisinopril")
    assert f.summary == "FHIR dose 10 mg; pharmacy dose 20 mg."


def test_equivalent_brand_and_generic_give_no_finding_through_the_pipeline():
    """The same ingredient and dose, with the brand stating no form, is simply a match."""
    assert _findings(("314076", "lisinopril 10 MG Oral Tablet"), ("Zestril", "10")) == []


def test_salts_of_one_ingredient_are_reported_through_the_pipeline():
    """Tartrate on FHIR vs succinate at pharmacy: never silently the same drug."""
    (f,) = _findings(
        ("866924", "metoprolol tartrate 25 MG Oral Tablet"), ("Metoprolol Succinate", "25")
    )
    assert f.details["different_salt"] == {
        "fhir": "metoprolol tartrate",
        "pharmacy": "metoprolol succinate",
    }


def test_salt_with_a_strength_is_still_reported_through_the_pipeline():
    """ER succinate on FHIR vs a tartrate row with its strength: a difference, never silence."""
    (f,) = _findings(
        ("866427", "24 HR metoprolol succinate 25 MG Extended Release Oral Tablet"),
        ("Metoprolol Tartrate 25 mg", "25"),
    )
    assert f.discrepancy_type == "dosage_mismatch" and f.medication == "metoprolol"
    assert f.details["different_salt"] == {
        "fhir": "metoprolol succinate",
        "pharmacy": "metoprolol tartrate",
    }


def test_er_vs_a_plain_tablet_at_another_strength_reports_both_through_the_pipeline():
    """A form stated beside any strength is compared, not only a display the cache holds."""
    (f,) = _findings(
        ("860975", "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet"),
        ("metformin hydrochloride 1000 MG Oral Tablet", "1000"),
    )
    assert f.details["different_form"]["pharmacy"] == "Oral Tablet"
    assert "FHIR dose 500 mg; pharmacy dose 1000 mg." in f.summary


def test_er_abbreviation_is_compared_through_the_pipeline():
    """ "Metformin ER" against a plain tablet differs; against an ER product it agrees."""
    (f,) = _findings(
        ("861007", "metformin hydrochloride 500 MG Oral Tablet"), ("Metformin ER", "500")
    )
    assert f.details["different_form"] == {"fhir": "Oral Tablet", "pharmacy": "Extended Release"}
    er = ("860975", "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet")
    assert _findings(er, ("Metformin ER", "500")) == []


def test_er_name_with_a_plain_form_is_extended_release_through_the_pipeline():
    """ "Metformin ER … Oral Tablet" differs from a plain tablet and agrees with an ER one."""
    (f,) = _findings(
        ("861007", "metformin hydrochloride 500 MG Oral Tablet"),
        ("Metformin ER 500 mg Oral Tablet", "500"),
    )
    assert f.details["different_form"] == {
        "fhir": "Oral Tablet",
        "pharmacy": "Extended Release Oral Tablet",
    }
    er = ("860975", "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet")
    assert _findings(er, ("Metformin ER 500 mg Oral Tablet", "500")) == []


def test_capsule_vs_tablet_is_reported_through_the_pipeline():
    """A form the committed cache doesn't hold is still read from the name and compared."""
    (f,) = _findings(
        ("861007", "metformin hydrochloride 500 MG Oral Tablet"),
        ("Metformin 500 mg Oral Capsule", "500"),
    )
    assert f.details["different_form"]["pharmacy"] == "Oral Capsule"


def test_case_mixed_pharmacy_brand_is_matched_and_compared(recorded_client, intake, saved):
    """Pharmacy's Zoloft keeps its name, meets FHIR's sertraline, and their schedules compare."""
    _, call = _found("CASE-MIXED", recorded_client, saved)
    (zoloft,) = [r for r in call["data"].pharmacy if r.name == "Zoloft"]
    assert zoloft.normalized_name == "sertraline" and zoloft.rxcui == "82728"
    (f,) = [f for f in call["findings"] if f.discrepancy_type == "frequency_mismatch"]
    assert f.details["pharmacy_codes"] == ["BID"] and f.details["fhir_codes"] == ["QD"]


def test_rejected_fhir_record_is_named_as_the_pharmacy_rows_counterpart():
    """A coded rejection and a plain salt name meet, so it isn't presented as an omission."""
    (f,) = _findings(
        ("477045", "Chlorpheniramine Maleate 2 MG/ML Oral Solution"),
        ("Chlorpheniramine Maleate", "4"),
    )
    assert f.discrepancy_type == "missing" and f.medication == "chlorpheniramine"
    assert "1 FHIR record with this name was rejected" in f.summary


def test_rejected_brand_is_named_as_the_generics_counterpart():
    """Rejections go through RxNorm too: pharmacy's bad Crestor row meets FHIR's rosuvastatin."""
    data = service.build_input(
        [_medication_request("859751", "rosuvastatin calcium 20 MG Oral Tablet")],
        "CASE-TEST",
        [_pharmacy_row("Crestor", "ten")],
        None,
        ALIASES,
    )
    (f,) = run_rules(data)
    assert f.medication == "rosuvastatin"
    assert "1 pharmacy record with this name was rejected" in f.summary


def test_records_keep_their_original_names_and_carry_rxcui(recorded_client, intake, saved):
    """Every record in a real run has an RxCUI, beside the name its source gave."""
    _, call = _found("CASE-MIXED", recorded_client, saved)
    data = call["data"]
    assert all(r.rxcui for r in [*data.fhir, *data.pharmacy, *data.intake])
    assert {r.name for r in data.fhir} >= {"metoprolol tartrate 25 MG Oral Tablet"}


def test_intake_rejection_is_kept_and_normalized(recorded_client, intake, saved):
    """The 'not sure' warfarin entry is an intake rejection that still carries its identity."""
    _, call = _found("CASE-MIXED", recorded_client, saved)
    (warfarin,) = [r for r in call["data"].rejected if r.source == "intake"]
    assert warfarin.normalized_name == "warfarin"
    assert [r.code for r in warfarin.reasons] == ["unreadable_dosage"]


def test_collect_does_not_save(recorded_client, intake, saved):
    """collect is a preview: it returns the prepared input and the interview, never saves."""
    prepared = service.collect("2178", None, recorded_client, ALIASES)
    assert saved == []
    assert prepared.interview.taken_by == "RN Okafor"
    assert {r.normalized_name for r in prepared.data.intake} >= {"metformin", "ibuprofen"}
