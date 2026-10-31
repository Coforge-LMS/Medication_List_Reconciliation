"""FHIR REST client for HAPI: patient reads and paged searches.

Request shapes are the decided ones, the keys of tests/fixtures/hapi/index.json, so recorded
fixtures and the E2E test match by exact URL. The transport is injectable for tests.
"""

import os
import re
import unicodedata
import urllib.parse
from typing import Any

import httpx

from ingest.fhir import CASE_ID_SYSTEM, SYNTHEA_ID_SYSTEM, _patient_name

DEFAULT_BASE_URL = "http://localhost:8080/fhir"
MAX_PAGES = 100  # guards against a next-link loop
FHIR_ID = re.compile(r"[A-Za-z0-9\-.]{1,64}")  # FHIR R4 id datatype


class InvalidFhirId(ValueError):
    """An id that isn't a valid FHIR id, refused before any request is sent."""


class FhirError(Exception):
    """A FHIR response the client can't use: not JSON, or a search that never ends."""


def _checked(patient_id: str) -> str:
    """The id unchanged when it is a valid FHIR id, so it can't alter the request URL."""
    if not FHIR_ID.fullmatch(patient_id):
        raise InvalidFhirId(f"{patient_id!r} is not a FHIR id")
    return patient_id


class FhirClient:
    """Thin httpx wrapper; every response is checked with raise_for_status()."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Build a client for base_url; pass an httpx.MockTransport in tests."""
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url + "/",
            transport=transport,
            timeout=timeout,
            headers={"Accept": "application/fhir+json"},
        )

    @classmethod
    def from_env(cls) -> "FhirClient":
        """Client for FHIR_BASE_URL (default: HAPI on localhost)."""
        return cls(os.environ.get("FHIR_BASE_URL", DEFAULT_BASE_URL))

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._http.close()

    def read_patient(self, patient_id: str) -> dict[str, Any]:
        """GET Patient/{id}."""
        return self._get(f"Patient/{_checked(patient_id)}")

    def active_medication_requests(self, patient_id: str) -> list[dict[str, Any]]:
        """GET MedicationRequest?patient={id}&status=active, following next links."""
        return self._search(f"MedicationRequest?patient={_checked(patient_id)}&status=active")

    def find_case_patient(self, case: str) -> list[dict[str, Any]]:
        """GET Patient?identifier=urn:medrec:case|<case> (encoded as the recorded fixtures)."""
        identifier = urllib.parse.quote(f"urn:medrec:case|{case}", safe="")
        return self._search(f"Patient?identifier={identifier}")

    def search_patients(self, query: str) -> list[dict[str, Any]]:
        """Patients matching every word of query by name, or all of it by identifier.

        Each word matches the start of a name part, so "Marcus Mixton" and "mix" both work. Runs
        Patient?name= and Patient?identifier= (live only: no recorded fixture), name matches first.
        Words are percent-encoded, so they can't add search parameters of their own. A query with
        control characters can't match anything, so it never reaches the server.
        """
        words = query.split()
        if not words or any(unicodedata.category(c) == "Cc" for c in "".join(words)):
            return []
        names = "&".join(f"name={urllib.parse.quote(word, safe='')}" for word in words)
        identifier = urllib.parse.quote(query, safe="")
        matches = [
            *self._search(f"Patient?{names}&_count=50"),
            *self._search(f"Patient?identifier={identifier}"),
        ]
        patients = [p for p in matches if p.get("resourceType") == "Patient" and p.get("id")]
        return list({patient["id"]: patient for patient in patients}.values())

    def _get(self, url: str) -> dict[str, Any]:
        """One GET; url is relative to the base or an absolute next link."""
        response = self._http.get(url)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise FhirError("The FHIR server sent a non-JSON response.") from exc

    def _search(self, url: str) -> list[dict[str, Any]]:
        """Resources from a searchset, page by page via link[relation=next]."""
        resources: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            bundle = self._get(url)
            resources += [e["resource"] for e in bundle.get("entry", []) if "resource" in e]
            url = next(
                (link["url"] for link in bundle.get("link", []) if link.get("relation") == "next"),
                None,
            )
            if url is None:
                return resources
        raise FhirError(f"The FHIR search exceeded {MAX_PAGES} pages.")


def patient_row(resource: dict[str, Any]) -> dict[str, str | None]:
    """Display fields for a patient row: id, 'Given Family', identifier, birth date, gender."""
    identifier = next(
        (
            i.get("value")
            for i in resource.get("identifier") or []
            if i.get("system") in (SYNTHEA_ID_SYSTEM, CASE_ID_SYSTEM)
        ),
        None,
    )
    return {
        "id": resource.get("id"),
        "name": _patient_name(resource),
        "identifier": identifier,
        "birth_date": resource.get("birthDate"),
        "gender": resource.get("gender"),
    }
