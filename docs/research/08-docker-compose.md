# 08 — Docker Compose topology, healthchecks, and image tagging
OWNER: Devang Borkar, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
- **Compose file:** `compose.yaml`, no `version:` key, `name: medrec`, all secrets via `${VAR:?msg}` from a gitignored `.env` (`.env.example` committed).
- **HAPI health:** use the healthcheck class the HAPI image ships: `["CMD","java","-cp","/app","HealthCheck"]` (`start_period: 180s`, `interval: 15s`, `timeout: 10s`, `retries: 10`). No shell/curl needed. The importer also retries `GET /fhir/metadata` itself as a second layer.
- **Import job:** `importer` = plain `python:3.12.16-slim-trixie` + committed `seed/import_bundles.py` (stdlib `urllib`), `restart: "no"`, `depends_on: hapi: service_healthy`. It does: wait for `/fhir/metadata` -> `GET /fhir/Patient?_summary=count` -> exit 0 if `total > 0` -> else POST hospital/practitioner bundles, then patient bundles.
- **App start order:** `app` depends on `app-db: service_healthy` and `importer: service_completed_successfully`. A failed import blocks the app loudly instead of showing an empty UI.
- **Tagging:** `image: medrec-app:${APP_VERSION:-1.1.0}` plus `build:`. Build each release from its **git tag** (worktree), never from the current tree with a different tag.
- **Rollback:** `APP_VERSION=1.0.0 docker compose up -d --no-build --no-deps app` (shell var beats `.env`; `--no-deps` leaves DBs and importer untouched).

## Rationale
- `version:` is obsolete: Compose only warns and always validates against the latest schema.
- The HAPI default image is a distroless Java 21 nonroot build with no shell. Its Dockerfile compiles `HealthCheck.java` into `/app`. The class GETs `http://127.0.0.1:8080/actuator/health` and exits 0 on HTTP 200, else 1 (2s connect, 3s request timeout). `application.yaml` exposes only `health` over the web. A May 2026 fix ("Fix healthcheck for distroless image") is listed in release `image/v8.10.0-2`, so `v8.12.0-2` includes it.
- `start_period` failures are not counted toward `retries`; a healthcheck starts in `starting` state. HAPI on an empty Postgres creates its schema on first boot (`hbm2ddl.auto: update`), so allow a long `start_period`.
- `pg_isready` needs `-h 127.0.0.1`: the postgres entrypoint starts a temporary init server with `listen_addresses=''` (socket only), so a socket-based check can pass before the real server is up.
- Python image + mounted script avoids a second Dockerfile and a `curl`/shell dependency. `_summary=count` returns a Bundle with `total` and no entries.
- Strict `service_completed_successfully` on the app gives a deterministic clean-machine `docker compose up`. Escape hatch for debugging: `docker compose up -d --no-deps app`.
- Explicit `environment:` (not `env_file: .env`) so the app never receives the HAPI DB password.

## Pinned versions
| Item | Pin | Evidence (2026-10-29) |
|---|---|---|
| HAPI | `hapiproject/hapi:v8.12.0-2` | Pushed 2026-10-02, same digest as `latest`, amd64+arm64; Hub page lists 425 MB. `-tomcat` suffix = other variant. |
| Postgres | `postgres:16.15-alpine` | Tag exists (rebuilt 2026-10-26). Matches HAPI's own compose (`postgres:16-alpine`). Not 18: PGDATA/VOLUME moved to `/var/lib/postgresql`. |
| Python | `python:3.12.16-slim-trixie` | Latest 3.12 patch; `3.12-slim` already maps to trixie. |
| App | `medrec-app:1.0.0`, `:1.1.0` | Built locally from git tags `v1.0.0`, `v1.1.0` (tag names assumed). |
| Compose | >= 2.20.2 | `restart` on depends_on 2.17.0, `required` 2.20.0, `start_interval` 2.20.2 (Engine >= 25.0 for it). |

## Commands and config snippets

### DRAFT compose.yaml
```yaml
name: medrec
services:
  hapi-db:
    image: postgres:16.15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: hapi
      POSTGRES_DB: hapi
      POSTGRES_PASSWORD: ${HAPI_DB_PASSWORD:?set HAPI_DB_PASSWORD in .env}
    volumes: ["hapi-db-data:/var/lib/postgresql/data"]
    healthcheck: &pg-health
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 15s
  app-db:
    image: postgres:16.15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: medrec
      POSTGRES_DB: medrec
      POSTGRES_PASSWORD: ${APP_DB_PASSWORD:?set APP_DB_PASSWORD in .env}
    volumes: ["app-db-data:/var/lib/postgresql/data"]
    healthcheck: *pg-health
  hapi:
    image: hapiproject/hapi:v8.12.0-2   # distroless: no shell, curl or wget
    restart: unless-stopped
    depends_on:
      hapi-db: { condition: service_healthy }
    environment:
      SPRING_DATASOURCE_URL: jdbc:postgresql://hapi-db:5432/hapi
      SPRING_DATASOURCE_USERNAME: hapi
      SPRING_DATASOURCE_PASSWORD: ${HAPI_DB_PASSWORD:?set HAPI_DB_PASSWORD in .env}
      SPRING_DATASOURCE_DRIVER_CLASS_NAME: org.postgresql.Driver
      HIBERNATE_DIALECT: ca.uhn.fhir.jpa.model.dialect.HapiFhirPostgresDialect
      JAVA_TOOL_OPTIONS: -Xmx1g          # sizing UNVERIFIED; never add -Xms (the probe JVM inherits it)
    mem_limit: 2g
    healthcheck:
      test: ["CMD", "java", "-cp", "/app", "HealthCheck"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 180s
    ports: ["127.0.0.1:8080:8080"]       # HAPI has no auth; keep it on localhost
  importer:
    image: python:3.12.16-slim-trixie
    restart: "no"
    depends_on:
      hapi: { condition: service_healthy }
    environment:
      FHIR_BASE: http://hapi:8080/fhir
      PYTHONUNBUFFERED: "1"
    volumes: ["./seed:/seed:ro"]         # import_bundles.py + bundles/
    command: ["python", "/seed/import_bundles.py", "/seed/bundles"]
  app:
    image: medrec-app:${APP_VERSION:-1.1.0}
    build:
      context: ./app
      args: { APP_VERSION: "${APP_VERSION:-1.1.0}" }
    restart: unless-stopped
    depends_on:
      app-db:   { condition: service_healthy }
      importer: { condition: service_completed_successfully }
    environment:
      DATABASE_URL: postgresql://medrec:${APP_DB_PASSWORD:?set APP_DB_PASSWORD in .env}@app-db:5432/medrec
      FHIR_BASE_URL: http://hapi:8080/fhir
    ports: ["127.0.0.1:8000:8000"]
volumes:
  hapi-db-data:
  app-db-data:
```
`.env.example` (alphanumeric passwords only, they go into a URL): `APP_VERSION=1.1.0`, `HAPI_DB_PASSWORD=change-me`, `APP_DB_PASSWORD=change-me`. `.gitignore`: `.env`, `backups/`.

### DRAFT app/Dockerfile
```dockerfile
FROM python:3.12.16-slim-trixie
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
Add `app/.dockerignore` with `.git`, `.env`, `__pycache__`, `tests`.

### Releases and rollback
```bash
# one-time, from the repo root: build both images from their tags
git worktree add ../medrec-v1.0.0 v1.0.0
docker build --build-arg APP_VERSION=1.0.0 -t medrec-app:1.0.0 ../medrec-v1.0.0/app
git worktree add ../medrec-v1.1.0 v1.1.0
docker build --build-arg APP_VERSION=1.1.0 -t medrec-app:1.1.0 ../medrec-v1.1.0/app
cp .env.example .env && docker compose up -d      # clean machine: add --build if images are not built yet
APP_VERSION=1.0.0 docker compose up -d --no-build --no-deps app   # rollback, same app-db volume
docker compose up -d --no-build --no-deps app                     # roll forward (default 1.1.0)
docker compose ps && docker compose logs importer                 # health + import result
```
### Backup and restore (brief; release doc has detail)
```bash
docker compose exec -T app-db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backups/medrec-$(date +%Y%m%d-%H%M%S).dump
docker compose stop app
docker compose exec -T app-db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backups/<file>.dump
```
Custom-format archives need `pg_restore`; `--clean/--no-owner/--create` belong on `pg_restore`, not `pg_dump`.

## Gotchas
- **Data loss:** `docker compose down` keeps named volumes; `down -v` deletes them (both DBs). Never use `-v` in the rollback demo. Volumes are named `medrec_hapi-db-data` / `medrec_app-db-data` (project name prefix).
- **initdb env vars apply only to an empty data dir.** Changing `POSTGRES_PASSWORD` in `.env` later does not change the DB password; the app then fails auth. Fix with `ALTER USER`, or `down -v` (destroys data).
- **Env precedence:** shell > `--env-file` > project `.env`. `docker compose config` shows the resolved file. `${VAR:?}` errors on every command (including `down`) when `.env` is missing.
- **Rollback needs schema compatibility.** 1.1.0 migrations must be additive (new tables/nullable columns); 1.0.0 must not abort on an unknown schema revision (e.g. Alembic "revision not found" if it runs `upgrade` at startup). Test the 1.1.0 -> 1.0.0 -> 1.1.0 loop once.
- **Image content comes from the tag, not the tag name.** `APP_VERSION=1.0.0 docker compose build` would tag the *current* tree as 1.0.0. The v1.0.0 tree must also contain `/healthz` and the Dockerfile `HEALTHCHECK`.
- **Healthcheck cost:** every HAPI probe starts a JVM inside the HAPI container; keep >= 1 GB headroom (`-Xmx1g` in `mem_limit: 2g`) and `interval >= 15s`. Exit 137 = OOM, raise limits.
- **Stale docs:** the Docker Hub overview and README still mention `gcr.io/distroless/java-debian10:11` and a `-distroless` tag suffix; master's Dockerfile uses `java21-debian13:nonroot` as the default (last) stage and the Hub tag list shows only `-tomcat` suffixes. Trust the Dockerfile; smoke test `docker inspect --format '{{.State.Health.Status}}' <hapi container>`.
- **Partial import:** a crash mid-import leaves `Patient > 0`, so the next run skips. Optional hardening: PUT a marker resource after the last bundle and check that instead; or `down -v` the HAPI volume only (`docker volume rm medrec_hapi-db-data`).
- **Ports:** inside the network use container ports (`hapi:8080`, `app-db:5432`). HAPI ships `cors.allowed_origin: "*"` and no auth, so publish only on `127.0.0.1`.
- **HAPI RAM/time (UNVERIFIED):** no official heap guidance exists in the README or Hub page; 1 GB heap and 3 minute start window are starting guesses. Measure on a clean machine.

## Rejected alternatives
- **`hapiproject/hapi:...-tomcat` variant:** its stage does not copy `HealthCheck.class`; whether it has curl/wget is UNVERIFIED; larger runtime.
- **Custom HAPI image with curl/busybox:** extra build and drift for no gain over the shipped class.
- **No HAPI healthcheck, importer polling only:** works, but `compose ps` never shows HAPI healthy. Kept as the second layer only.
- **`curlimages/curl` importer:** bundle ordering and JSON handling get awkward in shell; Python stdlib is simpler and testable.
- **`profiles` for the importer:** names are valid, but the importer must run on plain `up`; whether profile-gated dependencies auto-start was not verified, so avoided.
- **`env_file: .env` on services:** leaks every secret to every container.
- **`depends_on ... required: false` for the importer:** only warns, hides a failed import.
- **Postgres 18:** volume mount path changed (`/var/lib/postgresql`); an accidental mount at `/var/lib/postgresql/data` on a future bump would bite.
- **Digest pins:** tags are mutable (Docker's guidance); digests are stricter but need upkeep. Tag pins suffice for the demo; pull once and keep images cached.

## Sources
- [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/): depends_on conditions, pg_isready healthcheck with `$$` escaping (fetched 2026-10-29)
- [Compose services reference](https://docs.docker.com/reference/compose-file/services/): depends_on `restart`/`required` versions, healthcheck fields, restart values, profiles, env_file, image+build, mem_limit (fetched 2026-10-29)
- [Compose version and name](https://docs.docker.com/reference/compose-file/version-and-name/), [variable interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/): `version` obsolete; `:-`/`:?` semantics, `.env` precedence (fetched 2026-10-29)
- [Compose build spec](https://docs.docker.com/reference/compose-file/build/) and [compose build CLI](https://docs.docker.com/reference/cli/docker/compose/build/): image+build behavior on `up`; build tags the service `image` name (fetched 2026-10-29)
- [compose up](https://docs.docker.com/reference/cli/docker/compose/up/), [down](https://docs.docker.com/reference/cli/docker/compose/down/), [exec](https://docs.docker.com/reference/cli/docker/compose/exec/): `--no-build`/`--no-deps`/`--wait`; volumes kept unless `-v`; TTY by default, `-T` (fetched 2026-10-29)
- [Compose volumes](https://docs.docker.com/reference/compose-file/volumes/): project-prefixed naming, reuse on `up` (fetched 2026-10-29)
- [Compose networking](https://docs.docker.com/compose/how-tos/networking/), [fragments](https://docs.docker.com/reference/compose-file/fragments/): default network and service-name DNS, container ports; YAML anchors (fetched 2026-10-29)
- [Dockerfile reference](https://docs.docker.com/reference/dockerfile/): HEALTHCHECK defaults, start_period/start_interval, USER (fetched 2026-10-29)
- [Build context](https://docs.docker.com/build/concepts/context/), [best practices](https://docs.docker.com/build/building/best-practices/), [Python guide](https://docs.docker.com/guides/python/containerize/): git-URL contexts; mutable tags, explicit non-root UID, exec-form CMD; uvicorn binding, `.dockerignore` (fetched 2026-10-29)
- [HAPI starter Dockerfile (raw)](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/master/Dockerfile) and [GitHub view](https://github.com/hapifhir/hapi-fhir-jpaserver-starter/blob/master/Dockerfile): distroless default stage, `/app/HealthCheck`, no HEALTHCHECK/Xmx (fetched 2026-10-29)
- [HAPI starter docker-compose.yml (raw)](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/master/docker-compose.yml) and [GitHub view](https://github.com/hapifhir/hapi-fhir-jpaserver-starter/blob/master/docker-compose.yml): Postgres env var names, commented healthcheck (fetched 2026-10-29)
- [HAPI starter README](https://github.com/hapifhir/hapi-fhir-jpaserver-starter): `java -cp /app HealthCheck`, stale distroless notes (fetched 2026-10-29)
- [HealthCheck.java](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/master/src/main/java/HealthCheck.java): probe URL, exit codes, timeouts (fetched 2026-10-29)
- [HAPI application.yaml](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/master/src/main/resources/application.yaml): actuator exposure, `/fhir` tester address, CORS, `hbm2ddl update`, dialect env var (fetched 2026-10-29)
- [HealthCheck.java history](https://github.com/hapifhir/hapi-fhir-jpaserver-starter/commits/master/src/main/java/HealthCheck.java) and [releases](https://github.com/hapifhir/hapi-fhir-jpaserver-starter/releases): fix shipped in `image/v8.10.0-2` (fetched 2026-10-29)
- [hapiproject/hapi on Docker Hub](https://hub.docker.com/r/hapiproject/hapi) and [tags API](https://hub.docker.com/v2/repositories/hapiproject/hapi/tags?page_size=25&ordering=last_updated): `v8.12.0-2` = `latest`, size, `-tomcat` variant (fetched 2026-10-29)
- [Postgres on Docker Hub](https://hub.docker.com/_/postgres), [16.15 tags](https://hub.docker.com/v2/repositories/library/postgres/tags?page_size=25&name=16.15): supported majors, empty-dir rule, PG18 path change (fetched 2026-10-29)
- [Postgres entrypoint](https://raw.githubusercontent.com/docker-library/postgres/master/18/alpine3.23/docker-entrypoint.sh): socket-only temp server, `PG_VERSION` skip logic (fetched 2026-10-29)
- [Python on Docker Hub](https://hub.docker.com/_/python), [3.12.16-slim tags](https://hub.docker.com/v2/repositories/library/python/tags?page_size=25&name=3.12.16-slim): 3.12.16, slim = trixie (fetched 2026-10-29)
- [pg_dump (PostgreSQL 16)](https://www.postgresql.org/docs/16/app-pgdump.html): `-Fc`, restore flags belong to pg_restore (fetched 2026-10-29)
- [FHIR R4 search](https://hl7.org/fhir/R4/search.html) and [FHIR R4 HTTP](https://hl7.org/fhir/R4/http.html): `_summary=count`, transaction/batch POST (fetched 2026-10-29)

UNVERIFIED (not run, not in a fetched source): published `v8.12.0-2` is the distroless default target and its probe passes at runtime; HAPI first-boot time and heap sizing; whether `up` restarts an exited importer and how `up --wait` treats exited-0 services; `pg_dump` via local socket needing no password; Synthea bundle filename patterns; Compose build fallback when the `image:` pull fails; `-T` fixing TTY corruption of dumps (docs only say TTY is on by default).
