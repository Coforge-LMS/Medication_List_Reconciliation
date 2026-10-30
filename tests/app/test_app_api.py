"""Run JSON endpoint: documented shape and 404."""

from tests.app.conftest import make_run


def test_run_json_has_the_documented_shape(client, serve_run):
    """Patient, interview, the three record lists, rejections and findings with three values."""
    serve_run(make_run())
    response = client.get("/api/runs/7")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "run_id",
        "app_version",
        "started_at",
        "patient",
        "intake_interview",
        "intake",
        "fhir",
        "pharmacy",
        "rejected",
        "findings",
    }
    assert body["patient"]["identifier"] == "CASE-MIXED"
    assert body["intake_interview"]["taken_by"] == "RN Okafor"
    assert body["fhir"][0]["dose_amount"] == "25"
    assert {"intake_value", "fhir_value", "pharmacy_value"} <= set(body["findings"][0])
    assert body["findings"][1]["intake_value"] == "200 mg"


def test_run_json_without_interview_is_null(client, serve_run):
    """No interview serializes as null, with an empty intake list."""
    serve_run(make_run(intake_interview=None, intake=[]))
    body = client.get("/api/runs/7").json()
    assert body["intake_interview"] is None and body["intake"] == []


def test_missing_run_json_is_404(client, serve_run):
    """An unknown run id gives 404 with a detail message."""
    serve_run(None)
    response = client.get("/api/runs/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}
