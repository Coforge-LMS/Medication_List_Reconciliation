"""Alias config schema (TECHNICAL_PLAN §4.4). Loading lives in ingest/aliases.py."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class AliasConfigError(Exception):
    """The alias config is missing or malformed; the app must not start."""


def _check_token(kind: str, value: str) -> None:
    if not value or value != value.strip().lower():
        raise ValueError(f"{kind} {value!r} must be non-empty, lowercase and trimmed")


class AliasConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    aliases: dict[str, str]
    ignore_tokens: list[str] = []

    @model_validator(mode="after")
    def _check(self) -> "AliasConfig":
        for key, value in self.aliases.items():
            _check_token("alias key", key)
            _check_token("alias value", value)
            if value in self.aliases:
                raise ValueError(f"alias chain not allowed: {key!r} -> {value!r}")
        for token in self.ignore_tokens:
            _check_token("ignore token", token)
        return self
