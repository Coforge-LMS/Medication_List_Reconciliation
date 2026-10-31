# Operations

Run commands from the repository root with the `.env` configuration described
in the [local setup](../README.md#run-locally). Keep the same Compose project and
configuration selected throughout each operation. Release builds also require
Bash, uv and Python 3.12.

## Run a release image

The release image is built locally from an annotated tag; no image registry is
required. `compose.release.yaml` has no build configuration, so startup cannot
accidentally replace a release image with code from the current checkout.

```sh
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
each has a `.counts.txt` companion. `backups/` is gitignored. Verification
compares row counts; it does not check content checksums.

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
