# Medication List Reconciliation

Medication reconciliation using synthetic FHIR, pharmacy and patient-reported
intake data. Version 1.0.0 detects duplicate, missing and dosage discrepancies,
stores each run atomically, and exports its findings to PDF. Findings support
review; they never recommend treatment. All committed patients are synthetic.

## Prerequisites

- Docker Engine/Desktop with Compose v2.20+; allow memory for HAPI's 2 GiB
  container limit, two PostgreSQL instances and the app.
- Git, Bash and [uv](https://docs.astral.sh/uv/) with Python 3.12 for tagged builds
  and local tests. GitHub CLI (`gh`) is needed only to publish a release.
- Free loopback ports 8000 (app), 8080 (HAPI) and 5433 (app database).
  `APP_PORT`, `HAPI_PORT` and `APP_DB_PORT` override them for an isolated rehearsal.

Run commands from the repository root. `.env.example` contains public demo
passwords; copy it once to the gitignored `.env` and change passwords there if
needed. Keep the app password URL-safe (letters, digits, underscores).

## Start release 1.0.0

The release image is built locally from an annotated tag; no image registry is
required. `compose.release.yaml` has no build configuration, so startup cannot
accidentally replace a release image with code from the current checkout.

```sh
# First checkout: git clone https://github.com/Coforge-LMS/Medication_List_Reconciliation.git
# Then cd into the cloned repository. Copy .env only on the first setup.
cp .env.example .env
git fetch origin --tags
scripts/build_release.sh 1.0.0
export COMPOSE_FILE=compose.release.yaml
export APP_VERSION=1.0.0
docker compose config --quiet
docker compose up -d --no-build --wait --wait-timeout 300
docker compose ps -a
docker compose logs --timestamps importer app-seed
curl --fail "http://127.0.0.1:${APP_PORT:-8000}/healthz"
docker image inspect medrec-app:1.0.0 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
git rev-list -n 1 v1.0.0
```

Expect `/healthz` to return `{"status":"ok","version":"1.0.0"}`, importer and
app-seed to exit 0, and both printed revision hashes to match. HAPI imports 13
patients; subsequent starts skip the import and seed intake idempotently.
`docker compose down` preserves both database volumes. A disposable clean-stack
rehearsal uses `docker compose down -v` **before** startup; this deletes that
project's databases, so use a separate `COMPOSE_PROJECT_NAME` for rehearsals.

For development, leave `COMPOSE_FILE` unset, keep `APP_VERSION=dev` from
`.env.example`, and run `docker compose up -d --build --wait --wait-timeout 300`.
The default `compose.yaml` adds a local app build to the same six services.

## Use the app

Open http://127.0.0.1:8000 (or your `APP_PORT`). Search `Mixton`, open Marcus
Mixton, review the Patient-reported / FHIR / Pharmacy columns and rejected
records, then click Run. Expect seven findings: two duplicates, four missing
and one dosage mismatch, plus six rejected records. History lists stored runs;
each run offers a PDF report. `Cleary` demonstrates no discrepancies, and
`Montero` demonstrates reconciliation without an intake interview.
See [demo patients](docs/DEMO_PATIENTS.md) for the full walkthrough.

The JSON API exposes `POST /api/patients/{fhir_id}/reconcile` and
`GET /api/runs/{run_id}`. `GET /runs/{run_id}/report.pdf` downloads the stored
run's report. Use patient IDs returned by the current HAPI server rather than
assuming IDs survive a fresh import.

## Backup and verify restore

Use the same exported Compose project/file/version as startup. Keep other
writers stopped during verification. The script briefly stops a running app,
dumps app-db using its PostgreSQL 18 binaries, lists the archive, restores it
into `medrec_restore_check`, and compares **every public table's row count**.
It drops only the scratch database it created and restarts the app if it was
running, including on failure. A pre-existing scratch database causes a safe
failure. An initially stopped app stays stopped.

```sh
scripts/backup.sh
docker compose ps app
```

Success prints `RESTORE VERIFIED: medrec_restore_check`, matching table counts,
and the archive path. Only verified archives become `backups/medrec-*.dump`;
each has a `.counts.txt` companion. `backups/` is gitignored. See the measured
output below. Row counts verify completeness, rather than content checksums.

The default backup covers app history and intake. HAPI's database is rebuilt
from committed bundles; saved runs retain source snapshots and stable patient
identifiers, so history remains readable after re-import. A HAPI database backup
is needed separately if preserving exact server resource IDs matters.

For disaster recovery, first take a fresh verified backup if the source is
readable. Set `BACKUP` to the archive path printed above, then replace the app
database while the app is stopped. This deliberately discards changes made
after that archive; it is separate from a version rollback.

```sh
test -s "$BACKUP"
docker compose stop app
docker compose exec -T app-db sh -eu -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" -T template0 "$POSTGRES_DB"'
docker compose exec -T app-db sh -eu -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error --single-transaction' < "$BACKUP"
docker compose exec -T app-db sh -eu -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c ANALYZE'
docker compose start app
scripts/backup.sh
```

If restore fails, leave the app stopped, inspect the error, and retry from a
known-good archive before restarting it.

## Compatibility and rollback

The public contract consists of the HTTP API and persisted data. Release N may
only expand the schema with optional/defaulted fields; release N−1 must read
N's data. `discrepancy_type` is an open TEXT vocabulary: unknown types render as
`Other (<value>)` in history, run pages and PDFs. Readers tolerate additional
JSON keys. Raw source values remain preserved. Version 1.1.0 must make no DDL
changes and must not remove or retype existing fields.

Rollback swaps only the app image on the **same database volume**. Take and
verify a backup before any upgrade or rollback. Never restore an older dump
to perform a version rollback: doing so erases newer history.

Once 1.1.0 exists and both tagged images have been built:

```sh
scripts/backup.sh
APP_VERSION=1.0.0 docker compose up -d --no-build --no-deps --wait app
curl --fail "http://127.0.0.1:${APP_PORT:-8000}/healthz"
docker image inspect medrec-app:1.0.0 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
git rev-list -n 1 v1.0.0
# Check newer runs in History; unknown types show Other (frequency_mismatch).
# Run a new reconciliation to verify V1 writes, then roll forward:
APP_VERSION=1.1.0 docker compose up -d --no-build --no-deps --wait app
```

The 1.1.0 → 1.0.0 rehearsal belongs to TEA-57 after 1.1.0 is available.

## Tests

Use a dedicated database ending in `_test`; tests truncate its tables.

```sh
docker compose exec -T app-db createdb -U medrec medrec_test
export TEST_DATABASE_URL="postgresql+psycopg://medrec:demo_medrec@127.0.0.1:${APP_DB_PORT:-5433}/medrec_test"
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -vv --durations=10
bash -n scripts/build_release.sh scripts/backup.sh
```

Use your `.env` password in the test URL if it differs from the public demo
value. [Essential-test checklist](docs/TEST_CHECKLIST.md) maps requirements to
individual test IDs. The E2E test uses real PostgreSQL and recorded FHIR HTTP
responses; the clean Compose rehearsal exercises live HAPI too.

## Publish a release

Merge the reviewed release PR with `lint` and `test` green. The version in
`pyproject.toml`, `uv.lock`, CHANGELOG section and tag must agree. Create the
annotated tag on the reviewed release commit, then build and rehearse it before
pushing the tag. Release images carry both OCI version and revision labels;
the build script rejects a version mismatch or an existing image belonging to
a different revision. Published tags are immutable; fix forward with a new
version instead of moving a tag.

```sh
git switch main
git pull --ff-only
# Reuse an existing rehearsal tag only once its commit is on merged main.
if git show-ref --verify --quiet refs/tags/v1.0.0; then
  git merge-base --is-ancestor v1.0.0 main
else
  git tag -a v1.0.0 -m "MedRec 1.0.0: three-source reconciliation, history, PDF and verified backups"
fi
scripts/build_release.sh 1.0.0
# Run the clean-stack startup and backup verification above, then:
git push origin v1.0.0
gh release create v1.0.0 --verify-tag --title "MedRec 1.0.0" --notes-file docs/releases/1.0.0.md
```

See [CHANGELOG](CHANGELOG.md) and [release evidence](docs/releases/1.0.0.md).

## Release rehearsal evidence

Rehearsed 2026-10-31 with Docker 29.9.2, Compose v5.6.1, gh 2.103.3 and
Python 3.12.15. The disposable `medrec-tea51-check` project used ports
18000/18080/15433; the existing demo stack on 8000/8080/5433 was preserved.
The initial candidate image was `medrec-app:release-check`, with app version
1.0.0. Tagged-image verification is recorded on the release PR before publishing.

```sh
export COMPOSE_PROJECT_NAME=medrec-tea51-check
export COMPOSE_FILE=compose.release.yaml
export COMPOSE_ENV_FILES=.env.example
export APP_VERSION=release-check
export APP_PORT=18000 HAPI_PORT=18080 APP_DB_PORT=15433
docker compose down -v
docker compose config --quiet
docker compose up -d --no-build --wait --wait-timeout 300
scripts/backup.sh
```

Startup took **31.227 seconds**. Both databases, HAPI and the app were healthy;
importer and app-seed exited 0. `/healthz` returned version 1.0.0 and HAPI
reported 13 patients. Live searches, detail, reconciliation, stored JSON,
history and PDF returned the expected results for CASE-MIXED (7 findings,
6 rejected), CASE-CLEAN (0 findings) and CASE-BRAND (2 findings).

Backup verification after those three runs printed:

```text
RESTORE VERIFIED: medrec_restore_check
public.finding=9
public.intake_interview=12
public.intake_medication=47
public.medication_record=27
public.patient=12
public.reconciliation_run=3
public.rejected_record=6
Verified archive: backups/medrec-20261031T190429Z-yxSRc8.dump
```

The app database has 12 patients because seeding creates only patients with
intake interviews; the un-interviewed HAPI patient is added on reconciliation.
The disaster-recovery commands above were also run against this disposable
database; another verified backup produced identical counts. The scratch
database was removed and the app resumed successfully.

The full suite passed with real PostgreSQL and no skipped tests. Ruff lint and
formatting, Bash syntax, and both Compose entry points passed. Six backup
regressions cover existing scratch-database preservation, failed dump, failed
restore, mismatched counts, and preservation of a running/stopped app.

## Container architecture

All six services share the Compose network. Solid arrows below show startup
gates, pointing from a prerequisite to the service that waits for it. Dashed
arrows show data mounts.

```mermaid
flowchart TB
  subgraph network["Compose network"]
    hdb["hapi-db · PostgreSQL 18.6<br/>Port 5432 "]
    hapi["hapi · HAPI FHIR 8.12.0-2<br/>Host 127.0.0.1:8080 → container 8080"]
    importer["importer · Python 3.12"]
    adb["app-db · PostgreSQL 18.6<br/>Host 127.0.0.1:5433 → container 5432"]
    seed["app-seed · medrec-app image"]
    app["app · medrec-app image<br/>FastAPI / Uvicorn · non-root<br/>Host 127.0.0.1:8000 → container 8000"]

    hdb -->|healthy| hapi
    hapi -->|healthy| importer
    importer -->|completed successfully| app
    adb -->|healthy| seed
    adb -->|healthy| app
    seed -->|completed successfully| app
  end

  subgraph storage["Persistent volumes and host inputs"]
    hv[("hapi-db-data")]
    av[("app-db-data")]
    bundles["data/fhir/ + infra/import_fhir.py<br/>Read-only host mounts"]
  end
  hv -.->|/var/lib/postgresql| hdb
  av -.->|/var/lib/postgresql| adb
  bundles -.->|read-only| importer
```

HAPI stores FHIR resources in `hapi-db`; the importer writes bundles through
`http://hapi:8080/fhir`. The seeder writes intake records to `app-db`. The app
receives `FHIR_BASE_URL=http://hapi:8080/fhir` and a `DATABASE_URL` pointing to
`app-db:5432`.

`app` and `app-seed` use the same image built from `infra/Dockerfile`. App code,
aliases, pharmacy data, and intake CSVs are baked into that image. Passwords
come from the gitignored `.env`; `infra/hapi.env` holds non-secret HAPI settings.
Both database volumes survive `docker compose down`; `down -v` deletes them.
