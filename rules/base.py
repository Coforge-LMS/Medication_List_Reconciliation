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


def concept_values(records: list[MedicationRecord], field: str) -> list[str]:
    """Distinct values RxNorm's concept states for these records, sorted; unknowns are left out."""
    values = set()
    for record in records:
        concept = record.raw.get("rxnorm")
        value = concept.get(field) if isinstance(concept, dict) else None
        if value:
            values.add(value)
    return sorted(values)


def differing_concept(present: dict[Source, list[MedicationRecord]], field: str) -> dict[str, str]:
    """{source: value} for a concept field, if the sources stating one disagree; else empty.

    A vaguer value agrees with a fuller one it begins: "Extended Release" from a name like
    "Metformin ER" doesn't conflict with "Extended Release Oral Tablet".
    """
    stated = {source: concept_values(group, field) for source, group in present.items()}
    stated = {source: values for source, values in stated.items() if values}
    every = {value for values in stated.values() for value in values}

    def fullest(value: str) -> str:
        """The fuller value this one begins, if any source states one."""
        return next((other for other in sorted(every) if other.startswith(f"{value} ")), value)

    if len({frozenset(map(fullest, values)) for values in stated.values()}) < 2:
        return {}
    return {source: ", ".join(values) for source, values in stated.items()}


def with_product_differences(summary: str, forms: dict[str, str], salts: dict[str, str]) -> str:
    """The summary, led by any form or salt difference, as ingredient matching may group products.

    'Different form: FHIR Oral Tablet; pharmacy Extended Release Oral Tablet. FHIR dose ...'
    """
    for label, differing in (("salt", salts), ("form", forms)):
        if differing:
            listed = "; ".join(f"{SOURCE_LABELS[s]} {value}" for s, value in differing.items())
            summary = f"Different {label}: {listed}. {summary}"
    return summary
