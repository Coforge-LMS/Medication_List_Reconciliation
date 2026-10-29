"""What rules receive and return (TECHNICAL_PLAN §4.6, §7)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contract.medication import MedicationRecord, Rejection


class Finding(BaseModel):
    """One discrepancy. discrepancy_type is an open vocabulary (rollback-safe), never an enum."""

    model_config = ConfigDict(frozen=True)

    discrepancy_type: str = Field(min_length=1)
    medication: str
    summary: str  # factual sentence; never a treatment recommendation
    fhir_value: str | None = None
    pharmacy_value: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ReconciliationInput(BaseModel):
    """Everything one run compares: accepted records per source plus rejections."""

    model_config = ConfigDict(frozen=True)

    fhir: list[MedicationRecord]
    pharmacy: list[MedicationRecord]
    rejected: list[Rejection] = Field(default_factory=list)
