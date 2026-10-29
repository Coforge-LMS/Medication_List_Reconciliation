import pytest
from pydantic import ValidationError

from contract import AliasConfig

VALID = {
    "version": 1,
    "aliases": {"zestril": "lisinopril", "metformin hydrochloride": "metformin"},
    "ignore_tokens": ["oral", "tablet"],
}


def test_valid_config():
    cfg = AliasConfig.model_validate(VALID)
    assert cfg.aliases["zestril"] == "lisinopril"


@pytest.mark.parametrize(
    "bad",
    [
        VALID | {"version": 2},
        VALID | {"aliases": {"Zestril": "lisinopril"}},
        VALID | {"aliases": {"zestril ": "lisinopril"}},
        VALID | {"aliases": {"zestril": ""}},
        VALID | {"aliases": {"prinivil": "zestril", "zestril": "lisinopril"}},
        VALID | {"ignore_tokens": ["Oral"]},
        VALID | {"unexpected": True},
        {"version": 1},
    ],
    ids=["version", "uppercase", "untrimmed", "empty", "chain", "token", "extra-key", "no-aliases"],
)
def test_malformed_config_is_rejected(bad):
    with pytest.raises(ValidationError):
        AliasConfig.model_validate(bad)
