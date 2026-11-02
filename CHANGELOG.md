# Changelog

Changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html);
the public contract is the HTTP API and persisted data described in the README.

## [Unreleased]

## [1.1.0] - 2026-11-02

### Added

- Frequency mismatch findings across comparable patient-reported, FHIR and
  pharmacy schedules, with deterministic normalization of equivalent wording.
- Offline RxNorm cache matching brands to ingredients while preserving original
  source values, strength differences, salts, forms and routes; optional live
  RxNav resolution and NLM attribution.
- A no-differences section showing medications shared by all compared sources,
  with unavailable or unrecognized frequencies marked as not compared.

### Changed

- Release builds accept lightweight and annotated Git tags, resolve the tag to
  its commit and verify the image revision and application version.

### Compatibility

- No schema changes. Version 1.0.0 can read newer saved runs and displays the
  new finding type as `Other (frequency_mismatch)`, including stored summaries.
- Rollback retains the same database volume and all newer history.

## [1.0.0] - 2026-10-31

### Added

- Three-source medication reconciliation: FHIR, synthetic pharmacy records and
  patient-reported intake; missing intake retains the two-source result.
- Duplicate, missing and dosage mismatch rules, alias matching and equivalent
  dose conversion, with explicit rejection reasons for invalid records.
- Patient search, medication detail, grouped findings, history, JSON API and
  PDF reports, including no-discrepancy and no-interview cases.
- Atomic PostgreSQL persistence of each run and its source snapshots, rejected
  records, findings and app version; idempotent intake seeding.
- Six-service Docker Compose stack with health/startup gates, pinned dependencies
  and locally built release images from annotated tags with OCI revision labels.
- Verified app-database backups: scratch restore plus matching per-table counts.
- GitHub Actions lint and PostgreSQL tests, recorded-FHIR E2E coverage, an
  essential-test checklist and a synthetic demo patient walkthrough.

### Compatibility

- Finding types remain open TEXT; unknown types render as `Other (<value>)` in
  stored history, run pages and PDFs for forward-compatible rollback.
- Future changes must preserve the HTTP and persisted-data contracts; rollback
  swaps the app image while retaining the existing database and newer runs.

[Unreleased]: https://github.com/Coforge-LMS/Medical_List_Reconciliation/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Coforge-LMS/Medical_List_Reconciliation/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Coforge-LMS/Medical_List_Reconciliation/releases/tag/v1.0.0
