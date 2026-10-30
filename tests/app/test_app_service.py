"""service.build_input / collect / reconcile over the committed data and recorded HAPI fixtures.

The DB calls (latest_intake_for, save_run) are replaced; everything else is the real pipeline.
"""

from pathlib import Path

import pytest

from app import service
from app.version import __version__
from db import repo
from ingest.aliases import load_aliases
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


def test_case_mixed_gives_the_seven_documented_findings(recorded_client, intake, saved):
    """data/README's CASE-MIXED table: 7 findings across the three sources."""
    found, call = _found("CASE-MIXED", recorded_client, saved)
    assert sorted(found) == [
        ("dosage_mismatch", "acetaminophen"),
        ("duplicate", "acetaminophen"),
        ("duplicate", "sertraline"),
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
    """Alias matches across all three sources leave nothing to report."""
    assert _found("CASE-CLEAN", recorded_client, saved)[0] == []


def test_case_brand_gives_two_missing_in_v1(recorded_client, intake, saved):
    """Crestor isn't an alias, so FHIR's rosuvastatin calcium and crestor don't match in V1."""
    found, _ = _found("CASE-BRAND", recorded_client, saved)
    assert sorted(found) == [("missing", "crestor"), ("missing", "rosuvastatin calcium")]


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
