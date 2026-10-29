# 05 — App PostgreSQL schema, transactions, and persistence testing
OWNER: Vedant Misra, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
1. **Image:** `postgres:18.6-trixie` for the app DB (18.6 is the current 18.x minor). HAPI's DB may use the same image, but HAPI publishes no version matrix: smoke-test HAPI on it before Friday. Fallback for the HAPI DB only: `postgres:16-alpine` (the tag HAPI's own starter compose uses).
2. **Schema:** 5 tables (`patient`, `reconciliation_run`, `medication_record`, `finding`, `rejected_record`), bigint identity keys, FKs enforced. **Snapshot-per-run**: medication rows belong to a run; the patient row is upserted.
3. **Stack:** SQLAlchemy 2.1.6 + psycopg 3.3.6, URL `postgresql+psycopg://`. One `SessionLocal.begin()` block writes patient upsert + run + snapshot rows + findings + rejected records.
4. **Applying the schema:** `Base.metadata.create_all(engine)` from one startup path (and in the test fixture). No Alembic, no initdb.d. The schema is frozen at 1.0.0; V2 adds rows, not DDL.
5. **Tests:** real Postgres. CI service container; locally the compose `app-db` service plus a `medrec_test` database. TRUNCATE between tests. Assert from a fresh connection.

## Rationale
- **Snapshot-per-run:** a finding's FKs point at rows that never change, so history shows exactly what was compared even if HAPI data changes later. Append-only means no merge logic and no stale-row cleanup. Cost: rows are duplicated per run (dozens per patient: trivial). "Current list" = rows of the patient's latest run. Upsert would be smaller but old findings would silently point at mutated data.
- **Patient upserted** on `(fhir_base_url, fhir_patient_id)`. Demographics show the latest fetch. If per-run demographics are needed, copy them onto the run (decide now).
- **Tolerant reader:** `discrepancy_type` and `source` are plain `text` (no ENUM/CHECK). V2 writes new values; V1 reads them and falls back to showing the raw string. V2 columns (`normalized_name`, `rxcui`, `frequency`) exist and are nullable from 1.0.0. `finding.details jsonb` is the one extension point for V2 data that does not fit the two compared-value columns.
- **Compared values** are two nullable text columns (`fhir_value`, `pharmacy_value`): the original values as compared, renderable for any type without knowing it. `raw jsonb` on medication and rejected rows keeps the source payload. Rejections are saved per run with machine-readable reasons, so the UI can list them.
- **Counts and `status` omitted:** a persisted run is complete by construction (atomic save) and counts are `COUNT(*)` of children. A failed attempt leaves no rows.
- **ON DELETE:** run to children `CASCADE`; run to patient `NO ACTION` (cannot delete a patient with history); finding to medication `CASCADE`. Run delete with this graph was executed on PG 18.6: children gone, no FK error.
- **bigint `GENERATED ALWAYS AS IDENTITY`** over UUID: readable "Run #12", smaller, ordered. `ALWAYS` blocks explicit ids that would later collide with the sequence (verified). If ids must be non-enumerable, PG 18 has native `uuidv7()`.
- **create_all** is idempotent (creates only missing tables), keeps one source of truth (the models), works on a fresh CI container, and rolling 1.1.0 back to 1.0.0 on the same volume changes nothing.
- **psycopg 3:** SQLAlchemy 2.1 made it the default PostgreSQL driver (psycopg2 is its predecessor); supports Python 3.12; `psycopg[binary]` needs no libpq install.

## Pinned versions
| Item | Pin | Note |
|---|---|---|
| PostgreSQL | 18.6, `postgres:18.6-trixie` | supported until 2030-11-14; `18.6-bookworm`, `18.6-alpine3.24` also exist |
| SQLAlchemy | `2.1.6` (2026-10-21) | Python >=3.11. Fallback `2.0.55`: same code works |
| psycopg | `psycopg[binary]==3.3.6` (2026-09-18) | Python 3.10-3.15; PG 10-18 |
| Alembic | not used (docs show 1.20.1) | |
Executed locally 2026-10-29 on a throwaway `postgres:18-alpine` container (PG 18.6): the DDL below, success path, NOT NULL rollback, FK-violation rollback, `GENERATED ALWAYS` rejection, run cascade delete. **The SQLAlchemy snippets and pytest sketch were not executed.**

## Commands and config snippets
```sql
CREATE TABLE patient (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fhir_base_url text NOT NULL, fhir_patient_id text NOT NULL,   -- original FHIR id + source server
  name text, birth_date date, gender text, fetched_at timestamptz NOT NULL,
  UNIQUE (fhir_base_url, fhir_patient_id));
CREATE TABLE reconciliation_run (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  patient_id bigint NOT NULL REFERENCES patient(id),
  app_version text NOT NULL, started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL);
CREATE INDEX ix_run_patient_started ON reconciliation_run (patient_id, started_at DESC);
CREATE TABLE medication_record (            -- per-run snapshot row
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
  source text NOT NULL,                     -- 'fhir' | 'pharmacy' (app-validated, no CHECK)
  source_record_id text NOT NULL,           -- FHIR MedicationRequest.id or pharmacy record id
  original_name text NOT NULL, normalized_name text, rxcui text,        -- V2 cols nullable
  dose_amount numeric NOT NULL, dose_unit text NOT NULL, frequency text,  -- frequency: V2
  date_recorded date NOT NULL, raw jsonb NOT NULL,
  UNIQUE (run_id, source, source_record_id));
CREATE TABLE finding (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
  discrepancy_type text NOT NULL,           -- open vocabulary: no ENUM, no CHECK
  medication_label text NOT NULL, fhir_value text, pharmacy_value text,
  fhir_record_id bigint REFERENCES medication_record(id) ON DELETE CASCADE,
  pharmacy_record_id bigint REFERENCES medication_record(id) ON DELETE CASCADE,
  details jsonb);                           -- V2 extension point, V1 ignores
CREATE INDEX ix_finding_run ON finding (run_id);
CREATE TABLE rejected_record (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
  source text NOT NULL, source_record_id text, raw jsonb NOT NULL,
  reasons jsonb NOT NULL);                  -- [{"field":"dose","code":"unreadable_dosage","message":"..."}]
CREATE INDEX ix_rejected_run ON rejected_record (run_id);
```
Models: `Mapped[str]` / `Text` for `discrepancy_type` (never `sqlalchemy.Enum`), `Identity(always=True)`, `ForeignKey(..., ondelete="CASCADE")`, `JSONB` from `sqlalchemy.dialects.postgresql`.

Atomic save (sketch; `run.medications`, `run.rejected` are relationships filled by the caller):
```python
engine = create_engine("postgresql+psycopg://medrec:medrec@localhost:5433/medrec", pool_pre_ping=True)
SessionLocal = sessionmaker(engine)

def save_run(patient_vals: dict, run: ReconciliationRun, findings) -> int:
    with SessionLocal.begin() as session:      # BEGIN; COMMIT on exit; any exception -> ROLLBACK
        keys = ("fhir_base_url", "fhir_patient_id")
        run.patient_id = session.scalar(
            pg_insert(Patient).values(**patient_vals)
            .on_conflict_do_update(index_elements=list(keys),
                set_={k: v for k, v in patient_vals.items() if k not in keys})
            .returning(Patient.id))
        session.add(run)
        session.flush()                        # INSERTs already sent: a later failure must undo them
        run.findings.extend(findings)          # may raise; nothing is committed
        return run.id
```
Tests (`TEST_DATABASE_URL=postgresql+psycopg://medrec:medrec@localhost:5432/medrec_test`):
```python
TABLES = ("patient", "reconciliation_run", "medication_record", "finding", "rejected_record")

@pytest.fixture(scope="session")
def engine():
    url = os.environ["TEST_DATABASE_URL"]
    assert url.rsplit("/", 1)[-1].endswith("_test"), "refusing to TRUNCATE a non-test DB"
    eng = create_engine(url); Base.metadata.create_all(eng); yield eng; eng.dispose()

@pytest.fixture(autouse=True)
def clean(engine):
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))

def counts(engine):                            # fresh connection = what any other reader sees
    with engine.connect() as c:
        return {t: c.scalar(text(f"SELECT count(*) FROM {t}")) for t in TABLES}

def test_success_commits_all(engine):
    save_run(**payload())                      # 1 patient, 1 run, 2 meds, 2 findings, 1 rejected
    assert counts(engine) == dict(patient=1, reconciliation_run=1, medication_record=2, finding=2, rejected_record=1)

@pytest.mark.parametrize("fault", ["null_type", "dangling_fk", "raise_midway"])
def test_failure_rolls_back_all(engine, fault):  # null_type: Finding(discrepancy_type=None); dangling_fk:
    with pytest.raises((IntegrityError, RuntimeError)):  # fhir_record_id=999_999; raise_midway: findings
        save_run(**payload(fault))             # iterable raises after the flush
    assert counts(engine) == dict.fromkeys(TABLES, 0)  # incl. the patient upsert

def test_unknown_discrepancy_type_roundtrips(engine):
    save_run(**payload(finding_type="v2_future_type"))   # V1 render fn must show raw string, not crash
```
CI (GitHub Actions) and local:
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:18.6-trixie
        env: { POSTGRES_USER: medrec, POSTGRES_PASSWORD: medrec, POSTGRES_DB: medrec_test }
        ports: ["5432:5432"]
        options: --health-cmd "pg_isready -U medrec" --health-interval 10s --health-timeout 5s --health-retries 5
    env: { TEST_DATABASE_URL: "postgresql+psycopg://medrec:medrec@localhost:5432/medrec_test" }
    # steps: checkout, setup-python 3.12, pip install, pytest
```
```yaml
# docker-compose.yml (hapi-db: same image, own name/volume/credentials)
  app-db:
    image: postgres:18.6-trixie
    environment: { POSTGRES_USER: medrec, POSTGRES_PASSWORD: medrec, POSTGRES_DB: medrec }
    volumes: ["app-db-data:/var/lib/postgresql"]   # 18+: mount the parent dir, not .../data
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U medrec -d medrec"], interval: 5s, retries: 10 }
```
Local test DB, once: `docker compose exec app-db createdb -U medrec medrec_test`.

## Gotchas
- **Alpine sorts by byte order** (verified on PG 18.6 alpine: `A,B,a,b` despite `en_US.utf8`), a reason for the Debian image. Debian ordering was not tested here.
- **Sequences leave gaps** after rollback, and `ON CONFLICT` upserts burn values too. Show timestamps; never treat ids as counts.
- **`GENERATED ALWAYS`** rejects explicit ids: seeds and tests must omit `id`.
- **Relaxing NOT NULL needs DDL.** `dose_amount`, `dose_unit`, `date_recorded` are NOT NULL because validation rejects missing/unreadable values; FHIR `authoredOn` is optional, so confirm the validation rules before 1.0.0.
- **JSONB is not byte-exact** (drops whitespace, key order, duplicate keys): `raw` is semantically equal to the source.
- **create_all never alters tables**; a V2 that needs a new column needs Alembic then (baseline with `command.stamp(cfg, "head")`). Run it from one startup path (concurrent workers can race).
- **SQLAlchemy 2.1:** autoflush now happens on every execute, including Core and `text()`; keep the pg upsert before pending objects exist. Default driver is psycopg 3, but keep the explicit `+psycopg`.
- **Enum trap:** a Python-enum column type can raise on unknown stored values (from memory, UNVERIFIED); keep the column `Text`, map to labels with `LABELS.get(t, t)`.
- **PG 18 image:** `PGDATA` is `/var/lib/postgresql/18/docker`; initdb.d scripts run only on an empty data dir.
- Tests must never run against the dev DB (the fixture asserts the `_test` suffix). Missing DB should fail the suite, not skip it.

## Rejected alternatives
- **Upsert medication rows per patient:** history lies after the next run, needs merge logic.
- **PG ENUM or CHECK list** for `discrepancy_type`/`source`: V2 values would need DDL and break V1 reads.
- **initdb.d SQL:** only runs on an empty volume; a second schema source of truth; CI still needs a `psql` step.
- **Alembic now:** 5 files plus a version table for a schema that is frozen; revisit if V2 needs DDL.
- **Join-external-transaction (savepoint) test isolation:** the code under test opens its own transaction from the engine, and the recipe turns commit/rollback into savepoints, so real COMMIT is never exercised.
- **testcontainers-python:** extra dependency plus Docker needed locally anyway; default `driver='psycopg2'` must be overridden. Reasonable fallback; version not checked.
- **UUID keys, `status`/count columns, `ingestion_batch` table, finding-to-medication link table, compared values as one JSONB:** not needed for V1.

## Sources
- [PostgreSQL versioning](https://www.postgresql.org/support/versioning/): 18.6 current, 17.11, support end dates (fetched 2026-10-29)
- [Docker official postgres image](https://hub.docker.com/_/postgres): tags, PG 18 PGDATA/volume change, initdb.d rule, env vars (fetched 2026-10-29)
- [HAPI database support](https://hapifhir.io/hapi-fhir/docs/server_jpa/database_support.html): PostgreSQL "Supported", dialect class, no version list (fetched 2026-10-29)
- [HAPI starter docker-compose](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/master/docker-compose.yml): `postgres:16-alpine`, datasource env keys (fetched 2026-10-29)
- [HAPI PostgresEmbeddedDatabase.java](https://raw.githubusercontent.com/hapifhir/hapi-fhir/master/hapi-fhir-jpaserver-test-utilities/src/main/java/ca/uhn/fhir/jpa/embedded/PostgresEmbeddedDatabase.java): HAPI's own tests use `postgres:latest` (fetched 2026-10-29)
- [SQLAlchemy 2.0 session transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html): `session.begin()` commit/rollback; external-transaction recipe, `create_savepoint`; 2.0.55 legacy; [2.1 version](https://docs.sqlalchemy.org/en/21/orm/session_transaction.html): 2.1.6 current, `sessionmaker.begin()` (both fetched 2026-10-29)
- [SQLAlchemy 2.1 migration notes](https://docs.sqlalchemy.org/en/21/changelog/migration_21.html): psycopg default, autoflush change, Python >=3.11 (fetched 2026-10-29)
- [SQLAlchemy PostgreSQL dialects](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html): `postgresql+psycopg://` URL (fetched 2026-10-29)
- [SQLAlchemy MetaData](https://docs.sqlalchemy.org/en/21/core/metadata.html): `create_all` checks per table; ALTER is Alembic's job (fetched 2026-10-29)
- [SQLAlchemy on PyPI](https://pypi.org/project/SQLAlchemy/): 2.1.6, 2026-10-21 (fetched 2026-10-29)
- [psycopg on PyPI](https://pypi.org/project/psycopg/): 3.3.6, 2026-09-18, Python 3.12 (fetched 2026-10-29)
- [psycopg install docs](https://www.psycopg.org/psycopg3/docs/basic/install.html): binary/c/pure options, PG 10-18 (fetched 2026-10-29)
- [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html): init/revision/upgrade, version 1.20.1 (fetched 2026-10-29)
- [Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html): `create_all` then `stamp head` (fetched 2026-10-29)
- [GitHub Actions PostgreSQL service containers](https://docs.github.com/en/actions/using-containerized-services/creating-postgresql-service-containers): health check, ports, localhost (fetched 2026-10-29)
- [testcontainers-python postgres](https://testcontainers-python.readthedocs.io/en/latest/modules/postgres/README.html): `PostgresContainer`, default `driver='psycopg2'` (fetched 2026-10-29)
- [PostgreSQL 18 CREATE TABLE](https://www.postgresql.org/docs/18/sql-createtable.html): ON DELETE actions, DEFERRABLE, identity (fetched 2026-10-29)
- [PostgreSQL 18 JSON types](https://www.postgresql.org/docs/18/datatype-json.html): jsonb does not preserve key order or whitespace (fetched 2026-10-29)
- [PostgreSQL 18 sequence functions](https://www.postgresql.org/docs/18/functions-sequence.html): `nextval` not reclaimed on abort (fetched 2026-10-29)
- [PostgreSQL 18 UUID functions](https://www.postgresql.org/docs/18/functions-uuid.html): native `uuidv7()` (fetched 2026-10-29)
