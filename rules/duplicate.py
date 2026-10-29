"""Duplicate medication rule (TECHNICAL_PLAN §4.6)."""

from typing import ClassVar

from contract import Finding, ReconciliationInput, format_dose
from rules.base import SOURCE_LABELS, ReconciliationRule, by_name, sentence


class DuplicateMedicationRule(ReconciliationRule):
    """2+ records with the same name within one source (any dose); one per (source, name)."""

    discrepancy_type: ClassVar[str] = "duplicate"

    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        """Flag each (source, name) with 2+ records; source names and doses go in the value."""
        findings = []
        for source, records in (("fhir", data.fhir), ("pharmacy", data.pharmacy)):
            for name, group in by_name(records).items():
                if len(group) < 2:
                    continue
                listed = "; ".join(
                    f"{r.name} {format_dose(r.dose_amount, r.dose_unit)}" for r in group
                )
                findings.append(
                    Finding(
                        discrepancy_type=self.discrepancy_type,
                        medication=name,
                        summary=f"{sentence(SOURCE_LABELS[source])} has {len(group)} records "
                        f"for {name}.",
                        fhir_value=listed if source == "fhir" else None,
                        pharmacy_value=listed if source == "pharmacy" else None,
                        details={
                            "source": source,
                            "count": len(group),
                            "source_record_ids": [r.source_record_id for r in group],
                        },
                    )
                )
        return findings
