"""FhirClient: next-link pager, decided request shapes over recorded fixtures, errors."""

import json
from pathlib import Path

import httpx
import pytest

from app.fhir_client import FhirClient, patient_row

BASE = "http://hapi.test/fhir"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "hapi"


def _relative(request: httpx.Request) -> str:
    """The request URL relative to BASE, exactly as sent (percent-encoding kept)."""
    return str(request.url).removeprefix(BASE + "/")


def _searchset(ids: list[str], next_url: str | None = None) -> dict:
    """A minimal searchset bundle of Patients, with an optional next link."""
    links = [{"relation": "next", "url": next_url}] if next_url else []
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "link": links,
        "entry": [{"resource": {"resourceType": "Patient", "id": i}} for i in ids],
    }


def test_pager_follows_next_links_across_two_pages():
    """A two-page searchset yields both pages' resources in order."""
    page2 = f"{BASE}?_getpages=abc&_getpagesoffset=2&_count=2"
    seen = []

    def handler(request):
        """Page 1 for the search URL, page 2 for its absolute next link."""
        seen.append(str(request.url))
        if str(request.url) == page2:
            return httpx.Response(200, json=_searchset(["3"]))
        return httpx.Response(200, json=_searchset(["1", "2"], next_url=page2))

    client = FhirClient(BASE, transport=httpx.MockTransport(handler))
    assert [p["id"] for p in client.list_patients()] == ["1", "2", "3"]
    assert seen == [f"{BASE}/Patient?_count=50", page2]


@pytest.fixture
def recorded():
    """A client served from tests/fixtures/hapi by index.json key; unknown URLs fail."""
    index = json.loads((FIXTURES / "index.json").read_text())
    requested = []

    def handler(request):
        """Serve the recorded file for an exact key, or 404 so a wrong shape fails loudly."""
        key = _relative(request)
        requested.append(key)
        if key not in index:
            return httpx.Response(404, json={"unexpected": key})
        return httpx.Response(200, content=(FIXTURES / index[key]).read_bytes())

    client = FhirClient(BASE, transport=httpx.MockTransport(handler))
    client.requested = requested
    return client


def test_read_patient_uses_the_decided_shape(recorded):
    """Patient/{id} returns the recorded CASE-MIXED patient."""
    patient = recorded.read_patient("2178")
    assert recorded.requested == ["Patient/2178"]
    assert patient["identifier"][0]["value"] == "CASE-MIXED"


def test_active_medication_requests_use_the_decided_shape(recorded):
    """MedicationRequest?patient={id}&status=active (no _count) returns the five recorded meds."""
    meds = recorded.active_medication_requests("2178")
    assert recorded.requested == ["MedicationRequest?patient=2178&status=active"]
    assert len(meds) == 5 and {m["resourceType"] for m in meds} == {"MedicationRequest"}


def test_find_case_patient_encodes_the_identifier_like_the_fixtures(recorded):
    """Patient?identifier=urn%3Amedrec%3Acase%7C<CASE> finds the case patient."""
    (patient,) = recorded.find_case_patient("CASE-MIXED")
    assert recorded.requested == ["Patient?identifier=urn%3Amedrec%3Acase%7CCASE-MIXED"]
    assert patient["id"] == "2178"


def test_http_error_raises():
    """A non-2xx response raises instead of returning an empty list."""
    client = FhirClient(BASE, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        client.active_medication_requests("1")


def test_patient_row_formats_display_fields():
    """Given names then family; missing name gives None."""
    resource = json.loads((FIXTURES / "CASE-MIXED" / "patient_read.json").read_text())
    assert patient_row(resource) == {
        "id": "2178",
        "name": "Marcus Mixton",
        "birth_date": "1951-11-30",
        "gender": "male",
    }
    assert patient_row({"id": "9"})["name"] is None
