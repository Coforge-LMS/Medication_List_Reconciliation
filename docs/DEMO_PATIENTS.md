# Demo patient sheet

All patients are synthetic. App: http://127.0.0.1:8000. Search on the home page by name (a full name, or the start of any name) or by exact identifier (case-sensitive).

**Start clean, from the repo root (allow a minute or so):**

```bash
cp .env.example .env    # first time only
docker compose down -v
docker compose up -d --build
```

## Suggested order

| # | Search | Patient | What it shows | Expect |
|---|---|---|---|---|
| 1 | `Mixton` | Marcus Mixton (CASE-MIXED) | Everything at once: all four rule types, RxNorm matching, rejected records, the PDF | **8 findings:** 2 duplicate, 4 missing, 1 dosage mismatch, 1 frequency mismatch; 1 medication with no differences (metformin); 6 rejected records |
| 2 | `Cleary` | Clara Cleary (CASE-CLEAN) | Brand names matching generics across all three sources | **No discrepancies found** |
| 3 | `Montero` | Cristobal567 Montero62 | No interview recorded: FHIR and pharmacy only | **3 findings**, two-source wording; Patient-reported column says "No data" |
| 4 | `Dibbert` | Jona712 Dibbert990 | Patient says they take nothing | **3 findings**; "Patient reports no medications" |
| 5 | `Brandt` | Beatrice Brandt (CASE-BRAND) | A brand the alias list doesn't know, matched by RxNorm: `Crestor` is rosuvastatin | **No discrepancies found** (1.0.0 shows 2 missing here) |
| 6 | `Demopoulos` | Dana Demopoulos (CASE-DEMO) | Ingesting a new patient live | **No Run button**; "No data" for Pharmacy and Patient-reported |

## Points to show on Marcus Mixton

- **Metformin has no finding, and is listed under "No differences":** 500 mg (FHIR, pharmacy) and 0.5 g (patient) are the same dose. The section shows what each source states and doesn't call any of them correct, which is why it doesn't say "validated".
- **Acetaminophen has two findings:** pharmacy lists 500 mg and 1000 mg (duplicate), and the three sources' doses differ (dosage mismatch).
- **RxNorm:** pharmacy's list says `Zoloft`, marked "Matched as: sertraline". It isn't in the alias list, so only RxNorm connects it to FHIR's sertraline.
- **Sertraline:** the patient reported it twice (duplicate). Its frequency also differs: the patient and FHIR say once daily, pharmacy's Zoloft says twice daily. Without the RxNorm match there would be 2 false `missing` findings instead of this comparison. "Once a day", "at bedtime" and FHIR's `QD` all count as once daily, so they don't differ from each other.
- **Ibuprofen:** only the patient reports it. **Omeprazole:** only pharmacy has it. **Metoprolol:** only FHIR has it.
- **Warfarin:** on the FHIR list. The patient-reported and pharmacy cells show **Rejected** badges rather than "Not listed", so a rejection isn't presented as a true omission (the PDF says it in words). Clicking a badge jumps to the Rejected records table, which shows why: dose "ten" and "patient unsure of dose".
- **Say:** the app reports differences for clinician review. It doesn't treat any source as the truth and doesn't recommend treatment.

## Adding the live patient (step 6)

Run this, then search `Demopoulos`. Its FHIR id is assigned when it's posted.

```bash
curl -s -X POST -H 'Content-Type: application/fhir+json' \
  --data @data/fhir/demo/new-patient.json http://localhost:8080/fhir
```

Posting again changes nothing. The patient stays until `docker compose down -v`.

## All imported patients

Findings: D = duplicate, M = missing, DM = dosage mismatch, F = frequency mismatch. FHIR ids are from a fresh import.

| Search | Full name | Identifier | FHIR id | Intake | Findings | Rejected |
|---|---|---|---|---|---|---|
| `Mixton` | Marcus Mixton | CASE-MIXED | 2178 | 5 records | 8: 2 D, 4 M, 1 DM, 1 F | 6 |
| `Cleary` | Clara Cleary | CASE-CLEAN | 2174 | 3 records | 0 | 0 |
| `Brandt` | Beatrice Brandt | CASE-BRAND | 2184 | 1 record | 0 | 0 |
| `Lowe` | Bud153 Stan246 Lowe577 | 98ff8f7e… | 1119 | 8 records | 11: 3 D, 4 M, 3 DM, 1 F | 2 |
| `Montero` | Cristobal567 Alfredo17 Montero62 | c86c400e… | 1271 | **no interview** | 3: 1 D, 1 M, 1 DM | 3 |
| `Walter` | Ezekiel373 Leslie90 Walter473 | 4f083ce3… | 1349 | 3 records | 3: 2 M, 1 DM | 1 |
| `Dibbert` | Jona712 Bonnie873 Dibbert990 | aa616abe… | 1402 | **reports none** | 3: 2 M, 1 DM | 2 |
| `Cummings` | Kristine579 Eboni653 Cummings51 | 87f32e4c… | 1472 | 3 records | 5: 3 M, 1 DM, 1 F | 1 |
| `Nolan` | Leonila462 Candyce305 Nolan344 | 8c42357f… | 1578 | 6 records | 5: 3 M, 1 DM, 1 F | 4 |
| `Auer` | Shalanda398 Kelsie51 Auer97 | 46ee9d82… | 1783 | 5 records | 9: 1 D, 5 M, 2 DM, 1 F | 1 |
| `Erdman` | Tennille443 Denna536 Erdman779 | e74367bd… | 1909 | 2 records | 2: 2 M | 0 |
| `Todd` | Todd315 Adolph80 Effertz744 | 5a3596ef… | 1996 | 4 records | 5: 3 M, 2 DM | 6 |
| `Wallace` | Wallace647 Raymond398 Effertz744 | 5e688e99… | 2090 | 2 records (caregiver) | 1: 1 M | 0 |

## Watch out for

- **Findings use the RxNorm ingredient name:** `metoprolol`, `naproxen`, `fish oils`. The medication tables keep each source's own wording.
- **Frequency wording:** findings say "once daily"; the medication tables keep each source's own wording, such as `QD`. As-needed and unreadable frequencies are never compared, and show as "(not compared)", as on Bud153 Lowe577's FHIR value. A blank frequency shows as "—".
- **No "different form" finding in this data:** pharmacy and intake rows are bare drug names, so they state no dose form to compare. The form and salt checks are covered by automated tests.
- **Numbers in names:** Synthea generates names like `Montero62`. They're real values in the data, not a display bug.
- **`Effertz` finds two patients:** search `Todd` or `Wallace` to get one.
- **Identifier search is exact:** `CASE-MIXED` works; `case-mixed` and partial identifiers find nothing.
- **Avoid Kristine579 Cummings51 as an "intake-only" example:** a seeded-data overlap means Loratadine appears in both intake and pharmacy for this patient, so it isn't intake-only.
- **"No differences" means no finding, not proof of agreement:** a frequency marked "(not compared)" states no schedule, so it may still differ. Rosuvastatin on Leonila462 Nolan344 shows this. A medication with a rejected record isn't listed there.
- **Findings appear only after clicking Run.** The patient page previews the medication lists, and each patient joins Recent patients after their first run.
- **Reset between rehearsals and the real demo,** or runs and the live patient stay in place.
