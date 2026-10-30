"""Load the alias config (TECHNICAL_PLAN §4.4); any problem is an AliasConfigError."""

import json
from pathlib import Path

from pydantic import ValidationError

from contract import AliasConfig, AliasConfigError


def load_aliases(path: str | Path) -> AliasConfig:
    """Read and validate data/aliases.json. The app refuses to start on AliasConfigError."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AliasConfigError(f"alias config not found: {path}") from None
    except OSError as exc:
        raise AliasConfigError(f"cannot read alias config {path}: {exc.strerror}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AliasConfigError(
            f"alias config {path} is not valid JSON: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}"
        ) from exc
    try:
        return AliasConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or 'config'}: {err['msg']}"
            for err in exc.errors()
        )
        raise AliasConfigError(f"alias config {path} is invalid: {problems}") from exc
