"""FhirClient: next-link pager, decided request shapes over recorded fixtures, errors."""

import json

import httpx
import pytest

from app.fhir_client import MAX_PAGES, FhirClient, FhirError, InvalidFhirId, patient_row
from tests.app.conftest import BASE, FIXTURES


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


def test_read_patient_uses_the_decided_shape(recorded_client):
    """Patient/{id} returns the recorded CASE-MIXED patient."""
    patient = recorded_client.read_patient("2178")
    assert recorded_client.requested == ["Patient/2178"]
    assert patient["identifier"][0]["value"] == "CASE-MIXED"


def test_active_medication_requests_use_the_decided_shape(recorded_client):
    """MedicationRequest?patient={id}&status=active (no _count) returns the five recorded meds."""
    meds = recorded_client.active_medication_requests("2178")
    assert recorded_client.requested == ["MedicationRequest?patient=2178&status=active"]
    assert len(meds) == 5 and {m["resourceType"] for m in meds} == {"MedicationRequest"}


def test_find_case_patient_encodes_the_identifier_like_the_fixtures(recorded_client):
    """Patient?identifier=urn%3Amedrec%3Acase%7C<CASE> finds the case patient."""
    (patient,) = recorded_client.find_case_patient("CASE-MIXED")
    assert recorded_client.requested == ["Patient?identifier=urn%3Amedrec%3Acase%7CCASE-MIXED"]
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


@pytest.mark.parametrize(
    "bad_id", ["2178?_elements=id", "2178&status=x", "../Patient", "", "a" * 65]
)
def test_malformed_id_is_refused_before_any_request(bad_id):
    """An id outside the FHIR id rule never reaches the server, so it can't reshape the query."""
    sent = []
    client = FhirClient(BASE, transport=httpx.MockTransport(lambda r: sent.append(r) or None))
    with pytest.raises(InvalidFhirId):
        client.read_patient(bad_id)
    with pytest.raises(InvalidFhirId):
        client.active_medication_requests(bad_id)
    assert sent == []


def test_non_json_reply_raises_fhir_error():
    """A 200 HTML page (a proxy, HAPI starting up) is a FhirError, not a JSONDecodeError."""
    html = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>starting</html>"))
    with pytest.raises(FhirError, match="non-JSON"):
        FhirClient(BASE, transport=html).read_patient("2178")


def test_endless_next_links_stop_at_max_pages():
    """A next link that points back to itself raises after MAX_PAGES requests."""
    sent = []
    loop = {"resourceType": "Bundle", "link": [{"relation": "next", "url": f"{BASE}/Patient?p=1"}]}

    def handler(request):
        """Always answer with a page whose next link is the same page."""
        sent.append(request)
        return httpx.Response(200, json=loop)

    with pytest.raises(FhirError, match="exceeded"):
        FhirClient(BASE, transport=httpx.MockTransport(handler)).list_patients()
    assert len(sent) == MAX_PAGES
