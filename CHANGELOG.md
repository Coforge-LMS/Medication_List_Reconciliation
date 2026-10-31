# Changelog

Changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html);
the public contract is the HTTP API and persisted data described in the README.

## [Unreleased]

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

[Unreleased]: https://github.com/Coforge-LMS/Medication_List_Reconciliation/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Coforge-LMS/Medication_List_Reconciliation/releases/tag/v1.0.0
