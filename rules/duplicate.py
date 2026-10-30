"""Duplicate medication rule (TECHNICAL_PLAN §4.6)."""

from typing import ClassVar

from contract import Finding, ReconciliationInput, format_dose
from rules.base import SOURCE_LABELS, ReconciliationRule, by_name, participating, sentence


class DuplicateMedicationRule(ReconciliationRule):
    """2+ records with the same name within one source (any dose); one per (source, name)."""

    discrepancy_type: ClassVar[str] = "duplicate"

    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        """Flag each (source, name) with 2+ records, intake included when it takes part."""
        findings = []
        for source, records in participating(data).items():
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
                        **{f"{source}_value": listed},
                        details={
                            "source": source,
                            "count": len(group),
                            "source_record_ids": [r.source_record_id for r in group],
                        },
                    )
                )
        return findings
