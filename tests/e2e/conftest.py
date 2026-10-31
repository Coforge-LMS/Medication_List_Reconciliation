"""Real app and Postgres; only the FHIR HTTP boundary is replaced by recorded responses."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.fhir_client import FhirClient
from app.main import app, get_fhir_client
from db.session import get_session

ROOT = Path(__file__).resolve().parents[2]
FHIR_BASE = "http://hapi.test/fhir"


@pytest.fixture
def e2e_client(db, monkeypatch):
    """Use the guarded, truncated test DB and refuse any unrecorded FHIR request."""
    fixtures = ROOT / "tests" / "fixtures" / "hapi"
    index = json.loads((fixtures / "index.json").read_text())
    requested = []

    def handler(request):
        key = str(request.url).removeprefix(FHIR_BASE + "/")
        assert request.method == "GET"
        assert key in index, f"Unrecorded FHIR request: {request.url}"
        requested.append(key)
        return httpx.Response(200, content=(fixtures / index[key]).read_bytes())

    def session():
        with Session(db) as value:
            yield value

    monkeypatch.setenv("ALIASES_PATH", str(ROOT / "data" / "aliases.json"))
    monkeypatch.setenv("PHARMACY_DATA", str(ROOT / "data" / "pharmacy" / "pharmacy_records.json"))
    overrides = app.dependency_overrides.copy()
    fhir = FhirClient(FHIR_BASE, transport=httpx.MockTransport(handler))
    try:
        app.dependency_overrides[get_fhir_client] = lambda: fhir
        app.dependency_overrides[get_session] = session
        with TestClient(app) as client:
            yield client, requested
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)
        fhir.close()
