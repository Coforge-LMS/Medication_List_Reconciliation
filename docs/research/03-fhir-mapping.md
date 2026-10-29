# 03 — FHIR R4 to medication contract mapping
OWNER: Sarthak Kakkar, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
1. **Fetch**: `GET {base}/MedicationRequest?patient={id}&status=active&_include=MedicationRequest:medication&_count=100` (follow Bundle next link). Map `search.mode=match` entries only; `include` entries (Medication) exist only to resolve `medicationReference`.
2. **Dose**: use `doseAndRate[].doseQuantity` when it has a mass/volume UCUM unit (`mg`, `g`, `ug`->mcg, `mL`). Otherwise parse the strength from the RxNorm display (regex below). **Synthea never sends a unit, so the display path is the main path for our data.**
3. **Frequency**: one canonical string from doses-per-day: `QD BID TID QID Q4H Q3H Q2H Q1H QOD QW QM PRN`, fallback `<n>/D`. Derive from `timing.code` (GTS), else `timing.repeat`, else `timeOfDay`/`when` count. Unknown is NULL, never guessed.
4. **Missing dosageInstruction**: accept with NULLs plus a warning, do not reject. Reject only: no patient ref, no medication name, no usable date. Rules skip dose/frequency compare when either side is NULL ("unknown" is not "mismatch").
5. **Current** = `status=active` only (V1). `on-hold` is a V2 option.

## Rationale
- Synthea (master, read 2026-10-29) builds `doseQuantity` with `setValue` only: no unit, system or code. The value is a count of dose units (tablets), not mg.
- Synthea medication modules come in three shapes: (a) no `prescription` -> no `dosageInstruction` at all; (b) `prescription` with only refills/as_needed -> a `dosageInstruction` with no timing and no dose; (c) `prescription.dosage` -> timing.repeat + unitless doseQuantity. Rejecting (a)/(b) would drop most of a patient's list and create false "missing" findings.
- RxNorm SCD/SBD names embed ingredient, strength and form, so strength is recoverable from the display for single-ingredient solids.
- Decimal math in a base unit makes 500 mg == 0.5 g exact; floats would not.

## Pinned versions
- FHIR R4 4.0.1 (pages fetched are v4.0.1). Search params used (`patient`, `status`, `intent`, `medication`, `authoredon`) are in the R4 MedicationRequest search table.
- Synthea `master` as pinned by `synthea.properties`: `exporter.fhir.use_us_core_ig = true`, `exporter.fhir.us_core_version = 6.1.0`, `exporter.fhir.transaction_bundle = true`. The team's actual Synthea release is UNVERIFIED; re-check these on the release used. We do not validate against US Core.
- URIs: RxNorm `http://www.nlm.nih.gov/research/umls/rxnorm` (Synthea `RXNORM_URI`); SNOMED `http://snomed.info/sct`; UCUM `http://unitsofmeasure.org`; GTS `http://terminology.hl7.org/CodeSystem/v3-GTSAbbreviation`.

## Commands and config snippets

### Field mapping (FHIR -> contract)
| Contract field | FHIR source | Rule |
|---|---|---|
| patient_id | `subject.reference` = `Patient/{id}` | take id part (also accept absolute URL); anything else (Group, `urn:uuid:`) -> reject `no_patient_ref` |
| medication name | `medicationCodeableConcept` `.coding[RxNorm].display` -> `.text` -> any `coding.display`; or `Medication.code` via contained `#id` / included | store verbatim (case kept, e.g. `amLODIPine`) |
| rxcui (opt.) | `coding.code` where system = RxNorm URI | else NULL (SNOMED-only drugs) |
| normalized_name (opt.) | derived | V2; for V1 dup check use `ingredient_key` (text before first strength token, casefolded) |
| dose_amount, dose_unit | `doseQuantity` or display strength | see pseudo-code |
| frequency | `timing.code` / `timing.repeat` / `asNeeded[x]` | see pseudo-code |
| source | constant | `'fhir'` |
| date_recorded | `authoredOn` | UTC date; partial date -> first day of period + warning; missing -> `meta.lastUpdated` + warning; neither -> reject `no_date` |
| source_record_id | `MedicationRequest.id` | store as `MedicationRequest/{id}`; `meta.versionId` optional, skip in V1 |
| (filter only) | `status`, `intent` | not stored; skip intent `proposal`, `plan`, `option` (our choice, not from spec) |
| mapping_warnings | derived | DB column outside the contract (JSON list of codes below) |

### Frequency canon (doses per day -> code)
`1 QD | 2 BID | 3 TID | 4 QID | 6 Q4H | 8 Q3H | 12 Q2H | 24 Q1H | 1/2 QOD | 1/7 QW | 1/30 QM | other -> "<n>/D"`.
GTS codes (all 16 in the R4 TimingAbbreviation set): BID 2, TID 3, QID 4, QD 1, AM 1, PM 1, QOD 1/2, Q1H 24, Q2H 12, Q3H 8, Q4H 6, Q6H 4, Q8H 3, BED 1, WK 1/7, MO 1/30. So Q6H -> QID, Q8H -> TID, `1 per 12 h` -> BID, BED/AM/PM/HS/MORN/EVE -> QD. **Time-of-day is deliberately dropped (QHS == QD); clinical sign-off needed.** `UnitsOfTime` days: s 1/86400, min 1/1440, h 1/24, d 1, wk 7, mo 30 (approx), a 365 (approx).

### Pseudo-code
```python
UCUM = {"mg":"mg", "g":"g", "ug":"mcg", "mcg":"mcg", "ml":"mL"}      # key = code.lower(); mL stays its own dimension
BASE_MG = {"mg": Decimal(1), "g": Decimal(1000), "mcg": Decimal("0.001")}  # compare after converting to mg

def map_dose(dosages, display, warn):
    if len(dosages) > 1: warn("multi_dosage"); return None, None      # tapers / split regimens: human review
    q = first(doseAndRate.doseQuantity) or doseRange_if_low_equals_high(...)   # unequal range -> warn("dose_range"), None
    if q is not None and (q.code or q.unit) not in (None, "", "1") and not str(q.code).startswith("{"):
        u = UCUM.get((q.code or q.unit).lower())                      # lenient: also accept system-less `unit` text
        if u: return Decimal(str(q.value)), u
        warn("unsupported_unit"); return None, None                   # e.g. [iU], mEq, [drp]
    s = parse_strength(display, warn)                                 # (Decimal, unit) | None
    if s and q is not None and q.value is not None:                   # unitless count, e.g. 0.5 tablet
        s = (s[0] * Decimal(str(q.value)), s[1])
    return s or (None, None)

def map_frequency(dosages, warn):
    if len(dosages) != 1: return None
    d = dosages[0]; t = d.timing; r = t.repeat if t else None
    per_day = None
    if t and (c := gts_code(t.code)): per_day = GTS_PER_DAY[c]        # coding.system == GTS URI; fallback: CodeableConcept.text equals a GTS code
    elif r and r.frequency and r.period and r.periodUnit and not any([r.frequencyMax, r.periodMax]):
        per_day = Fraction(r.frequency) / (Fraction(str(r.period)) * UNIT_DAYS[r.periodUnit])
    elif r and (r.timeOfDay or r.when): per_day = len(set(r.timeOfDay or r.when))   # timeOfDay and when are mutually exclusive in R4
    elif r and (r.frequencyMax or r.periodMax): warn("freq_range")
    code = CANON.get(per_day) or (f"{float(per_day):g}/D" if per_day else None)
    prn = d.asNeededBoolean is True or d.asNeededCodeableConcept is not None
    return f"{code} PRN" if (prn and code) else ("PRN" if prn else code)

def ingredient_key(display):   # V1 name key: strip qty factor, keep text before the first strength token
    return QTY.sub("", display).split(first_strength_start)[0].strip().casefold()
```

### Strength regex (applied to the RxNorm display, case-insensitive)
```python
QTY      = re.compile(r'(?<![\w./])\d+(?:\.\d+)? (?:HR|ACTUAT|ML)(?![\w/])\s*', re.I)   # quantity factor: "24 HR", "200 ACTUAT", "3 ML"
STRENGTH = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?) (MG|MCG|UG|G|ML|UNT|MEQ)(/\S+)?(?![\w/])', re.I)

def parse_strength(display, warn):
    hits = STRENGTH.findall(QTY.sub("", display))
    if not hits:            warn("no_strength");  return None
    if len(hits) > 1:       warn("combination");  return None      # "amlodipine 10 MG / benazepril ... 20 MG"
    n, unit, denom = hits[0]
    if denom:               warn("concentration"); return None     # MG/ML, MG/ACTUAT, MG/HR, UNT/ML
    if unit.lower() not in UCUM: warn("unsupported_unit"); return None   # UNT, MEQ
    return Decimal(n), UCUM[unit.lower()]
```
Self-check cases (expected result):
- `lisinopril 10 MG Oral Tablet` -> 10 mg. `Aspirin 81 MG Oral Tablet [..]` -> 81 mg.
- `24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet` -> 500 mg (quantity factor stripped).
- `amlodipine 10 MG / benazepril hydrochloride 20 MG Oral Capsule` -> NULL, `combination`.
- `200 ACTUAT levalbuterol 0.045 MG/ACTUAT Metered Dose Inhaler` -> NULL, `concentration`.
- `3 ML liraglutide 6 MG/ML Pen Injector`, `Insulin Lispro 100 UNT/ML Injectable Solution [Humalog]` -> NULL.
- `500 mg` vs `0.5 g` -> equal after `BASE_MG` conversion; `mL` never equals a mass.

## Gotchas
- **Synthea `as_needed` quirk (source reading, not run on a real bundle)**: exporter uses `rxInfo.has("as_needed")` (key presence). Modules with `"as_needed": false` (statins, ACE/ARB, beta blockers, maintenance inhalers) still export `asNeededBoolean=true`, text `Take as needed.`, no timing, no dose. Our rule yields `PRN` for them. **Frequency-mismatch rule must treat PRN vs scheduled as "not comparable", not mismatch**, or lisinopril PRN vs pharmacy QD will be a false positive.
- Synthea status is `completed` if the medication has a stop time, else `active`; `intent` is always `order`; `stopped`/`on-hold` are not emitted. Chronic meds are re-issued at wellness visits (old one `completed`, new one `active`), so filter `status=active` or you get duplicate-looking history.
- Only the hypertension module's four drugs (amlodipine 2.5 mg, HCTZ 25 mg, lisinopril 10 mg, losartan 25 mg) carry `dosage`: always 1 per 1 day -> QD. Demo frequency mismatches must come from the pharmacy side (e.g. pharmacy BID vs FHIR QD).
- No `dosageInstruction` at all (Synthea): `metabolic_syndrome/medications` (metformin ER 500 mg, liraglutide pen, insulin). Metformin keeps its 500 mg from the display; liraglutide and insulin have concentration-only strengths -> dose NULL.
- Combination products: dose NULL + `combination`; if both sides carry `rxcui`, differing rxcui means a different product (V2), same rxcui means same strengths.
- Inhalers / injectables / patches (MG/ACTUAT, MG/ML, UNT/ML, MG/HR) cannot be expressed in mg/g/mcg/mL -> dose NULL + `concentration`; do not invent a per-dose mass.
- Quantity-factor prefixes (`24 HR`, `200 ACTUAT`, `3 ML`, `Breath-Actuated 120 ACTUAT`) are package/release info, not strength; strip before parsing. Different strength, form or route is never equivalent: keep form words in the name.
- Display case is Tall-Man style (`amLODIPine`): compare casefolded, store original. Brand suffix `[Lipitor]` is a different RxNorm concept; V1 exact-name rules treat it as different, V2 handles brand/generic.
- FHIR display has strength + form (`lisinopril 10 MG Oral Tablet`); pharmacy name may be bare `Lisinopril`. Exact name equality will miss; use `ingredient_key` for V1 duplicate/missing matching.
- `medicationReference`: Synthea emits it only for administered meds when a separate Medication is created (US Core on); resolve `#id` in `contained` or the included Medication (`search.mode=include`). Whether those are inpatient-only and should be excluded from a home list is UNVERIFIED.
- IDs: POST transaction entries get server-generated ids and in-bundle references are rewritten (spec), so HAPI ids differ from the Synthea file. HAPI's exact id format is UNVERIFIED. Seed the pharmacy generator from `GET /Patient` ids, or key on the Synthea identifier (system `https://github.com/synthetichealth/synthea`, value = original person UUID). Patient also has MRN, SSN, DL, passport identifiers: do not copy them into the app.
- `doseRange` with low != high, `frequencyMax`/`periodMax`, multiple `dosageInstruction`: NULL + warning (`dose_range`, `freq_range`, `multi_dosage`); Synthea emits none of these.
- Free-text-only SIG (`dosage.text`): NULL frequency in V1. Synthea text is only `Take as needed.` plus SNOMED instruction displays. A V2 exact-phrase dictionary (`twice daily`, `at bedtime`...) is optional.
- UCUM: `ug` is micro-gram; `mL` and `ml` are both valid case-sensitive; `1` and `{annotation}` units mean "unitless count". Treat Synthea's missing unit as unitless.
- Timing: `timeOfDay` and `when` cannot both be present; `timing.code` is a complete statement of the timing, `repeat.bounds` still applies. `mo`/`a` to days are approximations.
- Use `Decimal(str(x))`, never float. Do not store `entered-in-error` or `draft` rows in any case.
- Paging: set `_count`, loop on the Bundle next link; `Bundle.total` excludes included resources.

## Rejected alternatives
- **Reject records without dosageInstruction**: would discard most Synthea medications; replaced by nullable fields + warnings.
- **Store frequency as free text or raw `frequency/period`**: not directly comparable; canonical code from doses/day is deterministic and shared by the pharmacy side.
- **Keep QHS/AM/PM distinct from QD**: needs timing-of-day semantics we cannot source from Synthea; false mismatches. Revisit only with clinical input.
- **Use `doseQuantity.value` as mg**: wrong for Synthea (a tablet count).
- **Parse strength from free text with NLP / RxNav lookup per record**: slower and online; the RxNorm display is already structured. RxCUI is read from `coding.code` instead.
- **Include `on-hold` in V1**: needs a status field in the contract; defer to V2.

## Sources
- [FHIR R4 MedicationRequest](https://hl7.org/fhir/R4/medicationrequest.html): elements, medication[x], status/intent codes, search parameters (fetched 2026-10-29)
- [FHIR R4 Dosage](https://hl7.org/fhir/R4/dosage.html): dosage elements, doseAndRate dose[x] Range or SimpleQuantity (fetched 2026-10-29)
- [FHIR R4 datatypes, Timing](https://hl7.org/fhir/R4/datatypes.html#Timing): repeat elements, Timing.code semantics, frequency/period example, when/timeOfDay exclusivity; tim-* invariant IDs not seen (fetched 2026-10-29)
- [TimingAbbreviation value set](https://hl7.org/fhir/R4/valueset-timing-abbreviation.html): 16 GTS codes and the GTS system URI (fetched 2026-10-29)
- [UnitsOfTime value set](https://hl7.org/fhir/R4/valueset-units-of-time.html): s, min, h, d, wk, mo, a with UCUM system (fetched 2026-10-29)
- [EventTiming value set](https://hl7.org/fhir/R4/valueset-event-timing.html): `when` codes (MORN, HS, WAKE, ...) (fetched 2026-10-29)
- [MedicationRequest status value set](https://hl7.org/fhir/R4/valueset-medicationrequest-status.html): status definitions (fetched 2026-10-29)
- [FHIR R4 Search](https://hl7.org/fhir/R4/search.html): `_include` syntax, `search.mode` match/include (fetched 2026-10-29)
- [FHIR R4 HTTP](https://hl7.org/fhir/R4/http.html): transaction id assignment and reference rewriting (fetched 2026-10-29)
- [US Core MedicationRequest](https://hl7.org/fhir/us/core/StructureDefinition-us-core-medicationrequest.html): RxNorm for medication[x], contained or external Medication, `_include` support (page is US Core 9.0.0) (fetched 2026-10-29)
- [UCUM specification](https://ucum.org/ucum): `u` prefix -> `ug`, case sensitivity, annotations, unity (fetched 2026-10-29)
- [RxNorm technical documentation](https://www.nlm.nih.gov/research/umls/rxnorm/docs/techdoc.html): SCD/SBD name structure, ` / ` separator, `[Brand]`, quantity-factor prefixes (fetched 2026-10-29)
- [Synthea FhirR4.java](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/java/org/mitre/synthea/export/FhirR4.java): MedicationRequest export (status, intent, authoredOn, doseQuantity value-only, as_needed `has()` checks, medicationReference branch, Patient identifiers) (fetched 2026-10-29)
- [Synthea State.java](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/java/org/mitre/synthea/engine/State.java): `prescription` -> `prescriptionDetails`, may be null (fetched 2026-10-29)
- [Synthea synthea.properties](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/synthea.properties): FHIR export defaults, US Core 6.1.0 (fetched 2026-10-29)
- [Synthea wiki, module states](https://github.com/synthetichealth/synthea/wiki/Generic-Module-Framework%3A-States): MedicationOrder `prescription` fields optional (fetched 2026-10-29)
- Synthea module JSON, drug displays and prescription blocks (fetched 2026-10-29): [hypertension_medication](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/hypertension_medication.json), [ace_arb](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/ace_arb.json), [beta_blocker](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/beta_blocker.json), [statin](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/statin.json), [emergency_inhaler](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/emergency_inhaler.json), [maintenance_inhaler](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/maintenance_inhaler.json), [otc_pain_reliever](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/otc_pain_reliever.json), [metabolic_syndrome/medications](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/metabolic_syndrome/medications.json)

## UNVERIFIED
- Synthea behavior is from `master` source and module JSON read through a summarizing fetch; no real generated bundle was inspected (no published R4 sample bundle was reachable). Run a 5-minute tally on our HAPI (share of active MedicationRequests with no dosageInstruction / asNeededBoolean=true / unitless doseQuantity) before presenting.
- Synthea release used by the team, and whether it matches the `master` behavior above (incl. the `as_needed` presence quirk).
- HAPI id format after transaction load; HAPI default page size.
- Meaning of Synthea `category` values (community / inpatient / outpatient) and whether to exclude inpatient administrations.
- GTS code system page on terminology.hl7.org returned no content; code list comes from the R4 value set page. Q6H/Q8H/BED collapse into QID/TID/QD is our design choice.
