"""App database schema: five tables, V2-ready, applied with create_all (TECHNICAL_PLAN §5)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {
        int: BigInteger,  # ids and FKs are bigint
        str: Text,
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


def _pk() -> Mapped[int]:
    return mapped_column(Identity(always=True), primary_key=True)


def _run_fk() -> Mapped[int]:
    return mapped_column(ForeignKey("reconciliation_run.id", ondelete="CASCADE"))


class Patient(Base):
    """FHIR patient snapshot; identifier is the stable key, fhir_patient_id the latest HAPI id."""

    __tablename__ = "patient"

    id: Mapped[int] = _pk()
    identifier: Mapped[str] = mapped_column(unique=True)
    fhir_base_url: Mapped[str]
    fhir_patient_id: Mapped[str]
    name: Mapped[str | None]
    birth_date: Mapped[date | None]
    gender: Mapped[str | None]
    fetched_at: Mapped[datetime]


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_run"
    __table_args__ = (Index("ix_run_patient_started", "patient_id", "started_at"),)

    id: Mapped[int] = _pk()
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="RESTRICT"))
    app_version: Mapped[str]
    started_at: Mapped[datetime]


class MedicationRecord(Base):
    """Per-run snapshot of one accepted record, so history shows exactly what was compared."""

    __tablename__ = "medication_record"
    __table_args__ = (UniqueConstraint("run_id", "source", "source_record_id"),)

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = _run_fk()
    source: Mapped[str]  # fhir | pharmacy, app-validated (no CHECK)
    source_record_id: Mapped[str]
    original_name: Mapped[str]
    normalized_name: Mapped[str | None]
    rxcui: Mapped[str | None]  # V2
    dose_amount: Mapped[Decimal]
    dose_unit: Mapped[str]
    frequency: Mapped[str | None]
    date_recorded: Mapped[date]
    raw: Mapped[dict[str, Any]]


class Finding(Base):
    __tablename__ = "finding"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = _run_fk()
    discrepancy_type: Mapped[str]  # open vocabulary: TEXT, no ENUM, no CHECK (rollback-safe)
    medication: Mapped[str]
    summary: Mapped[str]
    fhir_value: Mapped[str | None]
    pharmacy_value: Mapped[str | None]
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class RejectedRecord(Base):
    __tablename__ = "rejected_record"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = _run_fk()
    source: Mapped[str]
    source_record_id: Mapped[str | None]
    original_name: Mapped[str | None]
    raw: Mapped[dict[str, Any]]
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
