from contract import Finding, ReconciliationInput
from rules.base import ReconciliationRule
from rules.dosage import DosageMismatchRule
from rules.duplicate import DuplicateMedicationRule
from rules.missing import MissingMedicationRule

DEFAULT_RULES: list[ReconciliationRule] = [
    DuplicateMedicationRule(),
    MissingMedicationRule(),
    DosageMismatchRule(),
]


def run_rules(
    data: ReconciliationInput, rules: list[ReconciliationRule] = DEFAULT_RULES
) -> list[Finding]:
    return [f for rule in rules for f in rule.evaluate(data)]
