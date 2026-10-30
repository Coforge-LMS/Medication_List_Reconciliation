"""Read the baked-in synthetic pharmacy dataset.

Rows stay raw, string-valued dicts; ingest.pharmacy.validate turns them into records (B4).
"""

import json
import os
from collections import defaultdict
from functools import cache
from pathlib import Path


class PharmacyDataError(ValueError):
    """The dataset file exists but isn't a JSON list of rows."""


def rows_for(patient_id: str, path: Path | str | None = None) -> list[dict[str, str]]:
    """This patient's raw rows in file order; [] when the patient has none."""
    default = Path(__file__).resolve().parents[1] / "data" / "pharmacy" / "pharmacy_records.json"
    dataset = Path(path or os.environ.get("PHARMACY_DATA") or default)
    return list(_by_patient(dataset).get(patient_id, []))


@cache
def _by_patient(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load the dataset once per path and group its rows by patient_id."""
    if not path.is_file():
        raise FileNotFoundError(
            f"pharmacy dataset not found at {path} "
            "(generate it with data/generators/make_pharmacy.py)"
        )
    try:
        rows = json.loads(path.read_text())
    except ValueError as exc:
        raise PharmacyDataError(f"pharmacy dataset {path} is not valid JSON: {exc}") from exc
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise PharmacyDataError(f"pharmacy dataset {path} is not a JSON list of rows")
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row.get("patient_id")].append(row)
    return dict(groups)
