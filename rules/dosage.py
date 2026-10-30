"""Dosage mismatch rule (TECHNICAL_PLAN §4.2, §4.6, §16)."""

from typing import ClassVar

from contract import Finding, MedicationRecord, ReconciliationInput, format_dose, to_base
from rules.base import (
    SOURCE_LABELS,
    ReconciliationRule,
    all_names,
    by_name,
    participating,
    sentence,
)


class DosageMismatchRule(ReconciliationRule):
    """A name in 2+ sources whose sets of base-unit doses differ (500 mg == 0.5 g)."""

    discrepancy_type: ClassVar[str] = "dosage_mismatch"

    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        """Flag names in 2+ sources whose dose sets differ; mg vs mL is a different measure."""
        groups = {source: by_name(records) for source, records in participating(data).items()}
        findings = []
        for name in all_names(groups):
            present = {source: g[name] for source, g in groups.items() if name in g}
            if len(present) < 2:
                continue
            base = {source: _base_doses(group) for source, group in present.items()}
            if len({frozenset(doses) for doses in base.values()}) == 1:
                continue
            values = {source: _listed(group) for source, group in present.items()}
            different_measure = len({frozenset(u for _, u in d) for d in base.values()}) > 1
            summary = sentence(
                "; ".join(f"{SOURCE_LABELS[s]} dose {value}" for s, value in values.items()) + "."
            )
            if different_measure:
                summary = f"Doses are recorded in a different measure: {summary}"
            findings.append(
                Finding(
                    discrepancy_type=self.discrepancy_type,
                    medication=name,
                    summary=summary,
                    **{f"{source}_value": value for source, value in values.items()},
                    details={
                        **{f"{s}_doses_base": _sorted_base(doses) for s, doses in base.items()},
                        "different_measure": different_measure,
                    },
                )
            )
        return findings


def _base_doses(records: list[MedicationRecord]) -> set[tuple]:
    """Distinct doses converted to mg or mL, so equivalent doses compare equal."""
    return {to_base(r.dose_amount, r.dose_unit) for r in records}


def _sorted_base(doses: set[tuple]) -> list[str]:
    """Base-unit doses as display strings, sorted by unit then amount."""
    return [format_dose(amount, unit) for amount, unit in sorted(doses, key=lambda d: (d[1], d[0]))]


def _listed(records: list[MedicationRecord]) -> str:
    """Doses as given, deduplicated in first-seen order."""
    return ", ".join(dict.fromkeys(format_dose(r.dose_amount, r.dose_unit) for r in records))
