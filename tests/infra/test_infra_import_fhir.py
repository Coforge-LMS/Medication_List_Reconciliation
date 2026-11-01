"""infra/import_fhir.py: load order, skip-if-imported, and loud failure (no HAPI needed)."""

import pytest

from infra import import_fhir as imp


@pytest.fixture
def server(monkeypatch):
    """Fake HAPI: records POSTed bundle names and answers the marker lookup."""
    state = {"marker_total": 0, "posted": [], "post_status": "201 Created", "post_http": 200}
    monkeypatch.setattr(imp, "wait_for_server", lambda: None)

    def fake_request(method, url, body=None, headers=None):
        if method == "GET":
            return 200, {"resourceType": "Bundle", "total": state["marker_total"]}
        state["posted"].append(body["entry"][0]["resource"]["resourceType"])
        entries = [{"response": {"status": state["post_status"]}} for _ in body["entry"]]
        return state["post_http"], {"resourceType": "Bundle", "entry": entries}

    monkeypatch.setattr(imp, "request", fake_request)
    return state


def test_load_order_is_hospital_practitioner_patients_cases():
    names = [p.name for p in imp.load_order()]
    assert names[0].startswith("hospitalInformation")
    assert names[1].startswith("practitionerInformation")
    assert names[-1] == "medrec-cases.json"
    assert len(names) == 13  # hospital + practitioner + 10 Synthea patients + cases


def test_demo_bundle_is_never_imported():
    """The live-demo patient stays out of the import, so the count and recorded ids don't move."""
    assert "new-patient.json" not in [p.name for p in imp.load_order()]
    assert (imp.DATA_DIR / "demo" / "new-patient.json").is_file()


def test_imports_every_bundle_when_marker_absent(server):
    assert imp.main() == 0
    assert len(server["posted"]) == 13
    assert server["posted"][:2] == ["Organization", "Practitioner"]


def test_second_run_is_a_noop_when_marker_present(server):
    server["marker_total"] = 1
    assert imp.main() == 0
    assert server["posted"] == []


def test_failed_entry_fails_loudly(server):
    server["post_status"] = "400 Bad Request"
    with pytest.raises(imp.FhirImportError, match="not fully applied"):
        imp.main()


def test_http_error_propagates_and_exits_non_zero(server, monkeypatch):
    def boom(method, url, body=None, headers=None):
        if method == "GET":
            return 200, {"total": 0}
        raise imp.FhirImportError("POST failed: HTTP 422")

    monkeypatch.setattr(imp, "request", boom)
    with pytest.raises(imp.FhirImportError):
        imp.main()


def test_image_build_includes_the_rxnorm_cache():
    """The app refuses to start without the cache, so it must get through both build filters."""
    root = imp.DATA_DIR.parents[1]
    assert "!data/rxnorm_cache.json" in (root / ".dockerignore").read_text().splitlines()
    assert "COPY data/rxnorm_cache.json" in (root / "infra" / "Dockerfile").read_text()


def test_compose_passes_rxnorm_live_through_to_the_app():
    """The app's environment is explicit, so the flag must be listed or it never arrives."""
    compose = (imp.DATA_DIR.parents[1] / "infra" / "docker-compose.yml").read_text()
    assert "RXNORM_LIVE: ${RXNORM_LIVE:-0}" in compose
