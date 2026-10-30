"""Rule interface and helpers shared by every rule (TECHNICAL_PLAN §4.6, §7).

One ReconciliationInput holds one patient's accepted records, so rules group by name only.
"""

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import ClassVar

from contract import Finding, MedicationRecord, ReconciliationInput, Rejection, Source

# Display names used inside finding summaries.
SOURCE_LABELS: dict[Source, str] = {
    "intake": "patient-reported",
    "fhir": "FHIR",
    "pharmacy": "pharmacy",
}


class ReconciliationRule(ABC):
    """One discrepancy check; subclasses set discrepancy_type and implement evaluate."""

    discrepancy_type: ClassVar[str]

    @abstractmethod
    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        """Return this rule's findings for one patient's accepted records (empty if none)."""


def identity(item: MedicationRecord | Rejection) -> str | None:
    """Identity key: normalized_name, else the lowercased name (records arrive normalized)."""
    if item.normalized_name:
        return item.normalized_name
    return item.name.strip().lower() if item.name else None


def by_name(records: list[MedicationRecord]) -> dict[str, list[MedicationRecord]]:
    """Group records by identity key, sorted by name so findings come out in a stable order."""
    groups: dict[str, list[MedicationRecord]] = defaultdict(list)
    for rec in records:
        groups[identity(rec)].append(rec)
    return dict(sorted(groups.items()))


def participating(data: ReconciliationInput) -> dict[Source, list[MedicationRecord]]:
    """Sources that take part, in display order; intake only when an interview was recorded.

    intake=None (no interview) leaves intake out; intake=[] (patient reports none) keeps it.
    """
    sources: dict[Source, list[MedicationRecord]] = {}
    if data.intake is not None:
        sources["intake"] = data.intake
    sources["fhir"] = data.fhir
    sources["pharmacy"] = data.pharmacy
    return sources


def all_names(groups: dict[Source, dict[str, list[MedicationRecord]]]) -> list[str]:
    """Every name across sources: each source's names in order, then names new to the next."""
    return list(dict.fromkeys(name for by_source in groups.values() for name in by_source))


def sentence(text: str) -> str:
    """Capitalize the first letter only ('pharmacy' -> 'Pharmacy'), leaving the rest as is."""
    return text[:1].upper() + text[1:]
