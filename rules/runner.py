"""Default rule list and the runner the reconcile pipeline calls (TECHNICAL_PLAN §7)."""

from contract import Finding, ReconciliationInput
from rules.base import ReconciliationRule
from rules.dosage import DosageMismatchRule
from rules.duplicate import DuplicateMedicationRule
from rules.missing import MissingMedicationRule

# V1 rules in output order; V2 appends FrequencyMismatchRule here (B15).
DEFAULT_RULES: list[ReconciliationRule] = [
    DuplicateMedicationRule(),
    MissingMedicationRule(),
    DosageMismatchRule(),
]


def run_rules(
    data: ReconciliationInput, rules: list[ReconciliationRule] = DEFAULT_RULES
) -> list[Finding]:
    """Run each rule in order and concatenate their findings."""
    return [f for rule in rules for f in rule.evaluate(data)]
