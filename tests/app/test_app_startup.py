"""App startup: the alias config is checked before the app serves anything."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from contract import AliasConfigError


def test_bad_alias_config_stops_startup(tmp_path, monkeypatch):
    """Invalid JSON at ALIASES_PATH makes startup raise AliasConfigError with the reason."""
    bad = tmp_path / "aliases.json"
    bad.write_text("{not json")
    monkeypatch.setenv("ALIASES_PATH", str(bad))
    with pytest.raises(AliasConfigError, match="not valid JSON"):
        with TestClient(app):
            pass


def test_missing_alias_config_stops_startup(tmp_path, monkeypatch):
    """A missing file is named in the error."""
    monkeypatch.setenv("ALIASES_PATH", str(tmp_path / "nope.json"))
    with pytest.raises(AliasConfigError, match="nope.json"):
        with TestClient(app):
            pass


def test_shipped_alias_config_starts(client):
    """The committed data/aliases.json loads and the app serves /healthz."""
    assert client.get("/healthz").status_code == 200
