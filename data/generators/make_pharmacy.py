"""Seeded pharmacy dataset: python -m data.generators.make_pharmacy --seed 42 (from the repo root).

Writes data/pharmacy/pharmacy_records.json, a JSON array of flat rows with string values:
record_id, patient_id, medication_name, dose_amount, dose_unit, frequency, date_recorded.
dose_amount is per administration, as dispensed.

Synthea patients get seeded perturbations of the FHIR medications that pass ingest validation, so
every row is valid. The three case patients get scripted rows, plus the invalid rows the
validation rules must reject (data/README.md lists what each case is expected to produce).
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from contract import MedicationRecord
from data.generators.common import (
    END_DATE,
    FUTURE_DATE,
    PHARMACY_FILE,
    PHARMACY_FREQUENCY,
    alternates,
    display_name,
    drugs_by_key,
    fmt,
    load_config,
    load_synthea,
    patient_rng,
    recent_date,
)

FIELDS = (
    "record_id",
    "patient_id",
    "medication_name",
    "dose_amount",
    "dose_unit",
    "frequency",
    "date_recorded",
)

# What can happen to one FHIR medication on its way to the pharmacy record, with its weight.
SCENARIOS = {
    "keep": 45,
    "brand": 15,  # written under a name the alias list knows (Zestril for lisinopril)
    "unit_equivalence": 8,  # 500 mg written as 0.5 g: equal, not a mismatch
    "frequency": 8,  # frequency text differs from the FHIR one
    "dose_change": 10,  # twice or half the dose
    "drop": 8,  # never reached the pharmacy record
    "duplicate": 10,  # two rows for the same drug
}
# Drugs a pharmacy might hold that the hospital list doesn't (mg only: no mL rows).
PHARMACY_ONLY = (
    ("Omeprazole", "20", "mg", "once daily"),
    ("Cetirizine", "10", "mg", "once daily"),
    ("Loratadine", "10", "mg", "once daily"),
    ("Pantoprazole", "40", "mg", "once daily"),
)

# Scripted rows for the case patients: (patient, name, dose, unit, frequency, date).
CASE_ROWS = (
    # CASE-CLEAN: the alias match (Zestril) and nothing else
    ("CASE-CLEAN", "Zestril", "10", "mg", "once daily", "2026-03-02"),
    ("CASE-CLEAN", "Atorvastatin", "20", "mg", "once daily", "2026-03-02"),
    ("CASE-CLEAN", "Amlodipine", "5", "mg", "once daily", "2026-03-02"),
    # CASE-MIXED
    ("CASE-MIXED", "Metformin Hydrochloride", "500", "mg", "twice daily", "2026-02-12"),
    ("CASE-MIXED", "Acetaminophen", "500", "mg", "twice daily", "2026-02-12"),
    ("CASE-MIXED", "Acetaminophen", "1000", "mg", "twice daily", "2026-02-19"),  # duplicate + dose
    ("CASE-MIXED", "Sertraline", "50", "mg", "twice daily", "2026-02-12"),  # FHIR says once daily
    ("CASE-MIXED", "Omeprazole", "20", "mg", "once daily", "2026-02-12"),  # not on the FHIR list
    # no metoprolol row: on the FHIR list, absent here
    ("CASE-MIXED", "Warfarin Sodium", "ten", "mg", "once daily", "2026-02-12"),  # only row invalid
    ("CASE-MIXED", "", "5", "mg", "once daily", "2026-02-12"),  # blank name
    (
        "CASE-MIXED",
        "Pravastatin",
        "40",
        "tab",
        "once daily",
        "2026-02-12",
    ),  # unit outside mg/g/mcg/mL
    ("CASE-MIXED", "Tamsulosin", "0.4", "mg", "once daily", "03/02/2026"),  # not an ISO date
    ("CASE-MIXED", "Famotidine", "20", "mg", "twice daily", FUTURE_DATE),  # future date
    # CASE-BRAND: a brand outside the alias list
    ("CASE-BRAND", "Crestor", "10", "mg", "once daily", "2026-01-20"),
)


@dataclass
class Plan:
    """One FHIR medication and what happens to it on its way to the pharmacy record."""

    patient: str
    key: str
    record: MedicationRecord
    kind: str


def build(seed: int = 42) -> tuple[list[dict[str, str]], Counter]:
    """Every row (record_id assigned in order) and a count of the scenarios applied."""
    config = load_config()
    brands = alternates(config)
    synthea = load_synthea(config)

    plans = []
    for identifier, records in synthea.items():
        rng = patient_rng(seed, identifier, "plan")
        for key, record in drugs_by_key(records).items():
            kind = rng.choices(list(SCENARIOS), weights=list(SCENARIOS.values()))[0]
            plans.append(
                Plan(identifier, key, record, kind if _can(kind, key, record, brands) else "keep")
            )
    _cover_every_scenario(plans, brands)

    rows: list[dict[str, str]] = []
    scenarios: Counter = Counter(plan.kind for plan in plans)
    for identifier, records in synthea.items():
        rng = patient_rng(seed, identifier, "pharmacy")
        for plan in (p for p in plans if p.patient == identifier):
            rows += _rows_for(plan, rng, brands)
        drugs = drugs_by_key(records)
        extras = [d for d in PHARMACY_ONLY if d[0].lower() not in drugs]
        if extras and rng.random() < 0.5:
            name, dose, unit, frequency = rng.choice(extras)
            recorded = recent_date(rng, 60).isoformat()
            rows.append(_row(identifier, name, dose, unit, frequency, recorded))
            scenarios["pharmacy_only"] += 1
    if not scenarios["pharmacy_only"]:  # keep the scenario guaranteed, whatever the seed
        identifier = next(iter(synthea))
        name, dose, unit, frequency = PHARMACY_ONLY[0]
        rows.append(_row(identifier, name, dose, unit, frequency, END_DATE.isoformat()))
        scenarios["pharmacy_only"] += 1

    for patient, name, dose, unit, frequency, recorded in CASE_ROWS:
        rows.append(_row(patient, name, dose, unit, frequency, recorded))
    scenarios["case_rows"] = len(CASE_ROWS)

    for number, row in enumerate(rows, start=1):
        row["record_id"] = f"PH-{number:04d}"
    return [{field: row[field] for field in FIELDS} for row in rows], scenarios


def render(rows: list[dict[str, str]]) -> str:
    """The exact file text: stable key order, two-space indent, one trailing newline."""
    return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"


def _row(patient: str, name: str, dose: str, unit: str, frequency: str, recorded: str) -> dict:
    return {
        "record_id": "",
        "patient_id": patient,
        "medication_name": name,
        "dose_amount": dose,
        "dose_unit": unit,
        "frequency": frequency,
        "date_recorded": recorded,
    }


def _can(kind: str, key: str, record: MedicationRecord, brands: dict) -> bool:
    """Whether this medication can show the scenario (a brand needs an alias, and so on)."""
    if kind == "brand":
        return key in brands
    if kind == "unit_equivalence":
        return record.dose_unit == "mg" and record.dose_amount >= 100
    if kind == "frequency":
        return (record.frequency or "") in PHARMACY_FREQUENCY
    return True


def _cover_every_scenario(plans: list[Plan], brands: dict) -> None:
    """Force any scenario the random draw missed onto the first medication that can show it."""
    for kind in SCENARIOS:
        if any(p.kind == kind for p in plans):
            continue
        target = next(
            (p for p in plans if p.kind == "keep" and _can(kind, p.key, p.record, brands)), None
        )
        if target is None:
            raise ValueError(f"no Synthea medication can show the {kind!r} scenario")
        target.kind = kind


def _rows_for(plan: Plan, rng, brands: dict) -> list[dict[str, str]]:
    """The pharmacy rows (zero, one or two) for one FHIR medication."""
    record, kind = plan.record, plan.kind
    fhir_frequency = PHARMACY_FREQUENCY.get(record.frequency or "")
    frequency = fhir_frequency or rng.choice(("once daily", "twice daily", ""))
    amount, unit, name = record.dose_amount, record.dose_unit, display_name(plan.key)
    recorded = recent_date(rng, 60).isoformat()

    if kind == "drop":
        return []
    if kind == "brand":
        name = display_name(rng.choice(brands[plan.key]))
    elif kind == "unit_equivalence":
        amount, unit = amount / 1000, "g"
    elif kind == "frequency":
        frequency = rng.choice(sorted(set(PHARMACY_FREQUENCY.values()) - {fhir_frequency}))
    elif kind == "dose_change":
        amount = amount * rng.choice((Decimal(2), Decimal("0.5")))

    rows = [_row(plan.patient, name, fmt(amount), unit, frequency, recorded)]
    if kind == "duplicate":
        again = display_name(rng.choice(brands[plan.key])) if plan.key in brands else name
        extra = amount * rng.choice((Decimal(1), Decimal(2)))
        rows.append(_row(plan.patient, again, fmt(extra), unit, frequency, recorded))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m data.generators.make_pharmacy")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=PHARMACY_FILE)
    args = parser.parse_args(argv)
    rows, scenarios = build(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(rows), encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {args.out}: {dict(sorted(scenarios.items()))}")


if __name__ == "__main__":
    main()
