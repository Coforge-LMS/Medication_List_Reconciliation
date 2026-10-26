# Medication List Reconciliation

Team 1, Week 3. A Python CLI tool, packaged in Docker, that reads two medication lists per patient (clinic intake form + pharmacy), rejects bad records with reasons, flags duplicates, dose mismatches and missing items, saves every reconciliation to SQLite (one transaction per run), and prints a nurse-facing report.

> **The tool flags and reports. It never recommends treatment.** All data in this repo is synthetic; never add real patient information.

Releases: **1.0.0** (duplicate, dose mismatch, missing item) and **1.1.0** (adds the unrecognized-medication-name rule). Rollback 1.1.0 → 1.0.0 keeps history.

Team: Rachit Shah (intake & validation) · Vedant Misra (SQLite storage) · Sarthak Kakkar (rules, report, CLI) · Devang Borkar (Docker, CI, release, README).

Task board: [Linear — Team 1: Medication List Reconciliation](https://linear.app/team-1-medrec/project/team-1-medication-list-reconciliation-cafde8ad7add). See [PLAN.md](PLAN.md) for repo ownership, merge order, CI, task list and schedule. Usage and real output are added in the release week (Devang).

## Workflow rules
- Feature branch per task (`<name>/<topic>`, e.g. `rachit/loader`); merge by PR only, never commit to `main`.
- CI must pass on every PR; keep `main` green. Pull/rebase on `main` daily.
- PR title starts with the Linear ID (`TEA-12 Feature: ...`); paste the PR link into the Linear issue.
- Commits carry your full name as git author; message `[<FirstName>] <area>: <summary> (TEA-<n>)`.
- Secrets go in `.env` (gitignored), never committed. Only synthetic data.
- AI use is allowed, but you must be able to explain every line you submit.

The section below changes only through a PR approved by all four members.

## Shared Decisions

### Input files
- Format **CSV** (stdlib `csv.DictReader`, nurse-readable, diffable). UTF-8, header row required, exact columns:
  `patient_id,medication_name,dose_amount,dose_unit,frequency,source,date_recorded`
- Naming: `data/input/<patient_id>_clinic.csv`, `data/input/<patient_id>_pharmacy.csv` (e.g. `P003_clinic.csv`).
- All data synthetic: patient IDs `P001…P099`, no names/DOB/addresses anywhere.

### Medication record (`models.Medication`, frozen dataclass)
| field | type | rule |
|---|---|---|
| patient_id | str | `^P\d{3}$`, must match the file's patient |
| medication_name | str | non-empty, kept as typed (for the report) |
| normalized_name | str | set by intake: lowercase, trim, collapse spaces, then alias → generic |
| dose_amount | float | > 0 |
| dose_unit | str | one of `mg, mcg, g, mL, units` (case-insensitive in; `ug`/`µg`→`mcg`) |
| frequency | str | normalized code: `QD, BID, TID, QID, QHS, PRN, QW` (`daily/once daily/od`→QD, `twice daily/bd`→BID, `three times daily`→TID, `four times daily`→QID, `at bedtime/nightly`→QHS, `as needed`→PRN, `weekly`→QW) |
| source | str | `clinic` or `pharmacy`, must match filename |
| date_recorded | datetime.date | ISO `YYYY-MM-DD`, not in the future |

Rejections: `RejectedRecord(source_file, line_no, raw: dict, reasons: list[str])`. Reason codes: `MISSING_FIELD:<name>`, `BAD_DOSE`, `UNKNOWN_UNIT`, `UNKNOWN_FREQUENCY`, `BAD_DATE`, `FUTURE_DATE`, `BAD_SOURCE`, `PATIENT_MISMATCH`. A record may have several reasons. Missing file / bad header → `InputFileError` (exit 3), not a rejection.

### Matching + alias config
Two medications match iff same `patient_id` and same `normalized_name`. Dose/frequency are **not** part of matching (that's what dose mismatch checks). `config/aliases.json`:
```json
{
  "version": 1,
  "aliases": { "tylenol": "acetaminophen", "advil": "ibuprofen", "motrin": "ibuprofen",
               "lipitor": "atorvastatin", "glucophage": "metformin", "zestril": "lisinopril",
               "norvasc": "amlodipine" },
  "known_generics": ["acetaminophen", "ibuprofen", "atorvastatin", "metformin",
                     "lisinopril", "amlodipine", "simvastatin", "levothyroxine", "omeprazole"]
}
```
Keys lowercase. `known_generics` ships in 1.0.0 (unused) so 1.1.0 needs no config-format change.

### Rule definitions (unit conversion: g→mg ×1000, mcg→mg ÷1000 before comparing)
| rule_id | definition | example | severity |
|---|---|---|---|
| `DUPLICATE` | same normalized name appears >1× **within one source** | clinic lists "Tylenol 500 mg BID" and "acetaminophen 500 mg BID" | medium |
| `DOSE_MISMATCH` | matched in both sources but amount/unit **or** frequency differ (`details` says which) | clinic metformin 500 mg BID vs pharmacy metformin 1000 mg BID | high |
| `MISSING_ITEM` | in one source, absent from the other; `details.missing_from` = `pharmacy` or `clinic` | pharmacy dispenses lisinopril 10 mg QD, clinic list has no lisinopril | high |
| `UNRECOGNIZED_NAME` (**1.1.0**) | normalized name not in aliases values or `known_generics` | clinic lists "Zorbex 20 mg QD" | low |

- **Two rules on one med**: clinic lists ibuprofen twice (DUPLICATE) and pharmacy ibuprofen differs in dose (DOSE_MISMATCH) → both findings.
- **Perfect match**: zero findings → report prints `No discrepancies found: all N medications match between clinic and pharmacy lists.`
- Wording rule: findings describe facts ("listed at 500 mg in clinic, 1000 mg at pharmacy — please review"). Never "increase/stop/change".

### Finding (what rules return, storage saves, report prints)
```python
@dataclass(frozen=True)
class Finding:
    rule_id: str          # free text, NOT an enum in the DB (rollback-safe)
    patient_id: str
    medication: str       # normalized_name
    severity: str         # "high" | "medium" | "low"
    message: str          # nurse-facing, factual, no treatment advice
    details: dict[str, str] = field(default_factory=dict)  # e.g. {"clinic": "500 mg BID", "pharmacy": "1000 mg BID"}
```

### SQLite schema (`src/medrec/storage/schema.sql`, `PRAGMA user_version = 1`)
```sql
CREATE TABLE IF NOT EXISTS runs (
  run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id     TEXT NOT NULL,
  started_at     TEXT NOT NULL,            -- ISO-8601 UTC
  tool_version   TEXT NOT NULL,            -- "1.0.0" / "1.1.0"
  clinic_file    TEXT NOT NULL,
  pharmacy_file  TEXT NOT NULL,
  accepted_count INTEGER NOT NULL,
  rejected_count INTEGER NOT NULL,
  finding_count  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  finding_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
  rule_id      TEXT NOT NULL,
  medication   TEXT NOT NULL,
  severity     TEXT NOT NULL CHECK (severity IN ('high','medium','low')),
  message      TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_patient ON runs(patient_id);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
```
- DB path env var **`MEDREC_DB_PATH`**, default `data/medrec.db` locally; Docker sets `/data/medrec.db` on volume `medrec-data`. `--db` flag overrides both. `*.db` gitignored.
- 1.1.0 **must not change the schema** (`user_version` stays 1). 1.0.0 report prints unknown `rule_id`s generically, so rows written by 1.1.0 still display after rollback.

### Interfaces (stubs land in the skeleton PR; bodies `raise NotImplementedError`)
```python
# src/medrec/models.py  (FROZEN after skeleton; change = PR approved by all 4)
@dataclass(frozen=True)
class Medication: patient_id: str; medication_name: str; normalized_name: str
                  dose_amount: float; dose_unit: str; frequency: str; source: str; date_recorded: date
@dataclass(frozen=True)
class RejectedRecord: source_file: str; line_no: int; raw: dict[str, str]; reasons: list[str]
@dataclass(frozen=True)
class LoadResult: accepted: list[Medication]; rejected: list[RejectedRecord]
@dataclass(frozen=True)
class Finding: ...  # 1.5
@dataclass
class RunRecord: patient_id: str; started_at: str; tool_version: str; clinic_file: str
                 pharmacy_file: str; accepted_count: int; rejected_count: int
                 finding_count: int; run_id: int | None = None
class InputFileError(Exception): ...
class AliasConfigError(Exception): ...

# intake/aliases.py   (Rachit)
@dataclass(frozen=True)
class AliasConfig: aliases: dict[str, str]; known_generics: frozenset[str]
def load_aliases(path: str | Path) -> AliasConfig
def normalize_name(raw: str, config: AliasConfig) -> str
# intake/loader.py    (Rachit)
def load_medications(path: str | Path, source: str, patient_id: str, config: AliasConfig) -> LoadResult

# storage/db.py       (Vedant)
def connect(db_path: str | Path | None = None) -> sqlite3.Connection   # resolves --db > MEDREC_DB_PATH > default; PRAGMA foreign_keys=ON
def init_db(conn: sqlite3.Connection) -> None
def save_run(conn, run: RunRecord, findings: list[Finding]) -> int     # ONE transaction, returns run_id
def load_run(conn, run_id: int) -> tuple[RunRecord, list[Finding]] | None
def list_runs(conn, patient_id: str | None = None) -> list[RunRecord]

# rules/base.py       (Sarthak)
class ReconciliationRule(ABC):
    rule_id: ClassVar[str]
    @abstractmethod
    def check(self, clinic: list[Medication], pharmacy: list[Medication]) -> list[Finding]: ...
# rules/runner.py
def default_rules(config: AliasConfig) -> list[ReconciliationRule]
def run_rules(rules: list[ReconciliationRule], clinic: list[Medication], pharmacy: list[Medication]) -> list[Finding]
# report.py
def render_report(run: RunRecord, findings: list[Finding], rejected: list[RejectedRecord]) -> str
def render_history(runs: list[RunRecord]) -> str
# cli.py
def main(argv: list[str] | None = None) -> int

# ops/backup.py       (Devang)
def backup_db(src_path: str | Path, dest_path: str | Path) -> None     # sqlite3 Connection.backup
def integrity_check(db_path: str | Path) -> bool                       # PRAGMA integrity_check == "ok"
```
Version single source: `pyproject.toml` `version`; `medrec.__version__` reads it via `importlib.metadata`.

### CLI (entry point `medrec`, argparse)
```
medrec reconcile --clinic data/input/P003_clinic.csv --pharmacy data/input/P003_pharmacy.csv [--aliases config/aliases.json] [--db PATH]
medrec history --patient P003 [--db PATH]
medrec show --run-id 7 [--db PATH]
medrec --version
python -m medrec.ops.backup --dest backups/medrec-YYYYMMDD.db      # Devang's module, keeps cli.py single-owner
python scripts/generate_synthetic_data.py --out data/input --seed 42  # Rachit's script
```
Exit codes: `0` ran OK (findings or not — the report carries them), `2` usage error (argparse), `3` input file error, `4` database error.

### Presentation
Order = role order: Title (Rachit) → Rachit (intake) → Vedant (storage) → Sarthak (rules/report/CLI) → Devang (Docker/CI/release) → live demo → Q&A. **Devang shares the screen** for the whole deck and demo (one laptop, Docker ready); each speaker says "next" — avoids screen-share swaps. Each section ends with a handoff sentence naming the next speaker and what they receive (e.g. "…and those clean Medication objects are what Vedant stores.").
