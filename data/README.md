# data/ (B2: FHIR side)

| Path | What |
|---|---|
| `fhir/synthea/` | 12 Synthea v4.0.0 FHIR R4 bundles: `hospitalInformation*.json` and `practitionerInformation*.json` (type `batch`), 10 patient bundles (type `transaction`). 1.7 MB. |
| `fhir/cases/medrec-cases.json` | Hand-designed transaction bundle: 3 invented patients (`urn:medrec:case`), 10 MedicationRequests. |
| `../infra/import_fhir.py` | Stdlib importer that loads both into HAPI. |
| `../tests/fixtures/hapi/` | Real HAPI responses recorded after the import, plus `index.json`. |

All data is synthetic or invented. No real patient data.

## Synthea generation

- Synthea **v4.0.0**, `https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar` (201,164,144 bytes).
- Jar sha256 `ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1`. This equals the `digest` the GitHub releases API reports for the asset (checked 2026-10-29). The jar is not committed.
- Run in `eclipse-temurin:17.0.20_8-jdk-jammy`; no local Java. `$JAR_DIR` holds the jar, `$OUT` receives `fhir/`.

```bash
docker run --rm -e TZ=UTC -w /out --user "$(id -u):$(id -g)" \
  -v "$JAR_DIR:/opt/synthea:ro" -v "$OUT:/out" \
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
cp "$OUT"/fhir/*.json data/fhir/synthea/
```

Synthea also writes an empty `x12/` directory, which we ignore.

**Determinism:** a second run with the same command into a fresh directory gave the same 12 file names, the same 10 Synthea patient identifiers, and **12 of 12 files byte-identical** (sha256).

Patients (key pharmacy rows on the Synthea identifier, system `https://github.com/synthetichealth/synthea`, not on the HAPI id):

| Patient | Synthea identifier | Active MedicationRequests |
|---|---|---|
| Bud153 Lowe577 | `98ff8f7e-7b14-79a9-04ea-aceff31a2328` | 12 |
| Cristobal567 Montero62 | `c86c400e-ff88-a1e3-2e23-caa4d8311f47` | 7 |
| Ezekiel373 Walter473 | `4f083ce3-f12b-bb4b-7353-e17f0cd55b0a` | 4 |
| Jona712 Dibbert990 | `aa616abe-1761-0c9a-7959-07544679dafd` | 3 |
| Kristine579 Cummings51 | `87f32e4c-f0e3-ba38-8864-d18d2698a070` | 4 |
| Leonila462 Nolan344 | `8c42357f-b924-9f38-d09a-007250c16c6f` | 10 |
| Shalanda398 Auer97 | `46ee9d82-b52c-856d-069b-5064ff052225` | 6 |
| Tennille443 Erdman779 | `e74367bd-7385-97dc-2c7f-251b4cd9fe29` | 2 |
| Todd315 Effertz744 | `5a3596ef-07d3-5463-e76d-96dedbb0e2cf` | 10 |
| Wallace647 Effertz744 | `5e688e99-61b3-5c88-3f60-21df8aaced27` | 1 |

### Tally of the Synthea MedicationRequests (checks assumptions A3/A4)

One-off Python over `fhir/synthea/*.json` (first `dosageInstruction` per request):

| Measure | Count |
|---|---|
| MedicationRequests, all statuses | 271 |
| **Active** | **59** |
| Active with a `dosageInstruction` | 23 |
| Active with `timing.repeat` | 9 (7 × `1 per 1 d`, 2 × `4 per 1 d`) |
| Active with a `doseQuantity` | 9 (all `{"value": 1.0}`) |
| Active with a `doseQuantity` that has a unit | **0** |
| Active with `asNeededBoolean = true` | 14 |
| Active whose display has exactly one parseable `<n> MG\|MCG\|G\|ML` strength | 43 (the other 16 are `/ACTUAT` or `/ML` concentrations, or 2-ingredient combinations) |
| Active with `medicationReference` | 0 |

What this confirms for ingest and rules:
- Strength comes only from the RxNorm display; `doseQuantity` is a unitless count.
- 36 of 59 active requests have no `dosageInstruction`, so frequency is often unknown.
- The `as_needed` presence quirk is real. `asNeededBoolean: true` with no timing appears on chronic meds such as `atorvastatin 20 MG`, `lisinopril 10 MG`, `rosuvastatin calcium 20 MG` and `24 HR metoprolol succinate` (V2 frequency rule: PRN means not comparable).

## Deliberate cases (`fhir/cases/medrec-cases.json`)

FHIR transaction bundle with POST entries and `urn:uuid` fullUrls (deterministic uuid5). Each MedicationRequest has `status active`, `intent order`, `authoredOn 2026-09-xxT09:00:00+00:00`, an RxNorm `medicationCodeableConcept` (display = text), and one `dosageInstruction` with `timing.repeat {frequency, period 1, periodUnit d}`, `asNeededBoolean false` and `doseQuantity {"value": 1}` with no unit, like Synthea.

RxCUIs, verified on 2026-10-29 with `https://rxnav.nlm.nih.gov/REST/rxcui.json?name=<display>` and `/rxcui/{id}/properties.json` (all TTY `SCD`, active, not suppressed):

| Display | RxCUI |
|---|---|
| lisinopril 10 MG Oral Tablet | 314076 |
| atorvastatin 20 MG Oral Tablet | 617310 |
| metformin hydrochloride 500 MG Oral Tablet | 861007 (the name query also returns 860975, the 24 HR extended-release SCD, so we use the exact match) |
| metoprolol tartrate 25 MG Oral Tablet | 866924 |
| amlodipine 5 MG Oral Tablet | 197361 |

Glucophage (brand RxCUI 151827) has ingredient metformin (6809) in RxNav, which is what V2 relies on for CASE-BRAND.

Case design. The FHIR column is this bundle; the pharmacy column documents what B3 must generate.

| Patient | FHIR MedicationRequest (display, timing) | Pharmacy rows B3 will generate | Expected V1 findings | V2 adds |
|---|---|---|---|---|
| CASE-CLEAN (Avery Clean, F, 1961-04-12) | lisinopril 10 MG Oral Tablet 1/1d; atorvastatin 20 MG Oral Tablet 1/1d; metformin hydrochloride 500 MG Oral Tablet 2/1d | Zestril 10 mg once daily; atorvastatin 20 mg once daily; metformin 500 mg twice daily | none | none |
| CASE-MIXED (Morgan Mixed, M, 1955-08-23) | atorvastatin 20 MG Oral Tablet 1/1d; lisinopril 10 MG Oral Tablet 1/1d; metoprolol tartrate 25 MG Oral Tablet 2/1d; metformin hydrochloride 500 MG Oral Tablet 2/1d; amlodipine 5 MG Oral Tablet 1/1d | Lipitor 20 mg once daily; atorvastatin 40 mg once daily; lisinopril 10 mg twice daily; metformin 0.5 g twice daily; omeprazole 20 mg once daily; amlodipine dose "ten" mg (invalid); blank name (invalid); aspirin 81 "tab" (invalid unit); simvastatin date 2026-13-45 (invalid); losartan date 2027-01-01 (future) | duplicate atorvastatin (pharmacy); dosage_mismatch atorvastatin; missing metoprolol (from pharmacy); missing omeprazole (from fhir); missing amlodipine (from pharmacy, rejected counterpart named) = 5 | frequency_mismatch lisinopril |
| CASE-BRAND (Riley Brand, F, 1968-02-03) | metformin hydrochloride 500 MG Oral Tablet 2/1d; lisinopril 10 MG Oral Tablet 1/1d | Glucophage 500 mg twice daily (brand NOT in alias list); lisinopril 10 mg once daily | missing metformin (from pharmacy); missing glucophage (from fhir) = 2 | RxNorm resolves Glucophage → metformin: 0 findings |

Notes: metformin 500 MG vs 0.5 g in CASE-MIXED is the unit-equivalence check, so it gives no finding. The alias list (TECHNICAL_PLAN §4.4) contains only zestril, lipitor, "metformin hydrochloride"→metformin and norvasc.

## Importing into HAPI

```bash
# in compose (defaults): FHIR_BASE_URL=http://hapi:8080/fhir DATA_DIR=/data/fhir WAIT_SECONDS=300
python3 infra/import_fhir.py
# from the host against a local HAPI:
FHIR_BASE_URL=http://localhost:18080/fhir DATA_DIR=data/fhir python3 infra/import_fhir.py
```

1. Waits until `GET {base}/metadata` returns 200, for up to `WAIT_SECONDS`.
2. Exits 0 with "already imported" if `Patient?identifier=urn:medrec:case|CASE-BRAND&_summary=count` has total > 0. The case bundle loads last, so this means a previous import finished.
3. Otherwise it POSTs the bundles in this order: hospital, practitioner, patients (sorted), cases.
4. It exits 1, naming the file and the HTTP status or failing entry, on any non-2xx response or entry status.
5. It prints one line per file.

The importer sends `Cache-Control: no-cache`. Without it, HAPI reuses an identical search result for 60 s: the first local re-run got the cached pre-import count of 0 and imported everything a second time.

Measured on 2026-10-29 against `hapiproject/hapi:v8.12.0-2` + `postgres:18-alpine` (18.6), started with `--env-file infra/hapi.env` plus the username/password `-e` flags:
- HAPI started in 13.5 s on an empty database.
- The import took **2.5 s** for 13 bundles, or 8.4 s wall time including the wait for HAPI.
- `Patient?_summary=count` returned **13**.
- The second run printed "already imported" in 0.2 s, and the count stayed 13.
- Both failure paths were checked by hand: a transaction with an unresolvable reference gave HTTP 404, and a batch entry with a bad reference gave entry status 400. Each exited 1 with the file name.

## Recorded fixtures (`tests/fixtures/hapi/`)

`index.json` maps each request string (relative to the FHIR base, exactly as the app issues it) to a file. `_case_ids` holds the HAPI ids of the three case patients, and `_synthea_sample` the HAPI id of Bud153 Lowe577 (12 active MedicationRequests: 2 with `timing.repeat`, 4 with `asNeededBoolean: true`, 6 with no `dosageInstruction`, and one `MG/ACTUAT` concentration).

| Request | File |
|---|---|
| `Patient?_count=50` | `patient-search.json` (13 entries, no `next` link) |
| `Patient/{id}` + `MedicationRequest?patient={id}&status=active&_count=100` for CASE-CLEAN, CASE-MIXED, CASE-BRAND, Synthea sample | `patient-<label>.json`, `medreq-<label>.json` (3, 5, 2 and 12 entries) |

The HAPI ids are only valid for that recorded import. The `self` links point at `http://localhost:18080/fhir`, with query parameters re-ordered by HAPI.
