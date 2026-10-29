# 10 — Releases, backup/restore, and V2 → V1 rollback on PostgreSQL
OWNER: Devang Borkar, to review and finalize (schema compatibility: Vedant Misra)
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
- **Backup:** `pg_dump -Fc --no-owner` run *inside* the `app-db` container, to `backups/medrec-<ts>.dump` (gitignored). Take one before every upgrade and every rollback.
- **Verify:** every dump is checked by `pg_restore --list`, then restored into scratch DB `medrec_restore_check` and compared table-by-table on row counts. A backup is "good" only after this passes.
- **Rollback = swap the app image, not restore data.** `APP_VERSION=1.0.0 docker compose up -d --no-build --no-deps app` against the same volume. Restoring a pre-1.1.0 dump would *erase* the 1.1.0 history, the opposite of the demo.
- **HAPI DB: optional, not in the default backup.** App DB is the system of record. See Gotchas on ID stability before relying on this.
- **Releases:** SemVer 1.0.0 → 1.1.0 (minor), Keep a Changelog, annotated tags `v1.0.0`/`v1.1.0`, `gh release create`, images built from the tagged commit, version defined once in `pyproject.toml`.
- **Must land before tagging 1.0.0:** the tolerant reader plus one test (insert a finding with `discrepancy_type='made_up_type'`; history page returns 200 and shows "Other (made_up_type)"). A published tag must not move, so 1.0.0 cannot be patched after the fact.

## Rationale
**COMPATIBILITY RULE: release N may only expand the schema (add tables, add nullable or defaulted columns, add new values to free-text columns), never contract it; and release N-1 must keep running on release N's data, reading `discrepancy_type` as plain TEXT and rendering any value it does not recognise as "Other (<value>)" without raising an error.**
- Corollaries: (1) `discrepancy_type` is `TEXT`, no PG ENUM, no CHECK list; allowed values are enforced in app code. (2) V2 ships no DDL, so the schema version is identical in 1.0.0 and 1.1.0. (3) V2 writes `rxcui`/`normalized_name` only into the existing nullable columns and never overwrites raw source columns. (4) New JSON keys may be added, existing keys never renamed, removed or retyped; readers ignore unknown keys. (5) No down-migrations; startup code never drops, truncates or re-seeds destructively.
- Why it works: this is Fowler's Parallel Change (expand, migrate, contract); the release can ship at any phase, and skipping contract is safe here because we never contract. Fowler's Tolerant Reader (Postel's law): read only what you need, ignore the rest.
- PG ENUM is a poor fit: values can be added/renamed but not removed or reordered (PG docs), so every new finding type would be DDL.
- Why a minor bump: SemVer 2.0.0 uses MINOR for backward-compatible functionality; released contents are immutable (new version for any change). Declare in the README that the public API = HTTP API + persisted data contract, with `discrepancy_type` documented as an open set.
- pg_dump takes a consistent snapshot without blocking readers or writers, so a live backup is safe. PG docs caution that pg_dump is not generally the tool for regular production backups; fine for this demo-scale system.
- Client/server match: running pg_dump via `docker compose exec app-db` uses the server's own binaries. Generally pg_dump can dump older servers but refuses newer ones, and its output loads into the same or newer servers.

## Pinned versions
| Item | Pin | Note |
|---|---|---|
| PostgreSQL (app-db) | `postgres:17.11` | 17.11 is current minor, EOL 2029-11-08 (postgresql.org, 2026-10-29). Minors need no dump/restore. 18.6 also supported; `19rc1` is only a release candidate. |
| Volume mount | `/var/lib/postgresql/data` | PG 17 and below. The PG 18+ image uses a versioned PGDATA under `/var/lib/postgresql`; do not switch major versions before Friday. |
| App images | `medrec-app:1.0.0`, `medrec-app:1.1.0` | Never `latest`. Python 3.12 base. |
| Spec/format | SemVer 2.0.0, Keep a Changelog 1.1.0 | Git tags use a `v` prefix (convention; the SemVer FAQ says `v1.2.3` is a tag name, not the version). |
| Tooling | Docker Compose v2 (`docker compose`), `gh` | Exact versions UNVERIFIED; record `docker compose version` and `gh --version` in the runbook. |

## Commands and config snippets
Compose and version source (no `build:` on `app` for releases; keep it in a dev override so `--build` can never tag the wrong code):
```yaml
services:
  app:     { image: "medrec-app:${APP_VERSION:?set APP_VERSION, e.g. 1.1.0}", depends_on: [app-db] }
  app-db:  { image: "postgres:17.11", volumes: ["medrec_pgdata:/var/lib/postgresql/data"] }
volumes: { medrec_pgdata: {} }
```
`pyproject.toml`: static `version = "1.1.0"` under `[project]`; app shows `importlib.metadata.version("<dist-name>")` (needs `pip install .` in the image, else `PackageNotFoundError`). Release check: `APP_VERSION`, pyproject version and git tag must be equal. Store the version on each run row (`reconciliation_run.app_version TEXT`, suggested; UNVERIFIED that the schema has it) so history can show "produced by 1.1.0".

Backup (single-quoted so `$POSTGRES_*` expand inside the container; avoids host `$USER` clash):
```bash
mkdir -p backups; F=backups/medrec-$(date +%Y%m%d-%H%M%S).dump
docker compose exec -T app-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$F" \
  && [ -s "$F" ] && echo "backup ok: $F" || echo "BACKUP FAILED"
```
Verify restore (scratch DB; `-T` keeps stdin/stdout binary-clean; `pg_restore` reads stdin when no file is given; stop `app` first so counts cannot drift):
```bash
docker compose stop app
docker compose exec -T app-db pg_restore --list < "$F" | head -20          # TOC readable
docker compose exec -T app-db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists medrec_restore_check && createdb -U "$POSTGRES_USER" -T template0 medrec_restore_check'
docker compose exec -T app-db sh -c 'pg_restore -U "$POSTGRES_USER" -d medrec_restore_check --no-owner --single-transaction' < "$F"
counts() { docker compose exec -T app-db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -Atq' sh "$1" <<'SQL'
SELECT table_name||'='||(xpath('/row/c/text()',query_to_xml(format('select count(*) c from %I',table_name),false,true,'')))[1]::text
FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1;
SQL
}
DB=$(docker compose exec -T app-db printenv POSTGRES_DB | tr -d '\r')
diff <(counts "$DB") <(counts medrec_restore_check) && echo "RESTORE VERIFIED"
docker compose exec -T app-db sh -c 'dropdb -U "$POSTGRES_USER" medrec_restore_check'; docker compose start app
```
Restore over the live DB (disaster only; app stopped): `pg_restore -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction` with the same stdin pattern. `--clean` drops only objects present in the archive; for an exact copy drop and recreate the DB from `template0` first. Run `ANALYZE` afterwards. `pg_restore -j` needs a real file, not a pipe, so skip it.

Release (repeat for 1.0.0):
```bash
git switch main && git pull                      # tests green, CHANGELOG [1.1.0] dated, pyproject = 1.1.0
git tag -a v1.1.0 -m "MedRec 1.1.0: frequency-mismatch rule, RxNorm normalization; no schema change"
git push origin v1.1.0                           # never move or re-push a published tag; fix forward as 1.1.1
sed -n '/^## \[1\.1\.0\]/,/^## \[1\.0\.0\]/p' CHANGELOG.md | sed '$d' | gh release create v1.1.0 --verify-tag --title "1.1.0" -F -
git worktree add ../medrec-v1.1.0 v1.1.0         # build from the tag, never from the working tree
docker build -t medrec-app:1.1.0 --label org.opencontainers.image.version=1.1.0 \
  --label org.opencontainers.image.revision="$(git rev-list -n1 v1.1.0)" ../medrec-v1.1.0
git worktree remove ../medrec-v1.1.0
```
CHANGELOG skeleton (newest first, ISO dates, compare links at the bottom):
```md
## [Unreleased]
## [1.1.0] - YYYY-MM-DD
### Added
- Frequency-mismatch rule (`discrepancy_type = frequency_mismatch`); RxNorm normalization fills `rxcui`/`normalized_name`.
### Changed
- No schema changes. 1.0.0 can read all 1.1.0 data and shows new finding types as "Other (...)".
## [1.0.0] - YYYY-MM-DD
### Added
- Initial release: 3 rules, history view that tolerates unknown finding types.
[Unreleased]: https://github.com/<org>/<repo>/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/<org>/<repo>/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/<org>/<repo>/releases/tag/v1.0.0
```
Rollback demo (presenter runs each line; `APP_VERSION` set inline so a new terminal cannot silently flip versions):
```bash
APP_VERSION=1.1.0 docker compose up -d --no-build                # 0. start on 1.1.0
# 1. UI: reconcile a patient with a frequency mismatch; finding shows "Frequency mismatch"; footer shows 1.1.0
# 2. Backup + verify (blocks above); keep $F
APP_VERSION=1.0.0 docker compose up -d --no-build --no-deps app  # 3. roll back: only `app` is recreated; db + volume untouched
docker compose ps app; docker compose logs --tail 20 app         #    no schema errors; footer shows 1.0.0
# 4. UI: History -> 1.1.0 runs still listed; finding reads "Other (frequency_mismatch)"; run a new reconcile under 1.0.0 (works)
APP_VERSION=1.1.0 docker compose up -d --no-build --no-deps app  # 5. roll forward; both runs visible, proper label returns
```
Rehearse once end to end before Friday, including a backup + verify run in the same session.

## Gotchas
| Risk | Effect on rollback | Mitigation |
|---|---|---|
| V1 maps `discrepancy_type` to a Python `Enum`/Pydantic `Literal` | History page 500s on the first 1.1.0 finding | `str` in ORM and schemas; label dict with `.get(v, f"Other ({v})")`; test in 1.0.0 |
| PG ENUM or CHECK on `discrepancy_type` | V2 needs DDL; enum values cannot be removed afterwards | `TEXT`, no CHECK; validate in app code |
| V2 adds `NOT NULL` column without DEFAULT | V1 INSERTs fail; rollback breaks writes | V2 adds no DDL; any future column is nullable or has a non-volatile DEFAULT (metadata-only add in PG) |
| V2 adds a column V1 does not know | Harmless if ORM maps a subset and queries name columns; breaks `SELECT *` into strict row models | Explicit columns; no strict `SELECT *` parsing (ORM behaviour UNVERIFIED) |
| V1 `create_all`/migration runner on a V2-era DB | `create_all` only creates missing tables and never alters existing ones (SQLAlchemy docs); a runner that rejects unknown schema revisions would refuse to start | No DDL in V2, so no new revision; never run `drop_all`, `--clean` or truncating seeds at startup; seeds use `ON CONFLICT DO NOTHING` |
| V2 writes JSON shapes V1 cannot parse (new keys, retyped keys) | Detail view errors | Add keys only; V1 reads with `.get`, ignores unknown keys, renders details generically |
| V2 overwrites raw med fields while normalizing | V1 shows altered source data | Write only `rxcui`/`normalized_name`; raw columns are immutable |
| `docker compose down -v` or deleting the volume | History gone | Never use `-v`; backup first (`down` alone keeps named volumes) |
| `up --build` with `APP_VERSION=1.0.0` on a 1.1.0 checkout | 1.1.0 code tagged 1.0.0, rollback is fake | No `build:` in release compose; always `--no-build`; build from `git worktree` of the tag |
| Shell `APP_VERSION` overrides `.env` | A plain `docker compose up` in another terminal flips the version | `${APP_VERSION:?}` forces explicit setting; inline `APP_VERSION=...` in the demo |
| Backup taken while app is writing | Counts differ from the scratch DB, false alarm | Stop `app` (or compare right after dump) before verifying |
- **HAPI IDs (UNVERIFIED):** re-importing Synthea transaction bundles probably assigns new server-generated resource IDs, so a rebuilt HAPI may not match FHIR IDs stored in app history. Either store a self-contained snapshot (display name, med list) in each run, or add `hapi-db` to the backup (`pg_dump` the same way, restore both together). Decide with the data-model owner.
- Dumps contain patient data (synthetic Synthea, but treat it as PHI-like): gitignore `backups/`, never commit.
- PowerShell `>` redirection can corrupt binary output (UNVERIFIED): Windows users should use `pg_dump -f /tmp/x.dump` inside the container, then `docker compose cp app-db:/tmp/x.dump backups/`.
- Password prompt: the official image should allow local-socket connections without one when run via `exec` (UNVERIFIED); if prompted, pass `-e PGPASSWORD`.
- Contract phase (dropping columns) is out of scope for two releases: do it only once no supported rollback target needs the old shape, and expect `DROP COLUMN` to be irreversible data loss.
- Row counts catch missing data, not corruption. For extra confidence compare `max(id)` per table, or run the app's smoke test against the scratch DB.
- Not checked: `ALTER TYPE ... ADD VALUE` transaction restrictions (irrelevant if we use TEXT).

## Rejected alternatives
- **PG ENUM or CHECK list for finding types:** every new type is DDL; values cannot be removed; rollback target must understand them.
- **Down-migration scripts / reverse DDL:** drops data and is a rarely tested path; the rule makes it unnecessary.
- **Restore the pre-upgrade dump as the rollback:** discards history created by 1.1.0, so it fails the requirement.
- **Separate DB or volume per version:** two histories, no continuity.
- **Plain SQL (`-Fp`) dumps:** readable and diffable, but uncompressed, cannot select or reorder on restore, and `psql` continues past errors by default. Custom format wins.
- **`pg_dumpall`, volume tarballs, `pg_basebackup`:** we need one database and no global roles (`--no-owner`); file-level backups are server-version specific and want the server stopped.
- **Lightweight or moved tags; `latest` image tag:** not release markers; published tags must not move (git-tag docs).
- **Backing up HAPI by default:** extra moving part; data is reproducible from committed bundles (but see ID caveat).

## Sources
- [pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html): consistent concurrent dumps, formats (`-Fc`), `--no-owner`/`--clean`/`--if-exists`/`--create`, version compatibility, ANALYZE note (fetched 2026-10-29)
- [pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html): `--list`, `-d`, `--clean`, `--single-transaction`, stdin, `-j` needs a file, template0 (fetched 2026-10-29)
- [Backup and Restore: SQL Dump](https://www.postgresql.org/docs/current/backup-dump.html): snapshot semantics, createdb from template0, psql ON_ERROR_STOP, `-Fc` usage (fetched 2026-10-29)
- [PostgreSQL enumerated types](https://www.postgresql.org/docs/current/datatype-enum.html): values can be added or renamed, not removed or reordered (fetched 2026-10-29)
- [ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html): ADD COLUMN with non-volatile default needs no rewrite; DROP COLUMN semantics (fetched 2026-10-29)
- [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/): supported versions, current minors, EOL dates, minors need no dump/restore (fetched 2026-10-29)
- [Docker Hub: postgres](https://hub.docker.com/_/postgres): tags, volume path for 17 vs 18, `POSTGRES_USER`/`POSTGRES_DB` (fetched 2026-10-29)
- [Semantic Versioning 2.0.0](https://semver.org/): MAJOR/MINOR/PATCH rules, immutability of released versions, `v` prefix note (fetched 2026-10-29)
- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/): sections, Unreleased, ISO dates, compare links (fetched 2026-10-29)
- [git-tag](https://git-scm.com/docs/git-tag): annotated vs lightweight, `-a`/`-m`, do not re-tag published tags (fetched 2026-10-29)
- [gh release create](https://cli.github.com/manual/gh_release_create): `--verify-tag`, `-F -`, `--notes-from-tag`, missing-tag behaviour (fetched 2026-10-29)
- [Parallel Change](https://martinfowler.com/bliki/ParallelChange.html): expand, migrate, contract; applies to schema changes (fetched 2026-10-29)
- [Tolerant Reader](https://martinfowler.com/bliki/TolerantReader.html): Postel's law, ignore unknown fields (fetched 2026-10-29)
- [docker compose exec](https://docs.docker.com/reference/cli/docker/compose/exec/): `-T` for non-interactive use (fetched 2026-10-29)
- [docker compose up](https://docs.docker.com/reference/cli/docker/compose/up/): `--no-build`, `--no-deps`, recreate on image change, volumes preserved (fetched 2026-10-29)
- [docker compose down](https://docs.docker.com/reference/cli/docker/compose/down/): named volumes kept unless `-v` (fetched 2026-10-29)
- [Compose variable interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/): `${VAR:?err}`, shell env beats `.env`, works in `image:` (fetched 2026-10-29)
- [SQLAlchemy MetaData](https://docs.sqlalchemy.org/en/20/core/metadata.html): `create_all` creates only missing tables, does not alter (first 100k chars read; assumes the team uses SQLAlchemy, UNVERIFIED) (fetched 2026-10-29)
- [importlib.metadata](https://docs.python.org/3/library/importlib.metadata.html): `version()` needs the distribution installed (fetched 2026-10-29)
- [pyproject.toml guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/): static `version` field (fetched 2026-10-29)
- [OCI image annotations](https://github.com/opencontainers/image-spec/blob/main/annotations.md): `image.version`, `image.revision` labels (fetched 2026-10-29)
