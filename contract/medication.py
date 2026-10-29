"""Shared medication record contract (TECHNICAL_PLAN §4.1, §4.5). Frozen after B1."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contract.units import Unit

Source = Literal["fhir", "pharmacy", "intake"]
ReasonCode = Literal["missing_field", "unreadable_dosage", "invalid_date", "future_date"]


class MedicationRecord(BaseModel):
    """One accepted medication from any source; dose is per administration."""

    model_config = ConfigDict(frozen=True)

    patient_id: str = Field(min_length=1)  # stable identifier, never the HAPI id
    source: Source
    source_record_id: str = Field(min_length=1)
    name: str = Field(min_length=1)  # original name, verbatim
    dose_amount: Decimal = Field(gt=0)
    dose_unit: Unit
    frequency: str | None = None  # as given by the source; V1 stores, never compares
    date_recorded: date
    normalized_name: str | None = None  # identity key, set by the normalize step
    rxcui: str | None = None  # V2 only
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @field_validator("date_recorded")
    @classmethod
    def _not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("date_recorded is in the future")
        return value


class Reason(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    code: ReasonCode
    message: str


class Rejection(BaseModel):
    """An invalid record, kept with its reasons; the name is kept when readable."""

    model_config = ConfigDict(frozen=True)

    source: Source
    source_record_id: str | None = None
    name: str | None = None
    normalized_name: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)
    reasons: list[Reason] = Field(min_length=1)
