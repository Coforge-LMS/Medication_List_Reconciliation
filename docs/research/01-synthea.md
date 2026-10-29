# 01 — Synthea: deterministic synthetic FHIR R4 patients
OWNER: Rachit Shah, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._
_Caveat: all GitHub source reads went through a summarizing fetch tool, not a local checkout. The two load-bearing claims (no unit on doseQuantity; `as_needed` is presence-based) should be re-checked against the generated files (jq snippet below). Nothing here was executed: Synthea was not downloaded or run._

## Recommendation
Run **Synthea v4.0.0** once inside `eclipse-temurin:17.0.20_8-jdk-jammy` (jar mounted from the host, no Java installed locally), 10 patients aged 45-85, fixed seeds and dates, FHIR R4 **transaction bundles with US Core OFF**, only the resource types the app needs. Commit the resulting `hospitalInformation*.json`, `practitionerInformation*.json` and 10 patient bundles. Load them into HAPI in that order. Key pharmacy records on the Synthea Person UUID (`Patient.identifier`, system `https://github.com/synthetichealth/synthea`), never on the HAPI-assigned id.

## Rationale
- Reproducible: same version + `-s` + `-cs` + `-r` + `-e` + same `years_of_history` gives identical output and identical UUIDs (Recreating-a-Dataset wiki). `-e` defaults to "now", so it MUST be pinned with `-r`.
- Transaction bundles are POSTable as-is, but reference Organization/Practitioner by search URL, so hospital/practitioner files must load first.
- US Core OFF: no Medication/Location/PractitionerRole/Provenance/CareTeam clutter; MedicationRequest still carries `medicationCodeableConcept` with RxNorm. `included_resources` drops Claim/EOB/Observation (the bulk of bundle size).
- Active meds are kept by the history filter regardless of start date, so `years_of_history=5` shrinks output without losing current meds.

## Pinned versions
| Item | Pin | Note |
|---|---|---|
| Synthea | `v4.0.0` (published 2026-03-05) | newest tagged release; `master-branch-latest` is a rolling build (2026-10-21): do not use |
| Jar URL | `https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar` | 201,164,144 bytes (~192 MiB) |
| Jar sha256 | `ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1` | from GitHub API asset `digest`; re-verify with `shasum -a 256` after download |
| Java | 17+ (v4.0.0 notes: drops JDK 11, supports up to JDK 25) | use a JDK image, wiki says JDK not JRE |
| Docker image | `eclipse-temurin:17.0.20_8-jdk-jammy` | tag exists, multi-arch incl. linux/amd64 and arm64 (Docker Hub API, 2026-09-18). Optionally add `@sha256:51d32af96fb8a13ffbc96c719d7b05447a04ca69f314627d64050a64ecd13057` (index digest) |
| FHIR | R4 (HAPI structures 4.0.1), `exporter.fhir.us_core_version` irrelevant with US Core off | |

## Commands and config snippets
Run from repo root (not executed by the author; flags verified against `App.java` v4.0.0 and `synthea.properties` v4.0.0):
```bash
mkdir -p tools/synthea/cache tools/synthea/out
curl -fL -o tools/synthea/cache/synthea-with-dependencies.jar \
  https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
shasum -a 256 tools/synthea/cache/synthea-with-dependencies.jar   # must equal the pin above

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
```
- Flag syntax: both `--key=value` and `--key value` work; `-s -cs -r -e -p -a -g` are CLI flags (`-r`/`-e` are `yyyyMMdd`, UTC).
- Output: `tools/synthea/out/fhir/` with `<First>_<Last>_<uuid>.json` per patient (name spaces become `_`), plus `hospitalInformation<stop>.json` and `practitionerInformation<stop>.json` (that `<stop>` is a long passed in; probably the end time in epoch ms, so stable with `-e` pinned: UNVERIFIED).
- Commit only `out/fhir/*.json` (suggest `seed/synthea/`). Do not commit the jar.
- Sanity check after the run (swap in a real file name; or do the same in Python):
```bash
jq -r '.entry[].resource|select(.resourceType=="MedicationRequest")|[.status,.medicationCodeableConcept.text,(.dosageInstruction[0].asNeededBoolean|tostring),(.dosageInstruction[0].doseAndRate[0].doseQuantity|tostring),(.dosageInstruction[0].timing.repeat|tostring)]|@tsv' out/fhir/Some_Patient_*.json
```
Every patient should have at least 2-3 `active` rows; if one has none, change `-s` (or raise `-p` and pick patients) and rerun.
- Bundle size: no measurement available. Expect tens to a few hundred KB per patient with the include filter (UNVERIFIED estimate).

Annotated MedicationRequest, **shape only, reconstructed from `FhirR4.java` v4.0.0 + `hypertension_medication.json`; not a copied sample; ids/dates/NPI illustrative**:
```jsonc
{ "resourceType": "MedicationRequest",
  "id": "<uuid, = Medication.uuid>",             // POSTed, so HAPI assigns a NEW id
  "status": "active",                            // only active|completed are emitted
  "intent": "order",
  "medicationCodeableConcept": {                 // CodeableConcept, not a Reference (US Core off)
    "coding": [{ "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                 "code": "314076", "display": "lisinopril 10 MG Oral Tablet" }],
    "text": "lisinopril 10 MG Oral Tablet" },   // strength lives ONLY here
  "subject":   { "reference": "urn:uuid:<Person.ID>" },     // HAPI rewrites to Patient/<id>
  "encounter": { "reference": "urn:uuid:<encounter uuid>" },
  "authoredOn": "2025-03-01T08:15:00+00:00",     // illustrative; no end date is exported
  "requester": { "reference": "Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|9999..." },
  "reasonReference": [{ "reference": "urn:uuid:<condition uuid>" }],  // or reasonCode when no Condition match
  "dosageInstruction": [{
    "sequence": 1,
    "asNeededBoolean": false,
    "timing": { "repeat": { "frequency": 1, "period": 1, "periodUnit": "d" } },
    "doseAndRate": [{ "doseQuantity": { "value": 1 } }]   // NO unit, NO system, NO code
  }] }
```

## Gotchas
1. **Q6: `doseQuantity` carries NO mg.** Code builds `new SimpleQuantity().setValue(amount)` with no `setUnit`; `amount` is the module's count of dose units (1 in the lisinopril/amlodipine modules), i.e. "1 tablet". Strength exists only in the RxNorm display/text (`lisinopril 10 MG Oral Tablet`, `amLODIPine 2.5 MG Oral Tablet`, `albuterol 0.09 MG/ACTUAT ...`). Dose comparison must parse strength from the display text (case-insensitive; mixed case like `amLODIPine`) or, better, from RxNorm (see 07-rxnorm.md).
2. **Many medications have no timing or dose at all.** `dosageInstruction` timing/dose is built only when the module prescription has a `dosage` object and no `as_needed` key. Module JSON read: hypertension drugs (lisinopril, amlodipine, HCTZ) have `{amount 1, frequency 1, period 1, unit days}`; the statin, beta_blocker and emergency_inhaler modules show only `refills`/`as_needed` with no dosage. Frequency rules (V2) must treat missing timing as "unknown", not mismatch. Prefer scenarios built on meds that have dosage.
3. **`asNeededBoolean` is presence-based**: source is `dosage.setAsNeeded(new BooleanType(rxInfo.has("as_needed")))` (comment: "true if present"). A prescription JSON with `"as_needed": false` (which the statin/beta_blocker modules appear to carry) may therefore export `asNeededBoolean: true` plus text "Take as needed." UNVERIFIED in real output: check with the jq snippet before relying on it.
4. **Status**: only `active` (stop == 0) and `completed` (stop != 0). Never `stopped`. No end date, no `dispenseRequest`. Current meds = `status == active`. Chronic meds are renewed at wellness visits (`renewChronicMedicationsAtWellness`), so expect an old `completed` plus a new `active` request for the same drug (renewal behaviour: reading of source, verify). Deduplicate by RxNorm code among active only.
5. **No MedicationStatement anywhere** in `FhirR4.java`. `Medication` resources only when `use_us_core_ig=true` AND the med is an in-encounter administration; `MedicationAdministration` exists in code (status always completed). Our include list and US Core OFF avoid all of these.
6. **HAPI re-assigns ids.** Patient bundle entries are `POST <Type>` with `urn:uuid:` fullUrls; FHIR R4 says the server generates ids for POST creates and rewrites in-bundle references. The only stable Synthea key surviving is `Patient.identifier` (the MR identifier has the same value). MedicationRequest has no identifier, so store the HAPI id for it.
7. **Not idempotent.** Only Organization/Location/Practitioner get `ifNoneExist`. Re-posting a patient bundle creates a duplicate Patient. Reload by wiping HAPI's volume, or search by identifier first.
8. **Load order is mandatory**: hospital, practitioner, then patients. Patient bundles use query references (`Organization?identifier=https://github.com/synthetichealth/synthea|<id>`, `Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|<npi>`); per FHIR R4, zero matches fails the whole transaction. HAPI must allow search-URL references in transactions (setting/default: UNVERIFIED, see 02-hapi-fhir.md). Hospital/practitioner files are Bundle type `batch` (POST + ifNoneExist), patient files `transaction`.
9. **Defaults/wiki disagree.** v4.0.0 `synthea.properties` has `use_us_core_ig=true` (6.1.0), `transaction_bundle=true`, hospital/practitioner export true, `years_of_history=10`; the Common-Configuration and HL7-FHIR wiki pages still say US Core false / 5.0.1. Always pass the flags explicitly.
10. **`-p` counts living patients, but deceased "overflow" patients are exported by default** (source reading). `--generate.only_alive_patients=true` suppresses them. Name numbers (`Jaime482 Hahn107`) come from `generate.append_numbers_to_person_names=true` (default).
11. **Identifiers** (Patient): Synthea id (system `https://github.com/synthetichealth/synthea`, value = Person.ID = Patient.id in the file); MR (`http://hospital.smarthealthit.org`, same UUID); SSN (`http://hl7.org/fhir/sid/us-ssn`); driver's license (`urn:oid:2.16.840.1.113883.4.3.25`, optional); passport (`http://hl7.org/fhir/sid/passport-USA`, optional). Name: `given` = first (+ middle), `family`, optional `prefix`/`suffix`, extra `maiden` name for some women. **Key pharmacy rows on the Synthea UUID** (`synthea_id`); join to the HAPI id at import time.
12. Determinism caveats: pin `-e` as well as `-r`; same seed across separate populations risks UUID collisions; single thread removes ordering doubt; set `TZ=UTC`; JDK/OS version should not matter.
13. `exporter.fhir.included_resources` takes R4 class simple names, invalid names throw; Patient and Encounter are always included; setting both include and exclude ignores both. UNVERIFIED: that `periodUnit` serialises as `d` (code derived from the units-of-time mapping s/min/h/d/wk/mo/a).

## Rejected alternatives
- `master-branch-latest` jar: rolling, not reproducible.
- Installing Java locally / Gradle build from source: violates the no-Java constraint.
- US Core ON: bigger bundles and extra resource types with no benefit for this app.
- `exporter.fhir.bulk_data=true` (NDJSON): no per-patient bundles, `fullUrl` becomes `Type/id`, needs a different loader.
- `transaction_bundle=false` (collection bundles): entries have no `request`, so they cannot be POSTed to HAPI directly.
- Pre-generated samples as primary source: not under our seed control; older Synthea. Keep as fallback only: `synthea-sample-data` repo, `downloads/latest/synthea_sample_data_fhir_latest.zip` (24,052,464 bytes, assumed R4) and `downloads/synthea_sample_data_fhir_r4_nov2021.zip` (94,887,125 bytes) and `..._sep2019.zip` (85,042,887 bytes). Patient counts, license, and MedicationRequest shape of these older files UNVERIFIED. `https://synthea.mitre.org/downloads` could not be fetched (certificate error), so its catalogue is UNVERIFIED.
- Official Synthea Docker image: none confirmed (UNVERIFIED); temurin + mounted jar is simpler to pin.

## Sources
- [Synthea releases](https://github.com/synthetichealth/synthea/releases): release list, `master-branch-latest` is rolling (fetched 2026-10-29)
- [Releases API (list)](https://api.github.com/repos/synthetichealth/synthea/releases?per_page=5): v4.0.0 date 2026-03-05, jar size, download URL (fetched 2026-10-29)
- [Releases API (v4.0.0)](https://api.github.com/repos/synthetichealth/synthea/releases/tags/v4.0.0): asset digest, notes (fetched 2026-10-29)
- [v4.0.0 release page](https://github.com/synthetichealth/synthea/releases/tag/v4.0.0): US Core 7, JDK 17+, Gradle 9 (fetched 2026-10-29)
- [Basic Setup and Running](https://github.com/synthetichealth/synthea/wiki/Basic-Setup-and-Running): Java 17+ JDK, CLI syntax (fetched 2026-10-29)
- [Common Configuration](https://github.com/synthetichealth/synthea/wiki/Common-Configuration): config file, years_of_history; defaults stale (fetched 2026-10-29)
- [HL7 FHIR wiki](https://github.com/synthetichealth/synthea/wiki/HL7-FHIR): transaction bundles, US Core resources, bulk data (fetched 2026-10-29)
- [FHIR Transaction Bundles wiki](https://github.com/synthetichealth/synthea/wiki/FHIR-Transaction-Bundles): load order, query references (fetched 2026-10-29)
- [Recreating a Dataset](https://github.com/synthetichealth/synthea/wiki/Recreating-a-Dataset): seed/-cs/-r/-e/version determinism (fetched 2026-10-29)
- [FAQ](https://github.com/synthetichealth/synthea/wiki/Frequently-Asked-Questions): sample data location, -a, years_of_history (fetched 2026-10-29)
- [App.java v4.0.0](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/App.java): flags, `--key=value` overrides, usage text (fetched 2026-10-29)
- [Generator.java v4.0.0](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/engine/Generator.java): defaults, per-person seeds, only_alive, overflow (fetched 2026-10-29)
- [Exporter.java v4.0.0](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/export/Exporter.java): file naming, history filter (fetched 2026-10-29)
- [FhirR4.java v4.0.0](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/export/FhirR4.java): MedicationRequest, dosage, status, identifiers, newEntry/fullUrl (fetched 2026-10-29)
- [ExportHelper.java v4.0.0](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/export/ExportHelper.java): search-URL reference format, ifNoneExist types (fetched 2026-10-29)
- [HospitalExporterR4.java](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/export/HospitalExporterR4.java): `hospitalInformation<stop>.json`, batch type (fetched 2026-10-29)
- [FhirPractitionerExporterR4.java](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/export/FhirPractitionerExporterR4.java): `practitionerInformation<stop>.json` (fetched 2026-10-29)
- [HealthRecord.java](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/world/concepts/HealthRecord.java): Medication fields, stop == 0 means active (fetched 2026-10-29)
- [State.java](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/java/org/mitre/synthea/engine/State.java): MedicationOrder, administration, chronic renewal (fetched 2026-10-29)
- [synthea.properties v4.0.0](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/resources/synthea.properties): all exporter/generate defaults (fetched 2026-10-29)
- [hypertension_medication.json](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/resources/modules/medications/hypertension_medication.json): RxNorm codes, dosage amount 1 (fetched 2026-10-29)
- [statin.json](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/resources/modules/medications/statin.json), [beta_blocker.json](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/resources/modules/medications/beta_blocker.json), [emergency_inhaler.json](https://raw.githubusercontent.com/synthetichealth/synthea/v4.0.0/src/main/resources/modules/medications/emergency_inhaler.json): no dosage objects (fetched 2026-10-29)
- [FHIR R4 HTTP/transaction](https://hl7.org/fhir/R4/http.html): server assigns ids on POST, reference rewriting, search-URL references (fetched 2026-10-29)
- [Docker Hub tag API, 17.0.20_8-jdk-jammy](https://hub.docker.com/v2/repositories/library/eclipse-temurin/tags/17.0.20_8-jdk-jammy): tag, architectures, index digest (fetched 2026-10-29)
- [synthea-sample-data downloads (API)](https://api.github.com/repos/synthetichealth/synthea-sample-data/contents/downloads) and [latest/](https://api.github.com/repos/synthetichealth/synthea-sample-data/contents/downloads/latest): fallback zip names and sizes (fetched 2026-10-29)
- [Third-party sample hospitalInformation.json](https://git.uni-greifswald.de/MILA_public/medax_pipeline/src/branch/main/mockData/short_hospitalInformation.json): secondary evidence only, batch bundle with `urn:uuid` fullUrl and `ifNoneExist` (fetched 2026-10-29)
