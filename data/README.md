# data/

Synthetic data only. No real patient information.

## FHIR (`data/fhir/`)

| Path | What | Source |
|---|---|---|
| `fhir/synthea/` | `hospitalInformation*`, `practitionerInformation*` and 10 patient transaction bundles | Synthea v4.0.0, seed 42, generated once and committed |
| `fhir/cases/medrec-cases.json` | Deliberate-case transaction bundle: CASE-CLEAN, CASE-MIXED, CASE-BRAND (identifier system `urn:medrec:case`) | hand-designed |

### Regenerating `fhir/synthea/`

Run from the repo root. The jar is not committed (`tools/` is gitignored).

```bash
mkdir -p tools/synthea/cache tools/synthea/out
curl -fL -o tools/synthea/cache/synthea-with-dependencies.jar \
  https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
shasum -a 256 tools/synthea/cache/synthea-with-dependencies.jar
# must print ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1

docker run --rm -e TZ=UTC -w /out --user "$(id -u):$(id -g)" \
  -v "$PWD/tools/synthea/cache:/opt/synthea:ro" -v "$PWD/tools/synthea/out:/out" \
  eclipse-temurin:17.0.20_8-jdk-jammy \
  java -Xmx2g -jar /opt/synthea/synthea-with-dependencies.jar \
    -s 42 -cs 42 -r 20261029 -e 20261029 -p 10 -a 45-85 \
    --generate.only_alive_patients=true --generate.thread_pool_size=1 \
    --exporter.baseDirectory=/out/ \
    --exporter.fhir.export=true --exporter.fhir.transaction_bundle=true \
    --exporter.fhir.use_us_core_ig=false --exporter.fhir.bulk_data=false \
    --exporter.hospital.fhir.export=true --exporter.practitioner.fhir.export=true \
    --exporter.fhir.included_resources=Patient,Encounter,Condition,MedicationRequest,AllergyIntolerance \
    --exporter.years_of_history=5 \
    --exporter.ccda.export=false --exporter.csv.export=false --exporter.text.export=false \
    --exporter.metadata.export=false \
    Massachusetts

cp tools/synthea/out/fhir/*.json data/fhir/synthea/
```

A second run produced byte-identical files (same Patient identifiers, same file names).

### Active MedicationRequest tally (checks A3 and A4)

Counted over the 10 committed Synthea patients, `status == active` only.

| | Count |
|---|---|
| Active MedicationRequests | **59** |
| with dose **and** timing (`doseAndRate` + `timing`) | **9** |
| without dose/timing | **50** |
| of those 50: no `dosageInstruction` at all | 36 |
| of those 50: `dosageInstruction` with only `asNeededBoolean: true` | 14 |

- **A3 holds:** none of the `doseQuantity` values carries a unit. Strength exists only in the RxNorm display (`lisinopril 10 MG Oral Tablet`).
- **A4 holds:** 85% of active Synthea meds have no dose or timing, so frequency must stay optional and PRN or unknown must mean "not comparable". The 14 as-needed rows are the Synthea presence-based `asNeededBoolean` behaviour (R01 gotcha 3).

## Pharmacy dataset (`data/pharmacy/pharmacy_records.json`)

```bash
python -m data.generators.make_pharmacy --seed 42      # from the repo root
```

A JSON array of 58 flat rows with string values: `record_id, patient_id, medication_name, dose_amount, dose_unit, frequency, date_recorded`. `patient_id` is the stable identifier (the Synthea UUID, or `CASE-*`); `dose_amount` is per administration. The file is **not** FHIR and never goes through HAPI; the app bakes it into its image.

- **Synthea patients (44 rows, all valid):** seeded perturbations of the FHIR medications that pass `ingest` validation, one scenario per medication: kept as is, a brand name from `aliases.json` (`Zestril` for lisinopril), 500 mg written as `0.5 g`, a different frequency text, a doubled or halved dose, dropped, or a duplicate row. Some patients also get a drug the hospital list doesn't have. Every scenario is guaranteed at least once; the generator fails loudly if the data can't show one. Fills are dated within 60 days of Synthea's end date, never in the future. No mL rows.
- **Case patients (14 rows):** scripted below, including the invalid rows the rules must reject.

## Patient intake (`data/intake/`)

```bash
python -m data.generators.make_intake --seed 42        # from the repo root
python -m db.seed data/intake                           # loads it into the app DB (idempotent)
```

Two CSVs in the format `db.seed` reads: `intake_interviews.csv` (`interview_ref, patient_identifier, taken_at, taken_by, informant, no_medications`) and `intake_medications.csv` (`interview_ref, record_id, medication_name, dose_amount, dose_unit, frequency`), raw strings as the patient said them. 12 interviews, 47 medication rows.

- **Synthea patients:** 8 interviewed with patient-report patterns (brand names, one OTC drug or supplement each, a prescribed drug not reported, a dose difference, a "not sure" dose); 1 patient who says they take nothing (`no_medications = true`, no rows); 1 with no interview at all. Which patients get which role is decided by the seed.
- **Case patients:** scripted interviews, below.
- Every seeded name normalizes to a FHIR or pharmacy name for that patient, or is one of the deliberate OTC drugs (a test checks this), so no false "missing" appears by accident.
- Interview times are mid-day UTC with an explicit offset, so their local date doesn't depend on the machine's timezone. `db.seed` upserts and never deletes, so after regenerating, reset a persistent app DB with `docker compose down -v`.

## Deliberate cases (`fhir/cases/medrec-cases.json` + the rows below)

What each source says, and the findings the real ingest and rules produce (`tests/data/test_data_cases.py` checks every line):

| Patient | FHIR (active) | Pharmacy | Intake | Expected findings |
|---|---|---|---|---|
| CASE-CLEAN | lisinopril 10, atorvastatin 20, amlodipine 5 mg (once daily) | Zestril 10, Atorvastatin 20, Amlodipine 5 mg | Zestril 10, Atorvastatin 20, Norvasc 5 mg | none (alias matches) |
| CASE-MIXED | metformin 500 mg, metoprolol 25 mg, acetaminophen 500 mg, sertraline 50 mg, warfarin 5 mg | Metformin Hydrochloride 500 mg; Acetaminophen 500 mg and 1000 mg; Sertraline 50 mg twice daily; Omeprazole 20 mg; Warfarin Sodium dose "ten"; four more invalid rows | Metformin 0.5 g; Acetaminophen 1000 mg; Sertraline 50 mg twice; Warfarin "not sure"; Ibuprofen 200 mg as needed | **7 findings** (below) |
| CASE-BRAND | rosuvastatin calcium 10 mg `[Crestor]` | Crestor 10 mg | Crestor 10 mg | **2 `missing`** in V1; 0 after V2 RxNorm |

CASE-MIXED's 7 findings:

| Type | Medication | Why |
|---|---|---|
| `duplicate` | acetaminophen | pharmacy lists 500 mg and 1000 mg |
| `duplicate` | sertraline | intake lists it twice |
| `dosage_mismatch` | acetaminophen | FHIR 500 mg, pharmacy 500 + 1000 mg, intake 1000 mg |
| `missing` | ibuprofen | reported by the patient only |
| `missing` | metoprolol | on the FHIR list; not in pharmacy records, not reported |
| `missing` | omeprazole | in pharmacy records only |
| `missing` | warfarin | on the FHIR list; the pharmacy row and the intake entry were rejected, so the summary names 2 rejected records |

- Metformin gives **no** finding: 500 mg = 0.5 g.
- Sertraline's once daily (FHIR) vs twice daily (pharmacy) is a V2 `frequency_mismatch`; V1 stores and shows frequency, never compares it.
- With no interview, CASE-MIXED gives the two-source result (`missing_from` is a single source).
- The six rejected records (five invalid pharmacy rows and the intake warfarin) sit on drugs that appear nowhere else, so they show as rejected without changing any finding: a blank name, a unit `tab`, a date `03/02/2026`, a future date, and the unreadable warfarin dose.
- CASE-BRAND's `Crestor` is deliberately not in `aliases.json`: FHIR normalizes to `rosuvastatin calcium` while pharmacy and intake say `crestor`.

`CASE-BRAND` is the last patient in the bundle and the importer's "already imported" marker.

Run the data tests with `pytest tests/data`. The seed test needs `TEST_DATABASE_URL` (CI sets it) and skips without it.

## Loading into HAPI

```bash
cp .env.example .env                  # once, from the repo root
docker compose up -d hapi             # HAPI + its Postgres, ~1 min to healthy
docker compose run --rm importer
curl -s -H 'Cache-Control: no-cache' 'http://localhost:8080/fhir/Patient?_summary=count'   # total: 13
```

HAPI caches search counts for 60 s, so a plain `Patient?_summary=count` right after an import can still show the old number. Send `Cache-Control: no-cache` (or add `_total=accurate`) to see the live count.

Order: hospital, practitioner, Synthea patients, cases. A second run finds `CASE-BRAND` and does nothing; any failed transaction exits non-zero.

Reset HAPI to empty: `docker compose down -v` (this also wipes the app DB).

## Recorded HAPI responses (`tests/fixtures/hapi/`)

`python infra/record_fixtures.py` (against a populated HAPI) writes, per case patient, the Patient search by identifier, `Patient/{id}` and `MedicationRequest?patient={id}&status=active`. `index.json` maps each request path and query to its file. HAPI assigns sequential numeric ids, so a fresh volume and the documented load order reproduce the recorded ids (`2174`, `2178`, `2184`).
