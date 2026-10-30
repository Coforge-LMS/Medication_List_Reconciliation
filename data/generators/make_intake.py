"""Seeded patient intake history: python -m data.generators.make_intake --seed 42 (repo root).

Writes data/intake/intake_interviews.csv and intake_medications.csv, the files db.seed loads.
Values are raw strings, as the patient said them; validation happens at run time (ingest).

Synthea patients: most are interviewed, with seeded patient-report patterns (a brand name, one
OTC drug, a prescribed drug not reported, a dose difference, a "not sure" dose). One patient says
they take nothing (no_medications) and one has no interview at all. The case patients get
scripted interviews (data/README.md lists what each is expected to produce).
"""

import argparse
import csv
import io
from collections import Counter
from decimal import Decimal
from pathlib import Path

from data.generators.common import (
    INTAKE_DIR,
    PATIENT_FREQUENCY,
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

INTERVIEW_FIELDS = (
    "interview_ref",
    "patient_identifier",
    "taken_at",
    "taken_by",
    "informant",
    "no_medications",
)
MEDICATION_FIELDS = (
    "interview_ref",
    "record_id",
    "medication_name",
    "dose_amount",
    "dose_unit",
    "frequency",
)
NURSES = ("RN Okafor", "RN Alvarez", "RN Nguyen", "RN Haddad")
# Over-the-counter drugs and supplements a patient mentions that no other source holds (mg only).
OTC = (
    ("Ibuprofen", "200", "mg", "as needed"),
    ("Melatonin", "3", "mg", "at bedtime"),
    ("Fish Oil", "1000", "mg", "once a day"),
    ("Loratadine", "10", "mg", "once a day"),
    ("Magnesium", "250", "mg", "once a day"),
)
OTC_NAMES = tuple(name for name, *_ in OTC)
PATTERNS = ("not_reported", "dose_difference", "unsure", "brand", "otc")

CASE_TAKEN_AT = "2026-10-28T14:00:00+00:00"
# Scripted interviews: patient -> rows of (name, dose, unit, frequency).
CASE_INTERVIEWS = {
    "CASE-CLEAN": (
        ("Zestril", "10", "mg", "once a day"),
        ("Atorvastatin", "20", "mg", "once a day"),
        ("Norvasc", "5", "mg", "once a day"),
    ),
    "CASE-MIXED": (
        ("Metformin", "0.5", "g", "twice a day"),  # 500 mg == 0.5 g: no finding
        ("Acetaminophen", "1000", "mg", "twice a day"),  # dose differs from FHIR
        ("Sertraline", "50", "mg", "once a day"),
        ("Sertraline", "50", "mg", "at bedtime"),  # listed twice: duplicate in intake
        ("Warfarin", "not sure", "", ""),  # unreadable: rejected, counterparts named
        ("Ibuprofen", "200", "mg", "as needed"),  # intake only
        # no metoprolol: on the FHIR list, not reported
    ),
    "CASE-BRAND": (("Crestor", "10", "mg", "once a day"),),
}


def build(seed: int = 42):
    """(interview rows, medication rows, count of patterns applied), in a fixed order."""
    config = load_config()
    brands = alternates(config)
    synthea = load_synthea(config)
    identifiers = list(synthea)
    no_interview, takes_nothing = patient_rng(seed, "all", "roles").sample(identifiers, 2)

    interviews: list[dict[str, str]] = []
    medications: list[dict[str, str]] = []
    patterns: Counter = Counter({"no_interview": 1, "no_medications": 1})

    for identifier, records in synthea.items():
        if identifier == no_interview:
            continue
        rng = patient_rng(seed, identifier, "intake")
        ref = f"INT-{identifier[:8]}"
        taken = recent_date(rng, 14)
        hour, minute = (
            rng.randint(9, 16),
            rng.choice((0, 15, 30, 45)),
        )  # mid-day UTC: same local date
        interviews.append(
            {
                "interview_ref": ref,
                "patient_identifier": identifier,
                "taken_at": f"{taken.isoformat()}T{hour:02d}:{minute:02d}:00+00:00",
                "taken_by": rng.choice(NURSES),
                "informant": "caregiver" if rng.random() < 0.15 else "patient",
                "no_medications": "true" if identifier == takes_nothing else "false",
            }
        )
        if identifier == takes_nothing:
            continue
        rows = _report(records, rng, brands, patterns)
        for number, (name, dose, unit, frequency) in enumerate(rows, start=1):
            medications.append(_med(ref, number, name, dose, unit, frequency))

    for patient, rows in CASE_INTERVIEWS.items():
        ref = f"INT-{patient}"
        interviews.append(
            {
                "interview_ref": ref,
                "patient_identifier": patient,
                "taken_at": CASE_TAKEN_AT,
                "taken_by": NURSES[0],
                "informant": "patient",
                "no_medications": "false",
            }
        )
        for number, row in enumerate(rows, start=1):
            medications.append(_med(ref, number, *row))
    patterns["case_interviews"] = len(CASE_INTERVIEWS)

    missing = [p for p in PATTERNS if not patterns[p]]
    if missing:
        raise ValueError(f"no Synthea patient shows the intake pattern(s) {missing}")
    return interviews, medications, patterns


def render(rows: list[dict[str, str]], fields: tuple[str, ...]) -> str:
    """CSV text with a header, \\n line endings and stable column order."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _med(ref: str, number: int, name: str, dose: str, unit: str, frequency: str) -> dict[str, str]:
    return {
        "interview_ref": ref,
        "record_id": f"{ref}-{number:02d}",
        "medication_name": name,
        "dose_amount": dose,
        "dose_unit": unit,
        "frequency": frequency,
    }


def _report(records, rng, brands, patterns) -> list[tuple[str, str, str, str]]:
    """What one patient says they take: their FHIR medications with report patterns, plus OTC."""
    drugs = drugs_by_key(records)
    order = list(drugs)
    rng.shuffle(order)
    # Patterns need spare drugs: one always stays plain so the interview isn't all exceptions.
    special = {}
    if len(order) >= 2:
        special[order[0]] = "not_reported"
    if len(order) >= 3:
        special[order[1]] = "dose_difference"
    if len(order) >= 4:
        special[order[2]] = "unsure"
    branded = next((k for k in drugs if k not in special and k in brands), None)

    rows = []
    for key, record in drugs.items():
        pattern = special.get(key)
        patterns[pattern or "plain"] += 1
        if pattern == "not_reported":
            continue
        name, amount = display_name(key), record.dose_amount
        said = PHARMACY_FREQUENCY.get(record.frequency or "")
        frequency = PATIENT_FREQUENCY.get(said or "", rng.choice(("once a day", "")))
        if pattern == "unsure":
            rows.append((name, "not sure", "", ""))
            continue
        if pattern == "dose_difference":
            amount = amount * rng.choice((Decimal(2), Decimal("0.5")))
        if key == branded:
            name = display_name(rng.choice(brands[key]))
            patterns["brand"] += 1
        rows.append((name, fmt(amount), record.dose_unit, frequency))

    others = [o for o in OTC if o[0].lower() not in drugs]
    rows.append(rng.choice(others))
    patterns["otc"] += 1
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m data.generators.make_intake")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=INTAKE_DIR, help="folder for the two CSVs")
    args = parser.parse_args(argv)
    interviews, medications, patterns = build(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "intake_interviews.csv").write_text(
        render(interviews, INTERVIEW_FIELDS), encoding="utf-8", newline=""
    )
    (args.out / "intake_medications.csv").write_text(
        render(medications, MEDICATION_FIELDS), encoding="utf-8", newline=""
    )
    print(
        f"Wrote {len(interviews)} interviews and {len(medications)} medication rows to "
        f"{args.out}: {dict(sorted(patterns.items()))}"
    )


if __name__ == "__main__":
    main()
