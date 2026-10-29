# Assumptions and Decisions Log

Format: decision / assumption · status · source or reason · owner. Rows are grouped by owner. Each owner reviews their section, edits anything they disagree with, then replaces the marker with `Reviewed by <name>, <date>` (BACKLOG B13).

Status values:
- `Decided`: agreed in the technical plan.
- `Assumed`: our best guess, to confirm with the customer.
- `Open`: needs an answer.

Research citations: [R01]…[R11] = `docs/research/NN-*.md`.

## Rachit Shah: data, validation, terminology
OWNER: Rachit Shah, to review and finalize

| # | Decision / assumption | Status | Source or reason |
|---|---|---|---|
| A1 | Synthetic data only: Synthea for EHR data, a seeded generator for pharmacy data, and a small hand-written deliberate-case FHIR bundle with invented names | Decided | Brief (medical safety); [R01]; [R11] (no PHI) |
| A2 | Patients are keyed on the Synthea `Patient.identifier` (or `urn:medrec:case`), never the HAPI id, which changes on every import. This applies to pharmacy rows and to the app DB `patient.identifier`. | Decided | [R01], [R02], [R03] |
| A3 | Synthea `doseQuantity` has no unit. FHIR dose = strength parsed from the RxNorm display × the unitless count. | Decided | [R01], [R03] (FhirR4.java). B2 re-checks this on the generated bundles. |
| A5 | The deliberate-case bundle (CASE-CLEAN, CASE-MIXED, CASE-BRAND) guarantees every rule, the no-discrepancy case, unit equivalence, rejected-counterpart wording and V2 behaviour, whatever Synthea produces | Decided | Synthea alone can't guarantee these [R03] |
| A6 | Only `status=active` MedicationRequests count as current medications | Assumed | [R01]–[R03]; confirm with a clinician (Q2) |
| A7 | Accepted units are mg, g, mcg and mL. Anything else (tablets, units, puffs, per-mL strengths, combination products) is rejected as `unreadable_dosage`. | Decided | Brief; ISMP prefers "mcg" over "µg" [R11] |
| A8 | Pharmacy `dose_amount` is per administration, matching the FHIR side (strength × doseQuantity) | Decided | Comparability of the dosage rule |
| A9 | The alias list stays deliberately small. The generator picks brands only from it (except CASE-BRAND), so V2's RxNorm normalization visibly reduces false "missing" findings. | Decided | Brief: V2 must show fewer false "missing" |
| A10 | The importer skips only when the last case patient exists, so a partial import is never treated as done | Decided | Red-team review |
| A31 | Patient intake history is simulated from a seeded generator (patient-report patterns on top of Synthea meds) and seeded into the app DB, not typed in a form | Decided | Lead decision 2026-10-29; brief puts forms out of scope; [R11] (patient interview) |
| A32 | An intake item with no usable dose ("not sure") is rejected as `unreadable_dosage` ("patient unsure of dose"), not accepted without a dose | Decided | Lead decision 2026-10-29; keeps the contract's dose required |

## Vedant Misra: persistence, history, compatibility
OWNER: Vedant Misra, to review and finalize

| # | Decision / assumption | Status | Source or reason |
|---|---|---|---|
| A13 | Medication rows are snapshotted per run (not upserted per patient), so history shows exactly what was compared | Decided | [R05], [R10] |
| A14 | Patient upsert + run + snapshot + rejections + findings are saved in ONE transaction. Any failure rolls back all of it. | Decided | Brief; [R05] |
| A15 | `discrepancy_type` is TEXT (no ENUM, no CHECK). V1 renders unknown types as "Other (type)" with the stored summary (tolerant reader). | Decided | [R10] |
| A16 | Schema is applied with `create_all()`, no Alembic. The schema is frozen at 1.0.0 and V2 ships zero DDL. | Decided | [R05], [R10] |
| A17 | History is append-only, with no delete endpoint. It is keyed on the stable patient identifier, so it survives HAPI re-imports. | Decided | Auditability: NPSG.03.06.01 documentation [R11]; [R01] |
| A33 | Intake is two tables: `intake_interview` (who, when, informant, `no_medications`) and `intake_medication` (raw rows as said). Both hang off `patient` by a real FK, and the patient's FHIR columns become nullable. That is 7 tables, one over the brief's "~4–6", because the interview is a real event. It makes "takes nothing" vs "not taken" and who took the history explicit. Intake is snapshotted per run, and each run records which interview it compared. | Decided | Schema decided by the lead's delegate 2026-10-29; brief requires enforced FKs; [R05] snapshot-per-run |
| A26 | Ownership split: FHIR → contract mapping and pharmacy **validation** go to Rachit ("ingestion validation"). Sarthak keeps the FHIR REST **client** and pharmacy record **access**. This balances an overloaded stream; the brief gave both to Sarthak. | Assumed | BACKLOG workload table; needs sign-off from Rachit and Sarthak |

## Sarthak Kakkar: rules, UI, PDF
OWNER: Sarthak Kakkar, to review and finalize

| # | Decision / assumption | Status | Source or reason |
|---|---|---|---|
| A4 | Most Synthea meds have no timing, and a Synthea bug marks some scheduled meds as-needed. Frequency is optional, and PRN or unknown is "not comparable". | Decided | [R01], [R03] |
| A11 | V1 identity = name normalization (bracketed brand tags stripped) + a small alias config. Form and route are not part of V1 identity (documented limitation). | Decided | Brief; [R07] for the V2 tightening |
| A12 | A duplicate is the same normalized name twice **within one source** (any dose). A dosage mismatch compares the **set** of base-unit doses (exact `Decimal`; 500 mg == 0.5 g). | Decided | Brief; closed PR #1 definitions |
| A18 | A `missing` finding whose counterpart was rejected says so in its summary, so a rejection is never presented as an omission | Decided | Red-team review |
| A19 | Finding summaries state facts only; a test bans treatment verbs there. The exact disclaimer text is asserted separately in the UI and PDF. | Decided | Brief; FDA CDS guidance criteria 3–4 [R11] |
| A20 | Stack: FastAPI + Jinja2/HTMX + SQLAlchemy 2.0 + psycopg 3 + httpx + fpdf2 with bundled DejaVu fonts. Exact pins, no upgrades before Friday. | Decided | [R04], [R06] |
| A21 | V1 shows frequency as stored. Plain-language display ("once daily", not "QD") ships with the V2 frequency normalizer, so no V2 logic lands in V1. | Decided | ISMP / Joint Commission guidance [R11]; brief: "no V2 logic in V1" |
| A22 | V2 RxNorm: ingredient-level identity. A different strength, form or route is reported as `dosage_mismatch`, never merged and never split into two "missing" findings. Offline cache; live only when `RXNORM_LIVE=1`. | Decided | [R07] |
| A34 | Reconciliation is three-way per medication over the sources that have data. No source is presented as the truth (patient recall is unreliable). An empty intake list gives the two-source result. | Decided | Lead decision 2026-10-29; [R11] |

## Devang Borkar: containers, CI, releases, privacy
OWNER: Devang Borkar, to review and finalize

| # | Decision / assumption | Status | Source or reason |
|---|---|---|---|
| A24 | Both databases use `postgres:18.6-alpine` (volume at `/var/lib/postgresql`). HAPI v8.12.0-2 was smoke-tested on it. | Decided | Smoke test 2026-10-29 (`/fhir/metadata` OK in 16 s); [R05]. [R08] preferred PG 16 but had not tested 18. |
| A25 | PR CI runs lint + pytest with a Postgres service. The E2E test uses recorded HAPI responses. The full Compose stack with HAPI is rehearsed by hand before releases and the demo. | Decided | [R09] (HAPI start and pull time vs PR budget) |
| A27 | App data files (aliases, pharmacy dataset, RxNorm cache) are baked into the app image, and release images are built from tag worktrees with a revision label, so a rollback is genuine | Decided | [R10]; red-team review |
| A28 | Rollback = run the 1.0.0 image on the same volume (no restore). Always back up first. | Decided | [R10] |
| A29 | No authentication; local demo only; ports bound to 127.0.0.1 | Decided | Brief (auth out of scope) |
| A30 | Branch protection: 2 required checks, 1 approval, `strict: false` (the repo is public, so protection is available) | Decided | [R09]; 17 PRs tonight |
| A35 | A one-shot `app-seed` Compose service seeds intake before the app starts; the intake CSVs are baked into the app image | Decided | Same pattern as the HAPI importer; [R08] |
| A36 | `infra/docker-compose.yml` (on main) is the single Compose file. A root `compose.yaml` that `include`s it keeps `docker compose up` working from the repo root. DB passwords are currently in `infra/hapi.env` (PR #12). B9 moves them to a gitignored `.env` with a committed `.env.example`; `hapi.env` keeps the non-secret HAPI settings. | Decided | Rachit + Devang decision 2026-10-29; brief: `docker compose up`, no secrets in git |
| A37 | The FHIR request shapes are the `tests/fixtures/hapi/index.json` keys on main. The patient list is live-only (no fixture), so the E2E starts at the patient detail page. | Decided | Rachit + Devang decision 2026-10-29 |

## Customer questions

Drafted from domain research [R11]. Each owner refines theirs.

| # | Question | Owner |
|---|---|---|
| Q1 | How do your clinicians write and read drug names and frequencies today (brand vs generic, "BID" vs "twice daily")? Would brand and generic side by side help, or add noise? | OWNER: Rachit Shah, to review and finalize |
| Q2 | Which discrepancy types do you see most and care about most (omission, duplication, dose, frequency, route)? How do you tell an intentional difference from an unintended one at review? | OWNER: Sarthak Kakkar, to review and finalize |
| Q3 | After a reconciliation, what do you need on record (who, when, which source lists, which findings), and for how long? Would a PDF filed to the chart meet that? | OWNER: Vedant Misra, to review and finalize |
| Q4 | Would a report-only tool that never suggests an action fit your workflow? What disclaimer wording and export restrictions would your organization expect? | OWNER: Devang Borkar, to review and finalize |
| Q5 | When the EHR list and pharmacy fills disagree, which do you trust more? How should the tool treat OTC, herbal and as-needed drugs that fill data may miss? | OWNER: Sarthak Kakkar, to review and finalize |
| Q6 | OWNER: Rachit Shah, to author: ______ | Rachit |
| Q7 | OWNER: Vedant Misra, to author: ______ | Vedant |
| Q8 | OWNER: Sarthak Kakkar, to author: ______ | Sarthak |
| Q9 | OWNER: Devang Borkar, to author: ______ | Devang |
