"""Display text shared by pages and the PDF.

Unknown finding types render as "Other (x)" so an older release can still show findings
written by a newer one (TECHNICAL_PLAN §5, tolerant reader).
"""

DISCLAIMER = (
    "Synthetic data. Reports discrepancies between sources for clinician review; "
    "does not recommend treatment."
)

LABELS: dict[str, str] = {
    "duplicate": "Duplicate medication",
    "missing": "Missing medication",
    "dosage_mismatch": "Dosage mismatch",
}


def label_for(discrepancy_type: str) -> str:
    return LABELS.get(discrepancy_type, f"Other ({discrepancy_type})")
