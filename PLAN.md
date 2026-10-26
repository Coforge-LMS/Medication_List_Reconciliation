# Team 1: Medication List Reconciliation — Team Plan

Week 3 project, Mon 2026-10-26 → Fri 2026-10-30 presentation. This file holds the shared contracts, repo ownership, merge order, CI plan, task list, day-by-day schedule and risk checklist. Planning only — no application code.

Team: **Rachit Shah** (intake & validation, task board) · **Vedant Misra** (SQLite storage, tech lead) · **Sarthak Kakkar** (rules, report, CLI) · **Devang Borkar** (Docker, CI, release, README).

Assumptions to confirm at the Monday session: CSV input, Python 3.12, argparse, stdlib only at runtime (pytest is the only dev dependency), Linear team key `TEA`. All data is synthetic.

---

## 1. Shared Decisions (goes into README.md → "Shared Decisions")

### 1.1 Input files
- Format **CSV** (stdlib `csv.DictReader`, nurse-readable, diffable). UTF-8, header row required, exact columns:
  `patient_id,medication_name,dose_amount,dose_unit,frequency,source,date_recorded`
- Naming: `data/input/<patient_id>_clinic.csv`, `data/input/<patient_id>_pharmacy.csv` (e.g. `P003_clinic.csv`).
- All data synthetic: patient IDs `P001…P099`, no names/DOB/addresses anywhere.

### 1.2 Medication record (`models.Medication`, frozen dataclass)
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

### 1.3 Matching + alias config
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

### 1.4 Rule definitions (unit conversion: g→mg ×1000, mcg→mg ÷1000 before comparing)
| rule_id | definition | example | severity |
|---|---|---|---|
| `DUPLICATE` | same normalized name appears >1× **within one source** | clinic lists "Tylenol 500 mg BID" and "acetaminophen 500 mg BID" | medium |
| `DOSE_MISMATCH` | matched in both sources but amount/unit **or** frequency differ (`details` says which) | clinic metformin 500 mg BID vs pharmacy metformin 1000 mg BID | high |
| `MISSING_ITEM` | in one source, absent from the other; `details.missing_from` = `pharmacy` or `clinic` | pharmacy dispenses lisinopril 10 mg QD, clinic list has no lisinopril | high |
| `UNRECOGNIZED_NAME` (**1.1.0**) | normalized name not in aliases values or `known_generics` | clinic lists "Zorbex 20 mg QD" | low |

- **Two rules on one med**: clinic lists ibuprofen twice (DUPLICATE) and pharmacy ibuprofen differs in dose (DOSE_MISMATCH) → both findings.
- **Perfect match**: zero findings → report prints `No discrepancies found: all N medications match between clinic and pharmacy lists.`
- Wording rule: findings describe facts ("listed at 500 mg in clinic, 1000 mg at pharmacy — please review"). Never "increase/stop/change".

### 1.5 Finding (what rules return, storage saves, report prints)
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

### 1.6 SQLite schema (`src/medrec/storage/schema.sql`, `PRAGMA user_version = 1`)
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

### 1.7 Interfaces (stubs land in the skeleton PR; bodies `raise NotImplementedError`)
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

### 1.8 CLI (entry point `medrec`, argparse)
```
medrec reconcile --clinic data/input/P003_clinic.csv --pharmacy data/input/P003_pharmacy.csv [--aliases config/aliases.json] [--db PATH]
medrec history --patient P003 [--db PATH]
medrec show --run-id 7 [--db PATH]
medrec --version
python -m medrec.ops.backup --dest backups/medrec-YYYYMMDD.db      # Devang's module, keeps cli.py single-owner
python scripts/generate_synthetic_data.py --out data/input --seed 42  # Rachit's script
```
Exit codes: `0` ran OK (findings or not — the report carries them), `2` usage error (argparse), `3` input file error, `4` database error.

### 1.9 Presentation
Order = role order: Title (Rachit) → Rachit (intake) → Vedant (storage) → Sarthak (rules/report/CLI) → Devang (Docker/CI/release) → live demo → Q&A. **Devang shares the screen** for the whole deck and demo (one laptop, Docker ready); each speaker says "next" — avoids screen-share swaps. Each section ends with a handoff sentence naming the next speaker and what they receive (e.g. "…and those clean Medication objects are what Vedant stores.").

---

## 2. Repo layout and ownership
```
.github/workflows/ci.yml, CODEOWNERS, pull_request_template.md   Devang
pyproject.toml, Dockerfile, .dockerignore, .env.example          Devang
CHANGELOG.md                                                     Devang
README.md                                                        Devang; "Shared Decisions" section changes only via all-4-approved PR
PLAN.md                                                          Vedant
config/aliases.json                                              Rachit
data/input/*.csv (synthetic, committed), data/README.md          Rachit
scripts/generate_synthetic_data.py                               Rachit
scripts/demo.sh                                                  Devang
src/medrec/__init__.py                                           Devang (version only, frozen)
src/medrec/models.py                                             FROZEN (all-4 approval)
src/medrec/intake/{aliases,frequency,loader}.py                  Rachit
src/medrec/storage/{db.py,schema.sql}                            Vedant
src/medrec/rules/{base,duplicate,dose_mismatch,missing_item,runner}.py, unrecognized_name.py (1.1.0)   Sarthak
src/medrec/report.py, cli.py                                     Sarthak
src/medrec/ops/backup.py                                         Devang
tests/intake/test_intake_*.py (+ own conftest.py)                Rachit
tests/storage/test_storage_*.py (+ own conftest.py)              Vedant
tests/rules/test_rules_*.py, tests/test_report.py, tests/test_cli.py   Sarthak
tests/test_smoke.py, tests/ops/test_ops_*.py, tests/integration/test_end_to_end.py   Devang
tests/conftest.py                                                Devang; append-only, prefer per-folder conftest
presentation/index.html, style.css                               Devang (shell); each person edits ONLY inside their markers
```
**Hot files and rules**
| file | rule |
|---|---|
| `models.py` | frozen after skeleton; changes need a PR approved by all 4, announced in chat, everyone rebases same day |
| `pyproject.toml` | Devang only; request deps in your PR description (runtime is stdlib — expect none) |
| all `__init__.py` | created empty in skeleton; only the package owner touches theirs; no re-exports |
| `README.md` | Devang; Shared Decisions edited only by agreement; others send text in PR comments |
| `CHANGELOG.md` | Devang; others add one line under `## [Unreleased]` in their PR (append-only, one line each, bottom of the list) |
| `ci.yml` | Devang only |
| `presentation/index.html` | skeleton contains `<!-- BEGIN title -->…<!-- END title -->`, `BEGIN rachit`, `BEGIN vedant`, `BEGIN sarthak`, `BEGIN devang`, `BEGIN demo` blocks separated by ≥3 unchanged lines; edit only inside yours → no conflicting hunks |
| `tests/conftest.py` | append-only; module fixtures live in the module's own `tests/<area>/conftest.py` |

Test filenames are unique across folders (`test_<area>_<thing>.py`) so pytest needs no `__init__.py` in tests.

**Merge order**
1. Mon — `vedant/plan`: PLAN.md + README Shared Decisions (docs only).
2. Mon — `devang/skeleton`: pyproject, models.py, all stubs, `schema.sql` placeholder, CI, smoke test, xfail integration test, CODEOWNERS, PR template, `.env.example`, CHANGELOG `[Unreleased]`, presentation shell, `.gitignore` adds `*.db`, `backups/`. **Everyone branches from main after this merges.** Then branch protection on.
3. Tue — any order (disjoint files): `rachit/aliases`, `rachit/data-generator`, `vedant/schema`, `vedant/connect-fk`, `sarthak/rules-base`, `sarthak/rule-duplicate`, `devang/docker`.
4. Tue EOD — `rachit/loader` (critical path).
5. Wed — `vedant/save-load-list` → `vedant/transaction-rollback`; `sarthak/rule-dose-mismatch`, `sarthak/rule-missing-item`, `sarthak/rule-tests`, `sarthak/report`; `devang/backup`; `rachit/intake-tests`.
6. Wed PM — `sarthak/cli` (needs loader + storage) → `devang/integration-test` (removes xfail).
7. Thu AM — `devang/release-1.0.0` (tag `v1.0.0`) → `sarthak/rule-unrecognized-name` → `devang/release-1.1.0` (tag `v1.1.0`) → `devang/rollback` → `devang/readme`.
8. Thu PM — presentation PRs in role order: `rachit/presentation-title`, `rachit/presentation`, `vedant/presentation`, `sarthak/presentation`, `devang/presentation`, `devang/demo-script`.
9. Fri — no merges after 12:00 except demo-blocking fixes.

---

## 3. CI from day one
`.github/workflows/ci.yml` (skeleton PR):
```yaml
name: CI
on:
  pull_request:
  push: { branches: [main], tags: ["v*"] }
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -e ".[dev]"
      - run: pytest -q
  docker:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t medrec:ci .
      - run: docker run --rm medrec:ci --version
```
- The skeleton (TEA-8) ships the `test` job; the `docker` job lands with the Dockerfile (TEA-15) and then becomes a required check.
- Skeleton has `tests/test_smoke.py` (imports every module, asserts `__version__`) and `tests/test_version.py` (CHANGELOG has a heading for the pyproject version) → green immediately. Integration test marked `xfail` until Wed.
- pytest config in pyproject: `testpaths=["tests"]`, `pythonpath=["src"]`, `addopts="-q --strict-markers"`.
- **Branch protection** (applied by Vedant as repo admin via `gh api`, after the skeleton merges): require PR, 1 approving review from another member, required checks `test` + `docker`, branches up to date, no force-push, no deletion, applies to admins.
- **Test independence**: every DB test uses `tmp_path / "test.db"` (or `:memory:`), never `MEDREC_DB_PATH`'s default (an autouse fixture in `tests/conftest.py` sets `MEDREC_DB_PATH` to a tmp path); file paths built from `Path(__file__).parent`; no network; no module-level state; close every connection (`contextlib.closing`); rules tests build `Medication` objects directly, no files.
- **Pre-push checklist** (in PR template): `git pull --rebase origin main` · `pytest` passes locally on 3.12 · no `.env`, `*.db`, keys, or real patient data · only my files changed (or hot-file rule followed) · PR title `TEA-<n> <Type>: …`, description has `Fixes TEA-<n>` · PR link pasted into Linear issue.
- **Commits**: git `user.name` = full name; message `[<first-name>] <area>: <summary> (TEA-<n>)`, e.g. `[Rachit] intake: reject future dates (TEA-17)`.
- **Secrets**: `.env` already gitignored; `.env.example` committed with `MEDREC_DB_PATH=data/medrec.db` only.

---

## 4. Linear setup

### 4.0 Workspace
- Workspace **Team 1 MedRec** (https://linear.app/team-1-medrec), team **TEA**. Members: Rachit, Vedant, Sarthak, Devang.
- Board: [Team 1: Medication List Reconciliation](https://linear.app/team-1-medrec/project/team-1-medication-list-reconciliation-cafde8ad7add) (lead Rachit).
- **Adam**: invite him via Settings → Members (a project link only opens for workspace members). Tracked in TEA-6.
- GitHub integration: Settings → Integrations → GitHub, connected to this repo, so `TEA-<n>` in a PR title/branch links the PR to the issue.

### 4.1 Board structure
- **Project** `Team 1: Medication List Reconciliation` — team TEA, lead Rachit (board owner), start 2026-10-26, target 2026-10-30, links to the GitHub repo.
- **Milestones**: `Mon Decisions + Skeleton` (10-26) · `Tue Core pieces` (10-27) · `Wed Integration` (10-28) · `Thu Release 1.0.0/1.1.0 + rollback + presentation page` (10-29) · `Fri Presentation` (10-30).
- **Labels**: area `intake`, `storage`, `rules`, `devops`, `presentation`, `docs`; type `feature` (reuse the default `Feature`), `test`, `chore` (`docs` doubles as area and type).
- **Issue description template**: Owner · Branch · Milestone/due · Context · Acceptance criteria (checklist) · Blocked by · `PR link: (paste here)`. Created in dependency order so `blockedBy` relations point at real IDs. Status `Todo`; Mon items `In Progress`.

### 4.2 Issue list (36 issues, TEA-5 … TEA-40)
| ID | Title | Owner | Branch | Due | Blocked by |
|---|---|---|---|---|---|
| TEA-5 | Chore: Monday shared-decisions session | Vedant (facilitates, all attend) | — | Mon | — |
| TEA-7 | Docs: PLAN.md + README Shared Decisions | Vedant | vedant/plan | Mon | TEA-5 |
| TEA-8 | Chore: Skeleton + shared models + CI PR | Devang | devang/skeleton | Mon | TEA-7 |
| TEA-9 | Chore: Branch protection on main | Vedant (repo admin) | — | Mon | TEA-8 |
| TEA-6 | Chore: Share Linear board with Adam | Rachit | — | Mon | — |
| TEA-10 | Feature: Synthetic data generator + sample input files (P001 perfect, P002 duplicate, P003 dose, P004 missing both ways, P005 two rules, P006 bad records, P007 unrecognized name) | Rachit | rachit/data-generator | Tue | TEA-8 |
| TEA-11 | Feature: Alias config loader + name normalization | Rachit | rachit/aliases | Tue | TEA-8 |
| TEA-17 | Feature: Loader + validation → Medication objects with rejection reasons (incl. frequency normalization) | Rachit | rachit/loader | Tue | TEA-8, TEA-11 |
| TEA-24 | Test: Intake tests (each reason code, multi-reason row, bad header, empty file, alias hit/miss) | Rachit | rachit/intake-tests | Wed | TEA-17 |
| TEA-12 | Feature: SQLite schema (runs + findings FK) + init_db | Vedant | vedant/schema | Tue | TEA-8 |
| TEA-13 | Feature: connect() with MEDREC_DB_PATH + PRAGMA foreign_keys=ON per connection | Vedant | vedant/connect-fk | Tue | TEA-8 |
| TEA-18 | Feature: save_run / load_run / list_runs | Vedant | vedant/save-load-list | Wed | TEA-12, TEA-13 |
| TEA-25 | Test: Single-transaction save + rollback test with temp DB (+ FK violation test) | Vedant | vedant/transaction-rollback | Wed | TEA-18 |
| TEA-14 | Feature: ReconciliationRule base class + rule runner | Sarthak | sarthak/rules-base | Tue | TEA-8 |
| TEA-19 | Feature: DuplicateRule | Sarthak | sarthak/rule-duplicate | Tue | TEA-14 |
| TEA-20 | Feature: DoseMismatchRule (unit conversion, frequency) | Sarthak | sarthak/rule-dose-mismatch | Wed | TEA-14 |
| TEA-21 | Feature: MissingItemRule (both directions) | Sarthak | sarthak/rule-missing-item | Wed | TEA-14 |
| TEA-26 | Test: Rule tests (med breaking two rules, patient with no findings) | Sarthak | sarthak/rule-tests | Wed | TEA-19, TEA-20, TEA-21 |
| TEA-22 | Feature: Nurse-facing report incl. perfect-match case + rejected section | Sarthak | sarthak/report | Wed | TEA-14 |
| TEA-27 | Feature: CLI reconcile / history / show + exit codes | Sarthak | sarthak/cli | Wed | TEA-17, TEA-18, TEA-22 |
| TEA-15 | Feature: Dockerfile + .dockerignore + named volume | Devang | devang/docker | Wed | TEA-8 |
| TEA-23 | Feature: Backup with Connection.backup + PRAGMA integrity_check | Devang | devang/backup | Wed | TEA-12 |
| TEA-32 | Test: End-to-end integration test (CSV → report → DB row) | Devang | devang/integration-test | Wed | TEA-17, TEA-18, TEA-27 |
| TEA-33 | Chore: Release 1.0.0 (pyproject, CHANGELOG, tag v1.0.0, image medrec:1.0.0) | Devang | devang/release-1.0.0 | Thu | TEA-24, TEA-25, TEA-26, TEA-15, TEA-32 |
| TEA-34 | Feature: Release 1.1.0 rule — UnrecognizedNameRule (+ tests, no schema change) | Sarthak | sarthak/rule-unrecognized-name | Thu | TEA-33 |
| TEA-35 | Chore: Release 1.1.0 (tag v1.1.0, CHANGELOG, image medrec:1.1.0) | Devang | devang/release-1.1.0 | Thu | TEA-34 |
| TEA-36 | Docs: Rollback procedure 1.1.0 → 1.0.0 keeping history (backup → integrity_check → run 1.0.0 on same volume → history shows 1.1.0 runs) | Devang | devang/rollback | Thu | TEA-23, TEA-35 |
| TEA-37 | Docs: README with real pasted output (reconcile, history, rollback) | Devang | devang/readme | Thu | TEA-36 |
| TEA-16 | Docs: Presentation title section + handoff sentences | Rachit | rachit/presentation-title | Thu | TEA-8 |
| TEA-28 | Docs: Presentation section — Rachit (+ Be-ready-to-answer checklist) | Rachit | rachit/presentation | Thu | TEA-16 |
| TEA-29 | Docs: Presentation section — Vedant (+ checklist) | Vedant | vedant/presentation | Thu | TEA-16 |
| TEA-30 | Docs: Presentation section — Sarthak (+ checklist) | Sarthak | sarthak/presentation | Thu | TEA-16 |
| TEA-31 | Docs: Presentation section — Devang (+ checklist) | Devang | devang/presentation | Thu | TEA-16 |
| TEA-38 | Docs: Demo script (scripts/demo.sh + demo section) | Devang | devang/demo-script | Thu | TEA-36 |
| TEA-39 | Chore: Full-team demo dry run | Devang (runs), all | — | Fri AM | TEA-37, TEA-28, TEA-29, TEA-30, TEA-31, TEA-38 |
| TEA-40 | Chore: Friday presentation (30 min) | Rachit | — | Fri | TEA-39 |

**Be ready to answer** (checklists in TEA-28 … TEA-31)
- Rachit: why CSV not JSON · how a row becomes rejected (show a multi-reason row) · how alias matching works and what happens for a brand not in the config · how frequency is normalized · how we guarantee no real patient data · why the generator is seeded · empty file / wrong header behaviour.
- Vedant: why two tables and what the FK protects · why `PRAGMA foreign_keys=ON` per connection · where the transaction begins/commits and what happens if a finding insert fails halfway · how the rollback test proves it · why `tmp_path` · how connections get closed · why parameterized queries · can 1.0.0 read 1.1.0 rows.
- Sarthak: why an ABC + subclasses, and how to add a rule · dose mismatch logic incl. unit conversion · how one med gets two findings · perfect-match output · how wording avoids treatment advice · exit codes · how the 1.1.0 rule was added without touching the others.
- Devang: walk the Dockerfile · where the DB lives and why it survives `docker rm` · what CI runs and when · how tag / CHANGELOG / image tag stay in sync · rollback steps and why history survives · `Connection.backup` vs file copy · what `integrity_check` returns · how secrets stay out.


---

## 5. Day-by-day
| | Rachit | Vedant | Sarthak | Devang |
|---|---|---|---|---|
| **Mon** | Decisions session; Linear invites/Adam (5) | Facilitate session; `vedant/plan` merged; branch protection | Session; review models.py | `devang/skeleton` **merged by EOD** (everyone blocked on it) |
| **Tue** | `rachit/aliases`, `rachit/data-generator`, **`rachit/loader` merged EOD** | `vedant/schema`, `vedant/connect-fk` merged | `sarthak/rules-base`, `rule-duplicate` merged (tests build Medication by hand) | `devang/docker` (image runs `medrec --version`) |
| **Wed** | `rachit/intake-tests` merged | `save-load-list` AM, `transaction-rollback` merged | dose/missing rules, rule tests, report AM; **`sarthak/cli` merged PM** | `devang/backup`; **integration test un-xfailed, merged EOD** |
| **Thu** | title section + own section | own section | 1.1.0 rule after v1.0.0 tag; own section | v1.0.0 AM → v1.1.0 → rollback → README → own section + demo script |
| **Fri** | dry run, present | dry run, present | dry run, present | drive dry run + demo |

**Critical path**: decisions → skeleton → loader (Rachit) + save_run (Vedant) → CLI wiring (Sarthak) → integration test (Devang) → v1.0.0 → 1.1.0 rule → v1.1.0 → rollback demo → README output → presentation.
**Working in parallel before upstream merges**: everyone codes against `models.py`; Sarthak's rules/report tests construct `Medication`/`Finding` directly; Vedant tests with hand-made `Finding`s; Sarthak's CLI tests can monkeypatch `load_medications`/`save_run` until real ones merge; Devang's integration test stays `xfail` and Dockerfile only needs `medrec --version`. Daily: 10:00 standup, `git pull --rebase origin main` before starting and before pushing.

---

## 6. Risk and conflict-prevention checklist
- **Merge hotspots**: models.py frozen; single owners for pyproject/ci/README/CHANGELOG; marker blocks in presentation; small PRs merged same day; rebase daily.
- **CI failures**: Python mismatch → pin 3.12 in CI, Docker (`python:3.12-slim`), and `requires-python=">=3.12"`; missing deps → only via Devang's pyproject, `pip install -e .[dev]` in CI; path-dependent tests → `Path(__file__)`-relative paths and `tmp_path`; real DB → autouse fixture overrides `MEDREC_DB_PATH`; Docker not needed for pytest (separate `docker` job; ubuntu runners have Docker).
- **Foreign keys off**: SQLite defaults to OFF per connection → only `storage.connect()` opens connections; test asserts `PRAGMA foreign_keys` == 1 and that a finding with a bogus `run_id` raises `IntegrityError`.
- **Unclosed connections**: `with closing(connect(...)) as conn:`; note `with conn:` only commits/rolls back, it does not close.
- **Rollback test design**: real temp DB; save a valid run; then call `save_run` with a findings list whose 2nd item violates the severity CHECK → assert `IntegrityError` and that `runs`/`findings` counts are unchanged.
- **Version drift**: version only in pyproject; release PR updates pyproject + CHANGELOG heading together; `test_version.py` asserts they agree; tag `vX.Y.Z` and image `medrec:X.Y.Z` built from the tagged commit.
- **Rollback compatibility**: 1.1.0 adds a rule class only — no new tables/columns, `user_version` stays 1, `rule_id` not constrained, 1.0.0 report renders unknown rule_ids; always `backup_db` + `integrity_check` before switching versions; demo shows `medrec history` on 1.0.0 still listing 1.1.0 runs.
- **Data safety**: synthetic only (`P0xx` IDs, invented drug "Zorbex" for 1.1.0); `*.db`, `backups/`, `.env` gitignored.
- **AI-use rule**: every PR description has "I can explain every line" checkbox; reviewer asks the author one "why" question per PR; Q&A checklists above are rehearsed in Friday's dry run.
