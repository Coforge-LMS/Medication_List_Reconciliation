"""Patient detail page, reconcile POST and JSON, history and error pages (no database)."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.fhir_client import FhirClient
from app.labels import DISCLAIMER
from app.main import app, get_fhir_client
from contract import RunSummary
from db import repo
from db.session import get_session
from tests.app.conftest import case_intake, make_run


@pytest.fixture
def wired(monkeypatch, recorded_client):
    """Recorded FHIR, committed intake, and a save_run that returns 42; no database session."""
    saved = []
    monkeypatch.setattr(repo, "latest_intake_for", lambda session, ident: case_intake(ident))
    monkeypatch.setattr(repo, "save_run", lambda *args: saved.append(args) or 42)

    def no_session():
        """Stand-in for db.session.get_session."""
        yield None

    app.dependency_overrides[get_session] = no_session
    app.dependency_overrides[get_fhir_client] = lambda: recorded_client
    yield saved
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_fhir_client, None)


def test_patient_page_shows_three_columns_and_the_run_button(client, wired):
    """The detail page lists each source's records, rejections and the interview."""
    html = client.get("/patients/2178").text
    assert "Marcus Mixton" in html and "CASE-MIXED" in html
    compared = html[html.index("Medications compared") :]
    assert compared.index("Patient-reported") < compared.index("FHIR") < compared.index("Pharmacy")
    assert "Ibuprofen" in compared and "metoprolol tartrate" in compared
    assert "Omeprazole" in compared  # an accepted pharmacy-only record
    assert "Warfarin Sodium" in compared  # the rejected pharmacy row
    assert '<p id="interview">Intake taken 2026-10-28 by RN Okafor (patient)</p>' in html
    assert 'action="/patients/2178/reconcile"' in html and "/patients/2178/history" in html
    assert wired == []  # viewing never saves


def test_reconcile_post_redirects_to_the_run(client, wired):
    """POST runs and saves, then 303s to /runs/{id}."""
    response = client.post("/patients/2178/reconcile", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/runs/42"
    assert len(wired) == 1


def _fhir(handler):
    """Point the app at a MockTransport FHIR server."""
    client = FhirClient("http://hapi.test/fhir", transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_fhir_client] = lambda: client


def _down(request):
    """Simulate HAPI not accepting connections."""
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    ("handler", "status", "heading"),
    [
        (lambda request: httpx.Response(404, json={}), 404, "Patient not found"),
        (_down, 502, "FHIR server unavailable"),
        (
            lambda request: httpx.Response(200, json={"resourceType": "Patient", "id": "9"}),
            422,
            "Patient cannot be reconciled",
        ),
    ],
    ids=["unknown-patient", "fhir-down", "no-identifier"],
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_fhir_failures_render_error_pages(client, wired, method, handler, status, heading):
    """FHIR failures give readable pages with the usual footer, for viewing and for running."""
    _fhir(handler)
    path = "/patients/9" if method == "get" else "/patients/9/reconcile"
    response = getattr(client, method)(path)
    assert response.status_code == status
    assert heading in response.text and DISCLAIMER in response.text
    assert wired == []


def test_missing_pharmacy_dataset_is_503(client, wired, tmp_path, monkeypatch):
    """Without the baked pharmacy file the page says so instead of failing."""
    monkeypatch.setenv("PHARMACY_DATA", str(tmp_path / "missing.json"))
    response = client.get("/patients/2178")
    assert response.status_code == 503
    assert "Pharmacy dataset not available" in response.text


def test_reconcile_api_returns_201_with_the_run_json(client, wired, monkeypatch):
    """POST /api/patients/{id}/reconcile saves and returns the run as GET /api/runs/{id} does."""
    monkeypatch.setattr(repo, "get_run", lambda session, run_id: make_run(run_id=run_id))
    response = client.post("/api/patients/2178/reconcile")
    assert response.status_code == 201
    body = response.json()
    assert body["run_id"] == 42 and len(wired) == 1
    assert {"patient", "intake_interview", "intake", "fhir", "pharmacy", "rejected"} <= set(body)
    assert body == client.get("/api/runs/42").json()


def test_reconcile_api_reports_fhir_failures_as_json(client, wired):
    """An unknown patient is a JSON 404 with a readable detail."""
    _fhir(lambda request: httpx.Response(404, json={}))
    response = client.post("/api/patients/9/reconcile")
    assert response.status_code == 404
    assert response.json()["detail"].startswith("Patient not found")


def test_history_lists_runs_newest_first_with_labels(client, wired, monkeypatch):
    """Runs come from list_runs for the stable identifier; unknown types render as Other (x)."""
    asked = []

    def list_runs(session, identifier):
        """Stand-in for repo.list_runs; newest first, as the repo returns them."""
        asked.append(identifier)
        return [
            RunSummary(
                run_id=8,
                app_version="1.1.0",
                started_at=datetime(2026, 10, 31, 9, 0, tzinfo=UTC),
                finding_count=3,
                counts_by_type={"missing": 2, "frequency_mismatch": 1},
            ),
            RunSummary(
                run_id=7,
                app_version="1.0.0",
                started_at=datetime(2026, 10, 30, 14, 5, tzinfo=UTC),
                finding_count=0,
                counts_by_type={},
            ),
        ]

    monkeypatch.setattr(repo, "list_runs", list_runs)
    html = client.get("/patients/2178/history").text
    assert asked == ["CASE-MIXED"]
    assert html.index('href="/runs/8"') < html.index('href="/runs/7"')
    assert "Missing medication: 2; Other (frequency_mismatch): 1" in html
    assert "2026-10-31 09:00" in html and DISCLAIMER in html


def test_history_without_runs_says_so(client, wired, monkeypatch):
    """A patient never reconciled shows a plain message."""
    monkeypatch.setattr(repo, "list_runs", lambda session, identifier: [])
    assert "No runs yet" in client.get("/patients/2178/history").text


def test_history_of_unknown_patient_is_404(client, wired):
    """The identifier can't be resolved, so the page is a 404."""
    _fhir(lambda request: httpx.Response(404, json={}))
    assert client.get("/patients/9/history").status_code == 404


@pytest.mark.parametrize("method", ["get", "post"])
def test_malformed_fhir_id_is_404_without_saving(client, wired, recorded_client, method):
    """An encoded '?' in the id is refused: 404, nothing sent to FHIR, nothing saved."""
    path = "/patients/2178%3F_elements=id" + ("" if method == "get" else "/reconcile")
    response = getattr(client, method)(path)
    assert response.status_code == 404 and "Patient not found" in response.text
    assert recorded_client.requested == [] and wired == []


def test_non_json_fhir_reply_is_a_502_page(client, wired):
    """A 200 HTML reply from FHIR renders the readable 502 page, not a traceback."""
    _fhir(lambda request: httpx.Response(200, text="<html>starting</html>"))
    response = client.get("/patients/2178")
    assert response.status_code == 502 and "FHIR server unavailable" in response.text


def test_corrupt_pharmacy_dataset_is_503(client, wired, tmp_path, monkeypatch):
    """A pharmacy file that isn't valid JSON gives the 503 page."""
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json")
    monkeypatch.setenv("PHARMACY_DATA", str(corrupt))
    response = client.get("/patients/2178")
    assert response.status_code == 503
    assert "Pharmacy dataset not available" in response.text


def _pharmacy_file(tmp_path, monkeypatch, rows):
    """Point the app at a pharmacy dataset holding only these rows."""
    path = tmp_path / "pharmacy.json"
    path.write_text(json.dumps(rows))
    monkeypatch.setenv("PHARMACY_DATA", str(path))


def test_patient_without_pharmacy_data_shows_no_data_and_no_run_button(
    client, wired, tmp_path, monkeypatch
):
    """FHIR meds still show, the pharmacy column says No data, and nothing can be run."""
    _pharmacy_file(tmp_path, monkeypatch, [])
    response = client.get("/patients/2178")
    assert response.status_code == 200
    html = response.text
    assert "metoprolol tartrate" in html  # FHIR side is still shown
    assert "No pharmacy records on file for this patient" in html
    assert "No data" in html and "/reconcile" not in html
    assert "/patients/2178/history" in html


def test_reconcile_without_pharmacy_data_is_refused_and_saves_nothing(
    client, wired, tmp_path, monkeypatch
):
    """Both the form POST and the API give 409, so no false "missing" findings are saved."""
    _pharmacy_file(tmp_path, monkeypatch, [])
    page = client.post("/patients/2178/reconcile", follow_redirects=False)
    assert page.status_code == 409 and "No pharmacy records on file" in page.text
    api = client.post("/api/patients/2178/reconcile")
    assert api.status_code == 409
    assert api.json() == {
        "detail": "No pharmacy records on file: Nothing to compare for CASE-MIXED."
    }
    assert wired == []


def test_pharmacy_rows_that_were_all_rejected_still_count_as_data(
    client, wired, tmp_path, monkeypatch
):
    """Rows on file that all fail validation can still be run; the rejections are the point."""
    bad = {
        "record_id": "PH-X",
        "patient_id": "CASE-MIXED",
        "medication_name": "metformin",
        "dose_amount": "ten",
        "dose_unit": "mg",
        "frequency": "",
        "date_recorded": "2026-09-15",
    }
    _pharmacy_file(tmp_path, monkeypatch, [bad])
    html = client.get("/patients/2178").text
    assert 'action="/patients/2178/reconcile"' in html
    assert "No accepted records" in html
    assert client.post("/patients/2178/reconcile", follow_redirects=False).status_code == 303


def test_fhir_and_pharmacy_without_an_interview_can_still_run(client, wired, monkeypatch):
    """No interview only empties the Patient-reported column; two-source reconcile still runs."""
    monkeypatch.setattr(repo, "latest_intake_for", lambda session, ident: None)
    html = client.get("/patients/2178").text
    assert "No intake history recorded" in html and "No data" in html
    assert 'action="/patients/2178/reconcile"' in html
    assert client.post("/patients/2178/reconcile", follow_redirects=False).status_code == 303
    assert wired[0][4].intake is None  # save_run's ReconciliationInput


def test_patient_with_full_data_shows_no_no_data_marker(client, wired):
    """All three sources present: nothing says No data."""
    assert "No data" not in client.get("/patients/2178").text


def test_fhir_failure_on_the_patient_page_hides_the_internal_url(client, wired):
    """Neither a refused connection nor a FHIR 500 shows the server's address."""
    _fhir(_down)
    down = client.get("/patients/9")
    assert "could not be reached" in down.text and "hapi.test" not in down.text
    _fhir(lambda request: httpx.Response(500))
    error = client.get("/patients/9")
    assert "answered with status 500" in error.text and "hapi.test" not in error.text
