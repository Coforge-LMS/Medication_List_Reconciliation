"""Home page: HAPI search through an injected transport, and the recent patients list."""

from datetime import UTC, datetime

import httpx
import pytest

from app.fhir_client import FhirClient
from app.labels import DISCLAIMER
from app.main import app, get_fhir_client
from contract import PatientInfo
from db import repo
from db.session import get_session

MIXTON = {
    "resourceType": "Patient",
    "id": "2178",
    "identifier": [{"system": "urn:medrec:case", "value": "CASE-MIXED"}],
    "name": [{"given": ["Marcus"], "family": "Mixton"}],
    "birthDate": "1951-11-30",
    "gender": "male",
}


def _bundle(*patients):
    """A searchset holding these patients."""
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": p} for p in patients],
    }


@pytest.fixture
def home(monkeypatch):
    """A home page with no database, no recent patients, and a settable FHIR handler."""

    def no_session():
        """Stand-in for db.session.get_session."""
        yield None

    def fhir(handler):
        """Route the app's FHIR requests to handler."""
        client = FhirClient("http://hapi.test/fhir", transport=httpx.MockTransport(handler))
        app.dependency_overrides[get_fhir_client] = lambda: client

    monkeypatch.setattr(repo, "recent_patients", lambda session: [])
    app.dependency_overrides[get_session] = no_session
    yield fhir
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_fhir_client, None)


def _no_fhir(request):
    """Fail the test if the page contacts FHIR."""
    raise AssertionError(f"unexpected FHIR request: {request.url}")


def test_opening_the_home_page_does_not_contact_fhir(client, home):
    """Without a query there is a search box, no results section and no FHIR request."""
    home(_no_fhir)
    html = client.get("/").text
    assert 'name="q"' in html and "Search results" not in html
    assert "No patients reconciled yet." in html and DISCLAIMER in html


def test_blank_query_does_not_contact_fhir(client, home):
    """A query of only spaces counts as no search."""
    home(_no_fhir)
    assert "Search results" not in client.get("/", params={"q": "   "}).text


def test_search_lists_matches_with_links(client, home):
    """A match shows its name, identifier and birth date, linking to the patient page."""
    home(lambda request: httpx.Response(200, json=_bundle(MIXTON)))
    html = client.get("/", params={"q": "mix"}).text
    assert '<a href="/patients/2178">Marcus Mixton</a>' in html
    assert "CASE-MIXED" in html and "1951-11-30" in html
    assert 'value="mix"' in html  # the query stays in the box


def test_search_without_matches_says_so(client, home):
    """No matches is stated, with the query escaped."""
    home(lambda request: httpx.Response(200, json=_bundle()))
    html = client.get("/", params={"q": "<b>nobody</b>"}).text
    assert "No patients match" in html and "&lt;b&gt;nobody&lt;/b&gt;" in html
    assert "<b>nobody</b>" not in html


def test_recent_patients_are_listed_with_their_last_run(client, home, monkeypatch):
    """Patients from the database link to their page and show the last run in UTC."""
    home(_no_fhir)
    patient = PatientInfo(identifier="CASE-MIXED", fhir_patient_id="2178", name="Marcus Mixton")
    last_run = datetime(2026, 10, 31, 9, 15, tzinfo=UTC)
    monkeypatch.setattr(repo, "recent_patients", lambda session: [(patient, last_run)])
    html = client.get("/").text
    assert '<a href="/patients/2178">Marcus Mixton</a>' in html
    assert "2026-10-31 09:15" in html
    assert "No patients reconciled yet." not in html


def test_search_with_fhir_down_is_a_502_page(client, home):
    """A connection error during a search renders a readable 502 page."""

    def down(request):
        """Simulate HAPI not accepting connections."""
        raise httpx.ConnectError("connection refused", request=request)

    home(down)
    response = client.get("/", params={"q": "mix"})
    assert response.status_code == 502
    assert "FHIR server unavailable" in response.text and DISCLAIMER in response.text


def test_non_json_fhir_reply_is_a_502_page(client, home):
    """A 200 HTML reply on the patient search renders the 502 page."""
    home(lambda request: httpx.Response(200, text="<html>starting</html>"))
    response = client.get("/", params={"q": "mix"})
    assert response.status_code == 502 and "FHIR server unavailable" in response.text


def test_full_name_reaches_fhir_as_separate_name_values(client, home):
    """Searching a full name, as the results table displays it, sends one name value per word."""
    sent = []

    def handler(request):
        """Record the query and answer with the patient."""
        sent.append(str(request.url))
        return httpx.Response(200, json=_bundle(MIXTON))

    home(handler)
    html = client.get("/", params={"q": "Marcus Mixton"}).text
    assert '<a href="/patients/2178">Marcus Mixton</a>' in html
    assert "name=Marcus&name=Mixton" in sent[0]


def test_control_characters_show_no_matches_without_calling_fhir(client, home):
    """A NUL in the query is a plain no-match, not a FHIR outage."""
    home(_no_fhir)
    response = client.get("/?q=%00")
    assert response.status_code == 200 and "No patients match" in response.text


def test_fhir_error_page_hides_the_internal_url(client, home):
    """A FHIR 500 says so by status, without showing the server's address."""
    home(lambda request: httpx.Response(500))
    response = client.get("/", params={"q": "mix"})
    assert response.status_code == 502
    assert "answered with status 500" in response.text
    assert "hapi.test" not in response.text
