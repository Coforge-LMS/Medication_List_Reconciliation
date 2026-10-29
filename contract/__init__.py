"""Shared medication contract: the single source of truth for every module (TECHNICAL_PLAN §4)."""

from contract.aliases import AliasConfig, AliasConfigError
from contract.findings import Finding, ReconciliationInput
from contract.medication import MedicationRecord, Reason, Rejection, Source
from contract.runs import PatientInfo, RunDetail, RunSummary
from contract.units import Unit, format_dose, normalize_unit, to_base

__all__ = [
    "AliasConfig",
    "AliasConfigError",
    "Finding",
    "MedicationRecord",
    "PatientInfo",
    "Reason",
    "ReconciliationInput",
    "Rejection",
    "RunDetail",
    "RunSummary",
    "Source",
    "Unit",
    "format_dose",
    "normalize_unit",
    "to_base",
]
