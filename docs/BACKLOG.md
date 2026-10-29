# Backlog (Linear-ready)

Project: **Team 1: Medication List Reconciliation** (Linear team TEA). Two release groups: **V1 (1.0.0)**, 17 tickets, and **V2 (1.1.0)**, 3 tickets. In Linear, B*n* = TEA-(40+*n*), **B0 = TEA-58**, **B1b = TEA-59** and **B6b = TEA-60** (intake update, see the end of this file).

**Gate:** every code ticket (B2–B11, B15–B17) is blocked by **B0**. No code PR merges to `main` until CI runs on GitHub, branch protection is on, and a teammate has approved the PR.

**Conventions:**
- Due times are Thu 2026-10-29 EDT and assume the plan is approved around 11:15.
- Priority: P1 urgent, P2 high.
- Branch `<owner>/<topic>`. PR title starts with the TEA id. The commit author is the owner.

## V1: Release 1.0.0

**B0 · CI on GitHub Actions + branch protection (prerequisite for all code PRs)**
- Owner Devang · V1 · P1 · 1 h · due 12:00 · blocked by none · `devang/ci`
- `.github/workflows/ci.yml` runs on PRs to `main` and pushes to `main`. It has two jobs, which become the required checks:
  - `lint`: `uv sync --locked`, `ruff check .`, `ruff format --check .`
  - `test`: `uv run pytest` with a `postgres:18.6-alpine` service and `TEST_DATABASE_URL` set
- Best practice: `permissions: contents: read`, a concurrency group per ref, `timeout-minutes`, `ubuntu-24.04`, actions pinned to commit SHAs.
- Also adds a PR template and `CODEOWNERS` (owners per TECHNICAL_PLAN §9).
- After a teammate approves and CI is green, apply branch protection on `main`: required checks lint + test, 1 approval with stale reviews dismissed, conversation resolution, no force-push or deletion, `enforce_admins: true`.
- AC:
  - [ ] Both checks pass on this PR itself, with the Postgres service reachable.
  - [ ] `gh api …/branches/main/protection` shows the settings above.
  - [ ] A PR without an approval, or with a failing check, can't be merged, admins included.
  - [ ] Opening a PR auto-requests the area owner (CODEOWNERS).

**B1 · Scaffold + shared contract + alias config schema**
- Owner Vedant · V1 · P1 · 1.5 h · due 12:45 · blocked by none · `vedant/foundation`
- Creates `pyproject.toml` + `uv.lock` with the pinned stack, ruff/pytest config, `tests/conftest.py` (lazy engine, TRUNCATE, `_test` guard), and a stub `app/main.py` with `/healthz` and the tomllib version.
- Implements `contract/` (MedicationRecord, Reason, Rejection, Finding, ReconciliationInput, units, AliasConfig + AliasConfigError) exactly as TECHNICAL_PLAN §4. The contract is frozen after merge.
- AC:
  - [ ] `uv lock` resolves and `uv run pytest` passes, including a TestClient `/healthz` smoke test.
  - [ ] `tests/contract` covers 500 mg == 0.5 g, unit spellings (µg→mcg), unknown-unit rejection and AliasConfig schema errors.
  - [ ] `ruff check` and `ruff format --check` are clean.

**B2 · Synthea data, deliberate-case bundle, HAPI import, recorded fixtures**
- Owner Rachit · V1 · P1 · 2.5 h · due 14:30 · blocked by none · `rachit/fhir-data`
- Run Synthea v4.0.0 once in Docker with seed 42 (10 alive adults aged 45–85, R4 transaction bundles, US Core off, include-list, 5 years of history) and commit `data/fhir/synthea/`.
- Hand-write `data/fhir/cases/medrec-cases.json`: 3 invented patients (`urn:medrec:case`) with full `dosageInstruction`, covering:
  - CASE-CLEAN: one alias match, otherwise identical.
  - CASE-MIXED: duplicate + dosage mismatch on the same drug, one missing on each side, 500 mg vs 0.5 g, a frequency difference, and a drug whose only pharmacy row is invalid.
  - CASE-BRAND: a brand not in the alias list.
- Write `infra/hapi.env` (shipped in PR #12; B9 later moves the DB passwords out of it into a gitignored `.env`) and the stdlib `infra/import_fhir.py`. Load order is hospital → practitioner → patients → cases. The script skips the import if CASE-BRAND exists and fails loudly on any transaction error.
- Record real HAPI responses for the case patients into `tests/fixtures/hapi/`.
- AC:
  - [ ] Against a local HAPI, the import gives `Patient?_summary=count` = 13, and a second run is a no-op.
  - [ ] `data/README.md` holds the exact generation command and a tally of active MedicationRequests with and without dose/timing (this checks A3/A4).
  - [ ] The fixtures cover the Patient search, `Patient/{id}` and `MedicationRequest?patient=…&status=active` for each case patient.

**B3 · Seeded pharmacy dataset generator**
- Owner Rachit · V1 · P1 · 1.5 h · due 16:30 · blocked by B1, B2, B4 · `rachit/pharmacy-data`
- `data/generators/make_pharmacy.py --seed 42` writes `data/pharmacy/pharmacy_records.json`. Rows: `record_id, patient_id, medication_name, dose_amount, dose_unit, frequency, date_recorded`. Values are strings; `dose_amount` is per administration.
- Synthea patients get seeded perturbations of FHIR meds that pass B4 validation: drop, dose change, duplicate, brand names taken only from `aliases.json`, frequency text. No mL rows.
- Case patients get scripted rows plus invalid ones: blank name, dose "ten", unit "tab", bad date, future date.
- AC:
  - [ ] Re-running produces a byte-identical file (test).
  - [ ] Every scenario type in the brief appears at least once (test counts them).
  - [ ] No real patient data.

**B4 · Ingestion: FHIR mapping, pharmacy validation, alias loading, normalization**
- Owner Rachit · V1 · P1 · 3 h · due 15:30 · blocked by B1 · `rachit/ingest`
- `ingest/fhir.py` maps Patient and MedicationRequest JSON to records or rejections: strength from the RxNorm display, frequency string, skip inactive.
- `ingest/pharmacy.py` validates rows. `ingest/aliases.py` loads `data/aliases.json` with clear `AliasConfigError` messages. `ingest/normalize.py` sets `normalized_name` (TECHNICAL_PLAN §4.3).
- Rejections keep the readable name, so rules can tell "rejected" from "absent".
- AC:
  - [ ] Every rejection code has a test, plus one multi-reason record.
  - [ ] FHIR cases tested: `24 HR … 500 MG …` → 500 mg; `[Lipitor]` stripped; missing dosage; combination product rejected; inactive skipped.
  - [ ] Missing file, invalid JSON and bad schema each give a distinct, readable error.

**B5 · App DB: schema, atomic save, history, persistence tests**
- Owner Vedant · V1 · P1 · 3 h · due 15:30 · blocked by B1 · `vedant/db`
- `db/models.py` has the 5 tables of §5: `discrepancy_type` is TEXT and `patient.identifier` is UNIQUE.
- `db/session.py` builds the engine lazily and provides the session dependency.
- `db/repo.py` provides `init_db`, `save_run(...)` (one transaction including the patient upsert on `identifier`), `get_run` and `list_runs(identifier)`.
- AC:
  - [ ] Success test asserts exact row counts in all 5 tables.
  - [ ] NOT NULL failure and exception-after-flush each leave 0 rows in every table, read from a fresh connection. A direct insert with a bad `run_id` raises IntegrityError.
  - [ ] An unknown `discrepancy_type` round-trips; V2 columns are nullable; history is newest first and survives a changed HAPI id.

**B6 · Rules: ReconciliationRule + Duplicate / Missing / DosageMismatch + runner**
- Owner Sarthak · V1 · P1 · 2.5 h · due 15:00 · blocked by B1 · `sarthak/rules`
- `rules/base.py` defines the abstract `evaluate(data: ReconciliationInput) -> list[Finding]`. Three subclasses plus `run_rules` and `DEFAULT_RULES`, with definitions exactly as §4.6, including the rejected-counterpart wording for `missing`.
- Tests build contract objects directly.
- AC:
  - [ ] Each rule has positive and negative tests; 500 mg vs 0.5 g gives no finding.
  - [ ] One medication yields 2 findings; a no-discrepancy patient yields 0; a rejected counterpart is named in the `missing` summary.
  - [ ] No finding summary contains increase/decrease/stop/start/discontinue/should/recommend.

**B7 · Web app: FHIR client, pharmacy access, service, pages, JSON API**
- Owner Sarthak · V1 · P1 · 3.5 h · due 17:00 · blocked by B1 (integrates B4, B5, B6 as they merge) · `sarthak/web`
- `app/fhir_client.py`: httpx with an injectable transport; follows `next` links.
- `app/pharmacy.py`: reads the baked dataset.
- `app/service.reconcile`: the §7.1 pipeline.
- Routes and templates from §6: list, detail with both lists and rejections, run page grouped by type, per-patient history.
- `app/labels.py`: `LABELS.get(t, f"Other ({t})")`.
- Footer carries the version and disclaimer. Frequency is shown as stored; HTMX is optional.
- AC:
  - [ ] The pager test passes over a two-page MockTransport bundle.
  - [ ] The run page groups findings by type with FHIR value vs pharmacy value. An unknown type renders "Other (x)" (test). The disclaimer text is present (test).
  - [ ] The two JSON endpoints and `/healthz` return the documented shapes.

**B8 · PDF report export**
- Owner Sarthak · V1 · P1 · 1.5 h · due 16:30 · blocked by B1, B6 · `sarthak/pdf`
- `app/pdf.py` (fpdf2 + bundled DejaVu regular/bold) contains: patient details, timestamp, version, FHIR and pharmacy tables, rejected records, findings grouped by type with compared values, a summary, and the disclaimer.
- Route: `GET /runs/{id}/report.pdf`.
- AC:
  - [ ] Output starts with `%PDF-`; pypdf text includes the patient name and the exact disclaimer.
  - [ ] A zero-findings run says "No discrepancies found".
  - [ ] An unknown type, "µg" and an em dash render correctly.

**B9 · Dockerfile + Compose stack**
- Owner Devang · V1 · P1 · 2.5 h · due 16:00 · blocked by B1, B2 · `devang/compose`
- `infra/Dockerfile`: `python:3.12.16-slim-trixie`, `uv sync --locked`, non-root, urllib healthcheck. It bakes in app code, `pyproject.toml`, `data/aliases.json` and `data/pharmacy/`.
- Extend `infra/docker-compose.yml` (from PR #12) with app-db, app and the one-shot app-seed, plus a root `compose.yaml` that `include`s it. Move the DB passwords out of `infra/hapi.env` into a gitignored `.env`; `hapi.env` keeps the non-secret HAPI settings. Includes healthchecks (`pg_isready -h 127.0.0.1`), depends_on conditions, named volumes at `/var/lib/postgresql`, ports on 127.0.0.1, `image: medrec-app:${APP_VERSION:?}`, and a committed `.env.example` with `APP_VERSION=dev` and the DB passwords.
- AC:
  - [ ] On a clean clone, `cp .env.example .env && docker compose up -d --build` brings every service healthy with the importer exited 0. Timings logged.
  - [ ] `down` then `up` keeps data; `down -v` resets it. The app service has no hapi-db credentials.
  - [ ] No secrets committed.

**B10 · Essential-test checklist + end-to-end test**
- Owner Devang · V1 · P1 · 1.5 h · due 18:00 · blocked by B0, B2, B4, B5, B6, B7 · `devang/e2e`
- CI and branch protection moved to B0.
- `tests/e2e/test_e2e_reconcile.py`: TestClient + real Postgres (the CI service) + MockTransport serving `tests/fixtures/hapi/` by URL.
- AC:
  - [ ] The E2E test covers list → detail → reconcile → run page (CASE-MIXED grouped findings) → history → PDF 200, and asserts persisted rows.
  - [ ] Checklist in the PR: every QUALITY RULES test maps to a passing test id in the CI log.
  - [ ] PR CI stays under 5 min.

**B11 · Release 1.0.0: README, CHANGELOG, tag, image, backup/restore**
- Owner Devang · V1 · P1 · 1.5 h · due 19:45 · blocked by B2–B10, B12 · `devang/release-1.0.0`
- README covers prerequisites, startup, usage, release, rollback, and backup/restore with the compatibility rule.
- CHANGELOG `[1.0.0]`; tag `v1.0.0` + `gh release create`.
- `scripts/build_release.sh` and `scripts/backup.sh`.
- AC:
  - [ ] Every V1 Definition-of-Done item is ticked, with evidence in the release notes.
  - [ ] The backup restores into `medrec_restore_check` with matching row counts (output in the README).
  - [ ] README commands were run verbatim on a `down -v` stack; image `medrec-app:1.0.0` carries the tag's revision label.

**B12 · Customer research + client brief**
- Owner Rachit · V1 · P2 · 1 h · due 19:00 · blocked by none · `rachit/client-brief`
- Get the research PR merged.
- Write `docs/CLIENT_BRIEF.md`: one page, citing only sources already fetched in R11 (who reconciles, current workflow, discrepancy types and harm, our scope and safety stance).
- AC:
  - [ ] Research docs are on main.
  - [ ] CLIENT_BRIEF fits on one page, and every claim links to a source.

**B13 · Questions and assumptions log + owner sign-off**
- Owner Rachit (board owner; tracks each member's sub-item) · V1 · P2 · 0.5 h each · due 23:59 · blocked by none · `<name>/signoff`
- Each member reviews their `OWNER:` sections in `docs/research/` and `docs/ASSUMPTIONS.md`, corrects them, and replaces the marker with `Reviewed by <name>, <date>`.
- Each member also writes their own customer question (Q6–Q9).
- AC:
  - [ ] No `to review and finalize` markers remain.
  - [ ] Q6–Q9 are written by their owners (commit author = owner).

**B14 · Presentation page, checklist, demo runbook**
- Owner Devang (shell + runbook; sub-items for each member's section) · V1 · P2 · 2 h · due 23:59 · blocked by B11 (V2 slides after B17) · `devang/presentation`
- `docs/presentation/index.html`, in the order Rachit → Vedant → Sarthak → Devang → live demo.
- `docs/PRESENTATION_CHECKLIST.md`: research, implementation, tests, PRs and likely questions for each member.
- The demo runbook has a fallback for each failure: HAPI down → pytest E2E on fixtures; app down → saved PDF + screenshots. It also schedules a dry run on Friday morning, before the presentation.
- AC:
  - [ ] Each section is authored by its owner.
  - [ ] The runbook was executed once end to end, including one fallback path.

## V2: Release 1.1.0 (exactly two features)

**B15 · Frequency mismatch: 4th rule + deterministic normalization**
- Owner Sarthak · V2 · P2 · 2 h · due 21:30 · blocked by B6 (to start, ~15:00) and B11 (to merge) · `sarthak/frequency-rule`
- `rules/frequency.py` holds the normalizer (`QD|BID|TID|QID|QOD|QW|PRN|n/d`, time-of-day collapses) and `FrequencyMismatchRule`, appended to `DEFAULT_RULES`.
- `app/labels.py` gains the label and plain-language display. No schema, route or other owners' files change.
- AC:
  - [ ] Normalizer table test: BID / "twice daily" / `2/1d` / Q12H → BID; PRN and unknown → not comparable.
  - [ ] CASE-MIXED yields exactly one `frequency_mismatch`; CASE-CLEAN still yields 0.
  - [ ] The diff touches only `rules/`, `app/labels.py` and tests.

**B16 · RxNorm normalization with offline cache**
- Owner Sarthak (terminology review: Rachit) · V2 · P2 · 2.5 h · due 21:30 · blocked by B4 (to start) and B11 (to merge) · `sarthak/rxnorm`
- `data/generators/build_rxnorm_cache.py` (live RxNav, run once) writes `data/rxnorm_cache.json`.
- `ingest/rxnorm.refine(records)` resolves cache first (live only when `RXNORM_LIVE=1`), sets `rxcui` and the ingredient `normalized_name`, and keeps original names. It is called from `app/service`.
- Strength differences stay `dosage_mismatch`. Form/route differences are reported as `dosage_mismatch` ("different form"), never merged [R07]. NLM attribution goes in the footer.
- AC:
  - [ ] CASE-BRAND: the brand not in the alias list matches its generic (V1: 2 `missing` → V2: 0).
  - [ ] Tests: 10 mg vs 20 mg is still a mismatch; ER vs IR is reported, not merged; resolution works offline from the cache.
  - [ ] Saved rows carry `rxcui`; no new tables or columns.

**B17 · Release 1.1.0 + rollback verification**
- Owner Devang · V2 · P2 · 1 h · due 22:30 · blocked by B15, B16 (B15 only, if scope-cut step 5 applies) · `devang/release-1.1.0`
- CHANGELOG `[1.1.0]`; tag `v1.1.0`; rebuild both images from their tags.
- Run the rollback demo of TECHNICAL_PLAN §12 on the same volume and record it in the README.
- AC:
  - [ ] A backup is taken and verified before switching.
  - [ ] After rollback, `/healthz` says 1.0.0, the image revision equals `git rev-list -n1 v1.0.0`, and the 1.1.0 runs show "Other (frequency_mismatch)" with summaries.
  - [ ] Rolling forward to 1.1.0 restores the full labels.

---

## Critical path
**B0 (CI + branch protection) and B1** → B4 + B5 + B6 (parallel) → B7 → B10 (E2E) → B11 **v1.0.0** → merge B15 + B16 → B17 **v1.1.0 + rollback** → B14.
B2 is on the path for B3, B9 and B10. B12 must merge before B11.

## What each member can start immediately
- **Rachit:** B2 (Synthea run, case bundle, importer against a local HAPI) and B12. Neither needs the contract.
- **Vedant:** B1 now. B5 the moment B1 merges.
- **Sarthak:** after B1 merges (~12:45), B6 and B7 in parallel streams; B8 after B6.
- **Devang:** **B0 first.** It's the gate for every code merge. Then the B9 skeleton (HAPI + both DBs need no app code).

## Workload (estimated hours)
| Member | Tickets | Hours |
|---|---|---|
| Rachit | B2 2.5, B3 2.5 (incl. intake), B4 3.25, B12 1, B13 0.5 | **9.75** |
| Vedant | B1 1.5, B1b 0.5, B5 4 (incl. intake), B13 0.5, integration and review ~2 | **8.5** |
| Sarthak | B6 2.5, B6b 1, B7 4, B8 2, B15 2, B16 2.5, B13 0.5 | **14.5** ⚠ |
| Devang | B0 1, B9 2.75, B10 1.75, B11 1.5, B14 2, B17 1, B13 0.5 | **10.5** |

⚠ Sarthak's load follows the ownership fixed in the brief. Two things keep it in budget:
- His V1 work runs as two parallel streams with disjoint files (rules + PDF, web + service), and V2 starts from the merged rules before v1.0.0.
- FHIR → contract mapping and pharmacy validation sit with Rachit, under his "ingestion validation" ownership (ASSUMPTIONS A26, to confirm). Sarthak keeps the FHIR REST client and pharmacy record access.

## Linear sync plan (not executed; waiting for the lead's confirmation)
- **Mark Done:** TEA-5 (decisions session, superseded by this plan).
- **Cancel** TEA-7 … TEA-38 with the comment "superseded by the web-app plan, see docs/BACKLOG.md". TEA-7 is the closed PR #1.
- **Retitle** TEA-39 (dry run) and TEA-40 (presentation) and attach them under B14.
- **Create** B1–B17 in dependency order, with owner, estimate, due date, priority, labels (`V1`/`V2` + area) and blocked-by relations.

## Intake update and Monday re-plan (2026-10-29)

Patient intake history is a third source with the final 7-table schema (TECHNICAL_PLAN §16). The presentation moved to **Mon 2026-11-02**. Linear is already updated: dates, intake sections, the two new tickets below, and closed coordination threads.

**B1b · Contract: intake as a third source**
- Owner Vedant · V1 · P1 · 0.5 h · due **Fri 10/30 10:00** · blocks B4, B5, B6b, B7, B8.
- `Source` gains `"intake"`; `ReconciliationInput.intake: list | None` (None = no interview, `[]` = takes nothing); `Finding.intake_value`; `IntakeInterviewInfo`; `RunDetail.intake` + `intake_interview`.
- It was auto-closed by a docs PR title and has been reopened.

**B6b · Three-way rules**
- Owner Sarthak · V1 · P1 · 1 h · due **Fri 10/30** · blocked by B1b · blocks B10, B11.
- Intake takes part when it isn't None. `missing` reports `present_in` / `missing_from` lists; `dosage_mismatch` fires across 2 or more sources; `duplicate` is per source.
- AC includes a None-vs-`[]` test.

**B0b · Finish branch protection** (new)
- Owner Devang · 0.25 h · due **Fri 10/30 12:00**.
- Turn on stale-review dismissal and conversation resolution (still off after B0).

**B18 · Instructor sign-off on deviations** (new)
- Owner Vedant · 0.5 h · due **Fri 10/30 17:00**.
- Written OK for TECHNICAL_PLAN §14, including the intake, three-source and 7-table changes; record it in ASSUMPTIONS A23.

| Changed ticket | Intake / decision delta | Extra | Due |
|---|---|---|---|
| B3 | two CSVs (interviews + medications); one `no_medications` and one un-interviewed Synthea patient; name-coverage test; three-way expectations in data/README | +1.25 h | Fri 10/30 |
| B4 | `validate(rows, source="intake")`, rows dated by interview; unknown dose rejected | +0.25 h | Fri 10/30 |
| B5 | 7-table schema, `db/seed.py`, `latest_intake_for`, `intake_interview_id` on run, tests | +1.5 h | Fri 10/30 |
| B7 | decided request shapes; pipeline step; three columns; interview line (3 states) | +0.5 h | Fri 10/30 |
| B8 | interview line, patient-reported table, three values | +0.5 h | Fri 10/30 |
| B9 | extend `infra/docker-compose.yml` (app-db, app, app-seed); root `compose.yaml` include; passwords out of `hapi.env` | +0.5 h | Fri 10/30 |
| B10 | decided fixture keys; E2E starts at `/patients/2178`; seeds intake; three-way assertions | +0.25 h | Sat 10/31 |
| B11 | unchanged scope | — | Sat 10/31 |
| B12 / B13 | unchanged scope | — | Fri 10/30 / Sun 11/1 |
| B14 | dry run moved to Mon AM | — | Sun 11/1 |
| B15 / B16 / B17 | RxNorm back in scope | — | Sun 11/1 |

Critical path: **B1b (Fri 10:00)** → B4 / B5 / B6b → B7 → B10 (Sat) → B11 **v1.0.0** (Sat) → B15 + B16 → B17 **v1.1.0 + rollback** (Sun) → dry run (Mon AM).

Updated workload (hours): Rachit 10.0 · Vedant 9.5 · Sarthak 14.5 ⚠ · Devang 11.0. Sarthak's load is still the highest; with the weekend, V2 work spreads to Sunday.
