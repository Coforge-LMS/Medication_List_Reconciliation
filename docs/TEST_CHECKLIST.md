# Essential-test checklist

[TEA-50](https://linear.app/team-1-medrec/issue/TEA-50/b10-essential-test-checklist-end-to-end-test)
covers the QUALITY RULES tests below.

## QUALITY RULES → test IDs

- [ ] Validation accepts valid records and rejects invalid inputs with reasons:
  - `tests/ingest/test_ingest_pharmacy.py::test_valid_row_becomes_a_record`
  - `tests/ingest/test_ingest_pharmacy.py::test_a_blank_required_field_is_missing_field`
  - `tests/ingest/test_ingest_pharmacy.py::test_unreadable_doses`
  - `tests/ingest/test_ingest_pharmacy.py::test_units_outside_the_accepted_four_are_unreadable`
  - `tests/ingest/test_ingest_pharmacy.py::test_bad_dates_are_invalid_date`
  - `tests/ingest/test_ingest_pharmacy.py::test_a_future_date_is_future_date`
  - `tests/ingest/test_ingest_pharmacy.py::test_one_row_can_carry_several_reasons`
  - `tests/ingest/test_ingest_pharmacy.py::test_an_unknown_intake_dose_is_rejected_as_patient_unsure`
  - `tests/ingest/test_ingest_fhir.py::test_unreadable_strengths_are_rejected`
  - `tests/ingest/test_ingest_fhir.py::test_malformed_dosage_shapes_do_not_crash`
- [ ] Missing, malformed and invalid alias configurations fail clearly:
  - `tests/ingest/test_ingest_aliases.py::test_missing_file_is_named`
  - `tests/ingest/test_ingest_aliases.py::test_invalid_json_reports_line_and_column`
  - `tests/ingest/test_ingest_aliases.py::test_bad_schema_names_the_field`
- [ ] Duplicate rule has positive and negative cases, including intake:
  - `tests/rules/test_rules_duplicate.py::test_brand_and_generic_in_one_source_is_a_duplicate`
  - `tests/rules/test_rules_duplicate.py::test_one_record_per_source_is_not_a_duplicate`
  - `tests/rules/test_rules_duplicate.py::test_intake_duplicate_is_reported_per_source`
- [ ] Missing rule checks both directions and distinguishes rejections from omissions:
  - `tests/rules/test_rules_missing.py::test_fhir_only_medication_is_missing_from_pharmacy`
  - `tests/rules/test_rules_missing.py::test_pharmacy_only_medication_is_missing_from_fhir`
  - `tests/rules/test_rules_missing.py::test_medication_in_both_sources_is_not_missing`
  - `tests/rules/test_rules_runner.py::test_rejected_counterpart_stays_missing_not_omitted`
  - `tests/rules/test_rules_missing.py::test_intake_only_drug_is_missing_from_fhir_and_pharmacy`
  - `tests/rules/test_rules_missing.py::test_drug_not_reported_by_the_patient`
- [ ] Dosage rule compares sources, including the three-way case:
  - `tests/rules/test_rules_dosage.py::test_different_strength_is_a_mismatch`
  - `tests/rules/test_rules_dosage.py::test_name_in_one_source_only_is_not_a_dosage_mismatch`
  - `tests/rules/test_rules_dosage.py::test_three_way_mismatch_names_every_source`
- [ ] One medication can produce several findings:
  - `tests/rules/test_rules_runner.py::test_one_medication_can_yield_two_findings`
- [ ] A no-discrepancy patient produces no findings:
  - `tests/rules/test_rules_runner.py::test_no_discrepancy_patient_yields_no_findings`
  - `tests/data/test_data_cases.py::test_case_clean_has_no_findings`
- [ ] 500 mg equals 0.5 g through conversion and reconciliation:
  - `tests/contract/test_contract_units.py::test_500_mg_equals_half_gram`
  - `tests/rules/test_rules_dosage.py::test_equivalent_doses_in_other_units_are_not_a_mismatch`
  - `tests/data/test_data_cases.py::test_case_mixed_metformin_is_equal_across_sources`
- [ ] Persistence commits all rows and rolls back failed saves, including after flush:
  - `tests/db/test_db_save.py::test_success_commits_exact_rows_in_all_tables`
  - `tests/db/test_db_save.py::test_success_with_intake_snapshots_intake_rows`
  - `tests/db/test_db_save.py::test_failure_rolls_back_everything_including_patient[not_null_violation]`
  - `tests/db/test_db_save.py::test_failure_rolls_back_everything_including_patient[exception_after_flush]`
  - `tests/db/test_db_save.py::test_failure_leaves_seeded_intake_and_patient_unchanged`
- [ ] End-to-end: detail → reconcile → grouped findings → history → PDF, with committed rows:
  - `tests/e2e/test_e2e_reconcile.py::test_case_mixed_detail_reconcile_history_and_pdf`
  - `tests/e2e/test_e2e_reconcile.py::test_no_interview_patient_keeps_the_two_source_result`

The E2E tests exercise the actual ingestion, normalization, rules, repository,
templates and PDF renderer. The only external service replaced is HAPI: exact
GET URLs map to committed files through `tests/fixtures/hapi/index.json`;
unrecorded requests fail. The flow starts at `/patients/2178` because the recorded
fixtures do not include a patient-list response (TECHNICAL_PLAN §16.3).

## Run locally

With the Compose app database running using the public `.env.example` values:

```sh
# Once: create a separate test database, leaving the demo database intact.
docker compose exec app-db createdb -U medrec medrec_test
export TEST_DATABASE_URL=postgresql+psycopg://medrec:demo_medrec@127.0.0.1:5433/medrec_test
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest tests/e2e -vv
uv run --locked pytest -vv --durations=10
```
