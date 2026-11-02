"""Missing medication rule, with rejected-counterpart wording (TECHNICAL_PLAN §4.6, §16)."""

from typing import ClassVar

from contract import (
    Finding,
    MedicationRecord,
    ReconciliationInput,
    Rejection,
    Source,
    format_dose,
)
from rules.base import (
    SOURCE_LABELS,
    ReconciliationRule,
    all_names,
    by_name,
    concept_values,
    identity,
    participating,
    sentence,
)

# Pattern wording when intake takes part: what each source says about a name.
PRESENT_PHRASES: dict[Source, str] = {
    "intake": "reported by the patient",
    "fhir": "on the FHIR list",
    "pharmacy": "in pharmacy records",
}
ABSENT_PHRASES: dict[Source, str] = {
    "intake": "not reported by the patient",
    "fhir": "not on the FHIR list",
    "pharmacy": "not in pharmacy records",
}
NO_MEDICATIONS = " (patient reports no medications)"


class MissingMedicationRule(ReconciliationRule):
    """A name present in some participating sources and absent from others; one per name.

    If an absent source rejected a record with that name, the summary says so, so a rejection
    is never presented as a true omission. With no interview (intake is None) the output is the
    two-source form: missing_from is a single source and the summary keeps its original wording.

    Matching by ingredient puts different salts under one name, so a source that lists two salts
    is also compared salt by salt: tartrate and succinate on FHIR against tartrate alone in
    pharmacy reports succinate as missing.
    """

    discrepancy_type: ClassVar[str] = "missing"

    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        """Flag each name missing from a participating source; details name present and absent."""
        groups = {source: by_name(records) for source, records in participating(data).items()}
        # A rejected intake entry means the patient did name a drug, so "reports none" is false.
        reports_none = data.intake == [] and not any(r.source == "intake" for r in data.rejected)
        findings = []
        for name in all_names(groups):
            present = [s for s, g in groups.items() if name in g]
            absent = [s for s, g in groups.items() if name not in g]
            if absent:
                listed = {s: groups[s][name] for s in present}
                findings.append(self._finding(data, name, name, listed, absent, reports_none))
            findings += self._missing_salts(data, name, groups)
        return findings

    def _missing_salts(
        self,
        data: ReconciliationInput,
        name: str,
        groups: dict[Source, dict[str, list[MedicationRecord]]],
    ) -> list[Finding]:
        """One finding per salt that a source lacks, when some source lists 2+ salts of a drug.

        A source lacks a salt only if every record it has for the drug states a different one:
        a bare "Metoprolol" could be either salt. One salt on each side stays a dosage finding.
        """
        listed = {s: g[name] for s, g in groups.items() if name in g}
        salts = {s: concept_values(records, "salt") for s, records in listed.items()}
        if all(len(stated) < 2 for stated in salts.values()):
            return []
        findings = []
        for salt in sorted({value for stated in salts.values() for value in stated}):
            with_salt = {
                s: [r for r in records if concept_values([r], "salt") == [salt]]
                for s, records in listed.items()
                if salt in salts[s]
            }
            absent = [
                s
                for s, records in listed.items()
                if s not in with_salt and all(concept_values([r], "salt") for r in records)
            ]
            if absent:
                others = "; ".join(f"{SOURCE_LABELS[s]} {', '.join(salts[s])}" for s in absent)
                note = f" Same ingredient, other salt: {others}."
                findings.append(self._finding(data, salt, name, with_salt, absent, False, note))
        return findings

    def _finding(
        self,
        data: ReconciliationInput,
        medication: str,
        name: str,
        listed: dict[Source, list[MedicationRecord]],
        absent: list[Source],
        reports_none: bool,
        note: str = "",
    ) -> Finding:
        """A finding for medication; rejected records are matched on the drug's identity, name."""
        present = list(listed)
        rejected = [r for r in data.rejected if r.source in absent and identity(r) == name]
        if data.intake is None:
            (only,), (other,) = present, absent
            summary = _two_source_summary(only, other, len(rejected))
            where = {"missing_from": other}
        else:
            summary = _pattern_summary(present, absent, rejected, reports_none)
            where = {"present_in": present, "missing_from": absent}
        return Finding(
            discrepancy_type=self.discrepancy_type,
            medication=medication,
            summary=summary + note,
            **{
                f"{source}_value": "; ".join(format_dose(r.dose_amount, r.dose_unit) for r in group)
                for source, group in listed.items()
            },
            details={
                **where,
                "rejected_count": len(rejected),
                "rejected_record_ids": [r.source_record_id for r in rejected],
            },
        )


def _two_source_summary(present: Source, absent: Source, rejected: int) -> str:
    """Factual summary; mentions rejected records in the absent source when there are any."""
    listed, other = SOURCE_LABELS[present], SOURCE_LABELS[absent]
    if not rejected:
        return f"Listed in {listed}; no {other} record."
    return f"Listed in {listed}. No valid {other} record; {_rejected_clause(other, rejected)}."


def _pattern_summary(
    present: list[Source], absent: list[Source], rejected: list[Rejection], reports_none: bool
) -> str:
    """Names the pattern ('On the FHIR list; not reported by the patient ...'), then rejections.

    No source is presented as the truth: each is only said to have or lack the name.
    """
    missing = [
        ABSENT_PHRASES[s] + (NO_MEDICATIONS if s == "intake" and reports_none else "")
        for s in absent
    ]
    summary = sentence(" and ".join(PRESENT_PHRASES[s] for s in present))
    summary += "; " + " and ".join(missing) + "."
    counts = [(s, sum(r.source == s for r in rejected)) for s in absent]
    clauses = [_rejected_clause(SOURCE_LABELS[s], n) for s, n in counts if n]
    if clauses:
        summary += f" {sentence('; '.join(clauses))}."
    return summary


def _rejected_clause(label: str, rejected: int) -> str:
    """'1 pharmacy record with this name was rejected (see Rejected records)', or plural."""
    records, verb = ("record", "was") if rejected == 1 else ("records", "were")
    return f"{rejected} {label} {records} with this name {verb} rejected (see Rejected records)"
