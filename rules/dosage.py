from typing import ClassVar

from contract import Finding, MedicationRecord, ReconciliationInput, format_dose, to_base
from rules.base import ReconciliationRule, by_name


class DosageMismatchRule(ReconciliationRule):
    """A name present in both sources whose sets of base-unit doses differ (500 mg == 0.5 g)."""

    discrepancy_type: ClassVar[str] = "dosage_mismatch"

    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        pharmacy = by_name(data.pharmacy)
        findings = []
        for name, fhir_group in by_name(data.fhir).items():
            pharmacy_group = pharmacy.get(name)
            if not pharmacy_group:
                continue
            fhir_base, pharmacy_base = _base_doses(fhir_group), _base_doses(pharmacy_group)
            if fhir_base == pharmacy_base:
                continue
            fhir_value, pharmacy_value = _listed(fhir_group), _listed(pharmacy_group)
            different_measure = {u for _, u in fhir_base} != {u for _, u in pharmacy_base}
            summary = f"FHIR dose {fhir_value}; pharmacy dose {pharmacy_value}."
            if different_measure:
                summary = f"Doses are recorded in a different measure: {summary}"
            findings.append(
                Finding(
                    discrepancy_type=self.discrepancy_type,
                    medication=name,
                    summary=summary,
                    fhir_value=fhir_value,
                    pharmacy_value=pharmacy_value,
                    details={
                        "fhir_doses_base": _sorted_base(fhir_base),
                        "pharmacy_doses_base": _sorted_base(pharmacy_base),
                        "different_measure": different_measure,
                    },
                )
            )
        return findings


def _base_doses(records: list[MedicationRecord]) -> set[tuple]:
    return {to_base(r.dose_amount, r.dose_unit) for r in records}


def _sorted_base(doses: set[tuple]) -> list[str]:
    return [format_dose(amount, unit) for amount, unit in sorted(doses, key=lambda d: (d[1], d[0]))]


def _listed(records: list[MedicationRecord]) -> str:
    """Doses as given, deduplicated in first-seen order."""
    return ", ".join(dict.fromkeys(format_dose(r.dose_amount, r.dose_unit) for r in records))
