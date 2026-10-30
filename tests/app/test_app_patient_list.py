"""Patient list page: live FHIR list through an injected transport, and FHIR down."""

import httpx
import pytest

from app.fhir_client import FhirClient
from app.labels import DISCLAIMER
from app.main import app, get_fhir_client


@pytest.fixture
def fhir(request):
    """Override the FHIR client with a MockTransport handler; removed after the test."""

    def use(handler):
        """Route the app's FHIR requests to handler."""
        client = FhirClient("http://hapi.test/fhir", transport=httpx.MockTransport(handler))
        app.dependency_overrides[get_fhir_client] = lambda: client

    yield use
    app.dependency_overrides.pop(get_fhir_client, None)


def test_patient_list_links_each_patient(client, fhir):
    """Patients from Patient?_count=50 are listed with links to their detail pages."""
    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "2178",
                    "name": [{"given": ["Marcus"], "family": "Mixton"}],
                    "birthDate": "1951-11-30",
                    "gender": "male",
                }
            }
        ],
    }
    fhir(lambda request: httpx.Response(200, json=bundle))
    html = client.get("/").text
    assert '<a href="/patients/2178">Marcus Mixton</a>' in html
    assert "1951-11-30" in html and DISCLAIMER in html


def test_empty_server_says_so(client, fhir):
    """A searchset with no entries shows a plain message."""
    fhir(lambda request: httpx.Response(200, json={"resourceType": "Bundle", "type": "searchset"}))
    assert "No patients on the FHIR server." in client.get("/").text


def test_fhir_unavailable_is_a_502_page(client, fhir):
    """A connection error renders a readable 502 page, not a traceback."""

    def down(request):
        """Simulate HAPI not accepting connections."""
        raise httpx.ConnectError("connection refused", request=request)

    fhir(down)
    response = client.get("/")
    assert response.status_code == 502
    assert "FHIR server unavailable" in response.text and DISCLAIMER in response.text
