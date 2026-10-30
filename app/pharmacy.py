"""Read the baked-in synthetic pharmacy dataset (TECHNICAL_PLAN §3, §7.1 step 3).

Rows stay raw, string-valued dicts; ingest.pharmacy.validate turns them into records (B4).
"""

import json
import os
from collections import defaultdict
from functools import cache
from pathlib import Path

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "pharmacy" / "pharmacy_records.json"
)


def rows_for(patient_id: str, path: Path | str | None = None) -> list[dict[str, str]]:
    """This patient's raw rows in file order; [] when the patient has none."""
    dataset = Path(path or os.environ.get("PHARMACY_DATA", DEFAULT_PATH))
    return list(_by_patient(dataset).get(patient_id, []))


@cache
def _by_patient(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load the dataset once per path and group its rows by patient_id."""
    if not path.is_file():
        raise FileNotFoundError(
            f"pharmacy dataset not found at {path} "
            "(generate it with data/generators/make_pharmacy.py)"
        )
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in json.loads(path.read_text()):
        groups[row.get("patient_id")].append(row)
    return dict(groups)
