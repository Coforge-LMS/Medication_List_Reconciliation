import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_reports_pyproject_version():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text())["project"]["version"]
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": version}
