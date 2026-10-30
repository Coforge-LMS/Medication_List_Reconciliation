"""Factories that build contract objects directly for rule tests."""

from datetime import date
from decimal import Decimal
from itertools import count

import pytest

from contract import MedicationRecord, Reason, ReconciliationInput, Rejection

_ids = count(1)


@pytest.fixture
def rec():
    """Factory for accepted MedicationRecords; normalized_name defaults to the lowercased name."""

    def make(source, name, dose="10", unit="mg", normalized_name=None):
        """Build one record with a unique source_record_id."""
        return MedicationRecord(
            patient_id="CASE-TEST",
            source=source,
            source_record_id=f"{source}-{next(_ids)}",
            name=name,
            dose_amount=Decimal(dose),
            dose_unit=unit,
            date_recorded=date(2026, 9, 15),
            normalized_name=normalized_name or name.lower(),
        )

    return make


@pytest.fixture
def rejected():
    """Factory for Rejections with an unreadable-dosage reason."""

    def make(source, name, normalized_name=None):
        """Build one rejection with a unique source_record_id."""
        return Rejection(
            source=source,
            source_record_id=f"{source}-rej-{next(_ids)}",
            name=name,
            normalized_name=normalized_name,
            raw={"dose_amount": "ten"},
            reasons=[Reason(field="dose_amount", code="unreadable_dosage", message="not a number")],
        )

    return make


@pytest.fixture
def data():
    """Factory for ReconciliationInput from iterables of records and rejections."""

    def make(fhir=(), pharmacy=(), rejected=(), intake=None):
        """Build one patient's reconciliation input; intake=None means no interview."""
        return ReconciliationInput(
            fhir=list(fhir),
            pharmacy=list(pharmacy),
            intake=None if intake is None else list(intake),
            rejected=list(rejected),
        )

    return make
