"""ingest.aliases: a missing file, invalid JSON and a bad schema each give a distinct error."""

from pathlib import Path

import pytest

from contract import AliasConfigError
from ingest.aliases import load_aliases

REPO_CONFIG = Path(__file__).parents[2] / "data" / "aliases.json"


def write(tmp_path, text):
    path = tmp_path / "aliases.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_config_loads():
    cfg = load_aliases(REPO_CONFIG)
    assert cfg.aliases["zestril"] == "lisinopril"
    assert "oral" in cfg.ignore_tokens


def test_missing_file_is_named(tmp_path):
    with pytest.raises(AliasConfigError, match="not found") as err:
        load_aliases(tmp_path / "nope.json")
    assert "nope.json" in str(err.value)


def test_invalid_json_reports_line_and_column(tmp_path):
    path = write(tmp_path, '{\n  "version": 1,\n  "aliases": {,}\n}')
    with pytest.raises(AliasConfigError, match="not valid JSON") as err:
        load_aliases(path)
    assert "line 3 column" in str(err.value)


def test_bad_schema_names_the_field(tmp_path):
    path = write(tmp_path, '{"version": 2, "aliases": {"Zestril": "lisinopril"}}')
    with pytest.raises(AliasConfigError, match="invalid") as err:
        load_aliases(path)
    assert "version" in str(err.value)


def test_alias_rule_violation_is_reported(tmp_path):
    path = write(tmp_path, '{"version": 1, "aliases": {"a": "b", "b": "c"}}')
    with pytest.raises(AliasConfigError, match="chain"):
        load_aliases(path)


def test_json_that_is_not_an_object_is_rejected(tmp_path):
    with pytest.raises(AliasConfigError, match="invalid"):
        load_aliases(write(tmp_path, "[1, 2]"))
