from typing import ClassVar

from contract import Finding, ReconciliationInput, format_dose
from rules.base import OTHER_SOURCE, SOURCE_LABELS, ReconciliationRule, by_name, identity


class MissingMedicationRule(ReconciliationRule):
    """A name present in one source and absent from the other; one finding per name.

    If the other source rejected a record with that name, the summary says so, so a rejection
    is never presented as a true omission.
    """

    discrepancy_type: ClassVar[str] = "missing"

    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        names = {"fhir": by_name(data.fhir), "pharmacy": by_name(data.pharmacy)}
        findings = []
        for present in ("fhir", "pharmacy"):
            absent = OTHER_SOURCE[present]
            for name, group in names[present].items():
                if name in names[absent]:
                    continue
                rejected = [r for r in data.rejected if r.source == absent and identity(r) == name]
                doses = "; ".join(format_dose(r.dose_amount, r.dose_unit) for r in group)
                findings.append(
                    Finding(
                        discrepancy_type=self.discrepancy_type,
                        medication=name,
                        summary=_summary(present, absent, len(rejected)),
                        fhir_value=doses if present == "fhir" else None,
                        pharmacy_value=doses if present == "pharmacy" else None,
                        details={
                            "missing_from": absent,
                            "rejected_count": len(rejected),
                            "rejected_record_ids": [r.source_record_id for r in rejected],
                        },
                    )
                )
        return findings


def _summary(present: str, absent: str, rejected: int) -> str:
    listed, other = SOURCE_LABELS[present], SOURCE_LABELS[absent]
    if not rejected:
        return f"Listed in {listed}; no {other} record."
    records, verb = ("record", "was") if rejected == 1 else ("records", "were")
    return (
        f"Listed in {listed}. No valid {other} record; {rejected} {other} {records} "
        f"with this name {verb} rejected (see Rejected records)."
    )
