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

## Deliberate cases (`fhir/cases/medrec-cases.json`)

The pharmacy side lives in B3's generator, which must emit these rows for the case patients:

| Patient | FHIR (active) | Pharmacy rows the generator must pair | Exercises |
|---|---|---|---|
| CASE-CLEAN | lisinopril 10 MG, atorvastatin 20 MG, amlodipine 5 MG (all once daily) | `Zestril 10 mg`, `atorvastatin 20 mg`, `amlodipine 5 mg` | alias match, otherwise no discrepancy |
| CASE-MIXED | metformin hydrochloride 500 MG BID, metoprolol tartrate 25 MG BID, acetaminophen 500 MG BID, sertraline 50 MG once daily, warfarin sodium 5 MG once daily | metformin 500 mg **and** metformin 1000 mg (duplicate + dosage mismatch); **no** metoprolol (missing in pharmacy); a pharmacy-only drug, e.g. omeprazole (missing in FHIR); acetaminophen `0.5 g` (equal to 500 mg, not a mismatch); sertraline 50 mg twice daily (frequency difference, V2); warfarin with an invalid row only (e.g. `dose_amount` not a number), so "missing" says the pharmacy record was rejected | each V1 rule, unit equivalence, rejected-counterpart wording, V2 frequency |
| CASE-BRAND | rosuvastatin calcium 10 MG `[Crestor]` | `Crestor 10 mg` | brand not in `aliases.json`: both sides normalize differently until V2 RxNorm |

`CASE-BRAND` is the last patient in the bundle and the importer's "already imported" marker.

## Loading into HAPI

```bash
docker compose -f infra/docker-compose.yml up -d hapi     # HAPI + its Postgres, ~1 min to healthy
docker compose -f infra/docker-compose.yml run --rm importer
curl -s -H 'Cache-Control: no-cache' 'http://localhost:8080/fhir/Patient?_summary=count'   # total: 13
```

HAPI caches search counts for 60 s, so a plain `Patient?_summary=count` right after an import can still show the old number. Send `Cache-Control: no-cache` (or add `_total=accurate`) to see the live count.

Order: hospital, practitioner, Synthea patients, cases. A second run finds `CASE-BRAND` and does nothing; any failed transaction exits non-zero.

Reset HAPI to empty: `docker compose -f infra/docker-compose.yml down -v`.

## Recorded HAPI responses (`tests/fixtures/hapi/`)

`python infra/record_fixtures.py` (against a populated HAPI) writes, per case patient, the Patient search by identifier, `Patient/{id}` and `MedicationRequest?patient={id}&status=active`. `index.json` maps each request path and query to its file. HAPI assigns sequential numeric ids, so a fresh volume and the documented load order reproduce the recorded ids (`2174`, `2178`, `2184`).
