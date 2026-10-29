"""App version, read from pyproject.toml (baked into the image), so tags and images agree."""

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
__version__: str = tomllib.loads(_PYPROJECT.read_text())["project"]["version"]
