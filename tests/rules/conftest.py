"""Factories that build contract objects directly for rule tests."""

from datetime import date
from decimal import Decimal
from itertools import count

import pytest

from contract import MedicationRecord, Reason, ReconciliationInput, Rejection

_ids = count(1)


@pytest.fixture
def rec():
    def make(source, name, dose="10", unit="mg", normalized_name=None):
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
    def make(source, name, normalized_name=None):
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
    def make(fhir=(), pharmacy=(), rejected=()):
        return ReconciliationInput(
            fhir=list(fhir), pharmacy=list(pharmacy), rejected=list(rejected)
        )

    return make
