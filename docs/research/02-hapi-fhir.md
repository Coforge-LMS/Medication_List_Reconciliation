# 02 — HAPI FHIR JPA server with PostgreSQL
OWNER: Rachit Shah, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
- Image: `hapiproject/hapi:v8.12.0-2` (pinned, never `latest`). FHIR R4, base URL `http://hapi:8080/fhir` inside Compose.
- Postgres: official starter env-var set (`SPRING_DATASOURCE_*` + `HIBERNATE_DIALECT`); no `application.yaml` mount needed. Dedicated `hapi-db` (`postgres:16-alpine`) with a named volume.
- Healthcheck: the image is distroless (no shell, curl or wget). Use the image's built-in probe: `test: ["CMD","java","-cp","/app","HealthCheck"]` (hits `/actuator/health`). Start period 120s.
- Import: curl-POST Synthea bundles in order hospitalInformation, practitionerInformation, then patient bundles. Defaults work: no settings changes needed.
- Re-run safety: check `Patient?_summary=count` first or wipe the HAPI volume. Patient bundles are plain POSTs, so a re-run duplicates patients.
- Leave request validation off (default). Set `JAVA_TOOL_OPTIONS=-Xms512m -Xmx1g` with a 2 GB container limit.

## Rationale
- v8.12.0-2 is the newest image on Docker Hub and the newest `image/*` release on GitHub (pushed 2026-10-02). The GitHub "Latest" badge is on `helm-v0.25.0`, the Helm chart, so ignore it.
- The official compose file at that tag uses exactly these env vars and a `HealthCheck` probe, so we follow a maintained path.
- Synthea's own export is built for this flow. Hospital/practitioner bundles use `ifNoneExist` (safe to reload). Patient bundles reference them by search URL (`Organization?identifier=...`, `Practitioner?identifier=...`), which HAPI resolves inside the transaction.
- The app only ever uses FHIR REST, so the HAPI schema stays private to HAPI.

## Pinned versions
| Item | Value | Note |
|---|---|---|
| Image | `hapiproject/hapi:v8.12.0-2` | git tag `image/v8.12.0-2`; HAPI 8.12.0; linux/amd64 + linux/arm64/v8 |
| Base | `gcr.io/distroless/java21-debian13:nonroot` | Java 21, UID 65532, no shell; image has no `EXPOSE`, server listens on 8080 |
| Variant to avoid | `-tomcat` suffix (`tomcat:10-jre21-temurin-noble`) | Not needed; shell/curl presence UNVERIFIED |
| Postgres | `postgres:16-alpine` | what the starter compose uses; HAPI docs list "Postgres" as supported but give no version list, so tested range is UNVERIFIED |
| Dialect | `ca.uhn.fhir.jpa.model.dialect.HapiFhirPostgresDialect` | required for Postgres (H2 and Postgres are not auto-detected) |
| Base path | `/fhir` | servlet mapped `/fhir/*`, load-on-startup 1, so it is ready when the Spring context is |
| Docs caveat | hapifhir.io docs are v9.0.0 | newer than the 8.12.0 image; trust starter source at the tag |

## Commands and config snippets
Compose (HAPI service names `hapi` and `hapi-db`):
```yaml
services:
  hapi-db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment: { POSTGRES_DB: hapi, POSTGRES_USER: hapi, POSTGRES_PASSWORD: hapi }  # demo creds; move to .env
    volumes: [hapi-db-data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U hapi -d hapi"]
      interval: 5s
      timeout: 5s
      retries: 10
  hapi:
    image: hapiproject/hapi:v8.12.0-2
    restart: on-failure
    depends_on: { hapi-db: { condition: service_healthy } }
    environment:
      SPRING_DATASOURCE_URL: jdbc:postgresql://hapi-db:5432/hapi
      SPRING_DATASOURCE_USERNAME: hapi
      SPRING_DATASOURCE_PASSWORD: hapi
      SPRING_DATASOURCE_DRIVER_CLASS_NAME: org.postgresql.Driver
      HIBERNATE_DIALECT: ca.uhn.fhir.jpa.model.dialect.HapiFhirPostgresDialect
      JAVA_TOOL_OPTIONS: "-Xms512m -Xmx1g"
    mem_limit: 2g
    ports: ["8080:8080"]   # host access for demo/Swagger; the app uses http://hapi:8080/fhir
    healthcheck:
      test: ["CMD", "java", "-cp", "/app", "HealthCheck"]
      interval: 15s
      timeout: 10s
      start_period: 120s
      retries: 12
volumes:
  hapi-db-data:
```
- Other services use `depends_on: hapi: {condition: service_healthy}` (the Synthea importer and the app, if it needs HAPI at start).
- Alternative if the probe misbehaves: an importer container polls `GET /fhir/metadata` until 200, then imports. No healthcheck needed on HAPI.
- `fhir_version: R4` is already the starter default; schema is created on first start (`hbm2ddl.auto: update`).

Synthea settings (defaults already right): `exporter.fhir.transaction_bundle=true`, `exporter.hospital.fhir.export=true`, `exporter.practitioner.fhir.export=true`, `exporter.fhir.use_us_core_ig=true` (defaults in `synthea.properties`).

Import (shell sketch, not app code; file-name case per Synthea output, verify):
```bash
BASE=http://localhost:8080/fhir; D=output/fhir
post(){ curl -sS -o /dev/null -w "%{http_code} $1\n" -H 'Content-Type: application/fhir+json' --data-binary @"$1" "$BASE"; }
curl -s "$BASE/Patient?_summary=count"            # Bundle.total > 0 means already imported: stop
for f in $(find $D -iname 'hospitalInformation*.json');     do post "$f"; done
for f in $(find $D -iname 'practitionerInformation*.json'); do post "$f"; done
for f in $(find $D -name '*.json' ! -iname 'hospitalInformation*' ! -iname 'practitionerInformation*'); do post "$f"; done
```
Expect `200` per transaction (FHIR spec); the Synthea wiki shows `201 Created` per entry inside the response bundle.

REST queries (all relative to `/fhir`):
- `Patient?_count=20&_sort=family&_total=accurate`, then follow `Bundle.link[relation=next].url` verbatim until absent.
- `Patient/{id}`
- `MedicationRequest?patient={id}&_count=100&_sort=-authoredon&_include=MedicationRequest:medication`
- Active only: add `&status=active`. Synthea emits only `active` or `completed`.
- Counts: `Patient?_summary=count`, `MedicationRequest?patient={id}&_summary=count`.
- `patient` and `subject` are both valid R4 MedicationRequest params; `status`, `authoredon`, `medication` (reference) and `code` (token) also exist.
- IDs are server-assigned (yaml comment says `SEQUENTIAL_NUMERIC`); treat as opaque strings.

## Gotchas
- Distroless: `CMD-SHELL` + curl/wget healthchecks fail (no shell). The probe accepts only HTTP 200 and has a 2s connect and 3s read timeout. It needs `management.endpoints.web.exposure.include: health` (already the default).
- Starter `application.yaml` comments are wrong on defaults. Code at the tag: `enforce_referential_integrity_on_write/delete = true`, `allow_external_references = false`, `allow_multiple_delete = false`, `auto_create_placeholder_reference_targets = false`, `default_page_size = 20`, `max_page_size = Integer.MAX_VALUE` (yaml comments say false/false/200). Treat code as truth.
- Hospital and practitioner bundles MUST load first. A conditional reference with zero or multiple matches fails the entire (atomic) transaction. A second Synthea run needs its own hospital/practitioner files loaded before its patients.
- Do not enable `allow_external_references`, placeholder auto-create or `mass_ingestion_mode`; Synthea references are all `urn:uuid:` or search URLs. Server rewrites `urn:uuid` to server IDs (FHIR spec).
- Idempotency: only Location, Organization and Practitioner get `ifNoneExist`. Patient POSTs have none, so a re-run creates duplicate patients with new IDs. Options: count check (above), `docker compose down -v`, or rewrite each patient entry with `ifNoneExist: identifier=https://github.com/synthetichealth/synthea|<Patient.identifier[0].value>` (that identifier exists on every Synthea Patient). The rewrite is optional and not tested.
- Medication shape: `MedicationRequest.medication[x]` is usually inline `medicationCodeableConcept` (RxNorm). A separate `Medication` resource is created only for inpatient-administered meds with US Core on, so `_include` often returns nothing. The app must read both forms.
- `hapi.fhir.*` env-var mapping for snake_case keys is UNVERIFIED (README only shows dotted names like `-e hapi.fhir.default_encoding=xml`). If a setting must change, mount an override at `/app/config/application.yaml` (pattern shown in the README).
- Paging links: `next` URL host comes from the incoming request unless `server_address` is set (UNVERIFIED). Call HAPI with the same base URL for every page.
- Cold start: UNVERIFIED, nothing measured (we cannot run Docker). Evidence: starter compose suggests `start_period: 60s`; its CI sleeps 80s for H2 on a runner. First boot on empty Postgres builds the schema and is slower, hence 120s.
- Import time and bundle size: UNVERIFIED. The starter sets no transaction-size limit (grepped `AppProperties`). Time one bundle before the demo, and keep the Synthea population small (for example `-p 10`).
- Swagger UI at `/fhir/swagger-ui/index.html` is enabled by default; useful for the demo.
- README tag note ("-distroless" suffix) is stale: tags with no suffix are the distroless image, `-tomcat` is the Tomcat variant.

- Validation, no profile checks by default: `hapi.fhir.validation.requests_enabled` and `responses_enabled` default `false`; the validating interceptor is only added when `requests_enabled` is true.
- Validation, still enforced: JSON/FHIR parse errors; invalid values (HAPI's default `LenientErrorHandler` throws on invalid values and invalid extensions, logs unknown elements); and reference integrity on write (target must exist).
- Validation, why off: Synthea claims US Core profiles; validating them needs the IG and terminology loaded, adds startup and import cost, and gains nothing for a demo. Turn on only if a requirement asks for it (UNVERIFIED how Synthea data fares).

## Rejected alternatives
- `latest` tag: moves under us; pin `v8.12.0-2`.
- `-tomcat` image to get a shell: needless; the built-in probe works on the default image.
- Own sidecar `curl` healthcheck, or full `application.yaml` mount: more moving parts than 5 env vars.
- H2 (starter default): in-memory and loses data; conflicts with the fixed Postgres architecture.
- Validation on, bulk `$import` / `bulk_import_enabled`, mass-ingestion mode: not needed at demo scale.

## Sources
- [HAPI starter releases](https://github.com/hapifhir/hapi-fhir-jpaserver-starter/releases): `image/v8.12.0-2` is newest image release (02 Oct); `helm-v0.25.0` holds the "Latest" badge (fetched 2026-10-29)
- [Docker Hub tags, hapiproject/hapi](https://hub.docker.com/r/hapiproject/hapi/tags): `v8.12.0-2`, pushed 27 days earlier; `-tomcat` variants (fetched 2026-10-29)
- [Dockerfile @ image/v8.12.0-2](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/Dockerfile): distroless java21-debian13 default stage, ENTRYPOINT, HealthCheck compiled, no EXPOSE (fetched 2026-10-29)
- [docker-compose.yml @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/docker-compose.yml): env vars, `postgres:16-alpine`, healthcheck block (fetched 2026-10-29)
- [application.yaml @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/src/main/resources/application.yaml): `${HIBERNATE_DIALECT}`, `fhir_version: R4`, actuator, `hbm2ddl update` (fetched 2026-10-29)
- [AppProperties.java @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/src/main/java/ca/uhn/fhir/jpa/starter/AppProperties.java): real defaults for integrity, paging, validation (fetched 2026-10-29)
- [FhirServerConfigCommon.java @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/src/main/java/ca/uhn/fhir/jpa/starter/common/FhirServerConfigCommon.java): properties wired into JpaStorageSettings (fetched 2026-10-29)
- [StarterJpaConfig.java @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/src/main/java/ca/uhn/fhir/jpa/starter/common/StarterJpaConfig.java): paging sizes and validating interceptor wiring (fetched 2026-10-29)
- [Application.java @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/src/main/java/ca/uhn/fhir/jpa/starter/Application.java): `/fhir/*` mapping, load-on-startup (fetched 2026-10-29)
- [HealthCheck.java @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/src/main/java/HealthCheck.java): probe URL, env vars, exit codes (fetched 2026-10-29)
- [build-images.yaml @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/.github/workflows/build-images.yaml): platforms amd64+arm64, default vs `-tomcat` tags (fetched 2026-10-29)
- [smoke-tests.yml @ tag](https://raw.githubusercontent.com/hapifhir/hapi-fhir-jpaserver-starter/image/v8.12.0-2/.github/workflows/smoke-tests.yml): CI waits 80s for startup (fetched 2026-10-29)
- [Starter README](https://github.com/hapifhir/hapi-fhir-jpaserver-starter/blob/master/README.md): Postgres yaml, `/app/config/application.yaml` mount, health check docs, stale tag note (fetched 2026-10-29)
- [HAPI Database Support](https://hapifhir.io/hapi-fhir/docs/server_jpa/database_support.html): Postgres supported, dialect class, no version list (fetched 2026-10-29)
- [HAPI JPA Configuration](https://hapifhir.io/hapi-fhir/docs/server_jpa/configuration.html): referential integrity, external references, search cache one minute (fetched 2026-10-29)
- [HAPI JPA Performance](https://hapifhir.io/hapi-fhir/docs/server_jpa/performance.html): bulk-load tuning; no documented bundle limit (fetched 2026-10-29)
- [HAPI LenientErrorHandler javadoc](https://hapifhir.io/hapi-fhir/apidocs/hapi-fhir-base/ca/uhn/fhir/parser/LenientErrorHandler.html): default parser handler behavior (fetched 2026-10-29)
- [HAPI Validation intro](https://hapifhir.io/hapi-fhir/docs/validation/introduction.html): validator kinds; says nothing on JPA defaults (fetched 2026-10-29)
- [Synthea wiki: FHIR Transaction Bundles](https://github.com/synthetichealth/synthea/wiki/FHIR-Transaction-Bundles): upload order, search-URL references, `ifNoneExist` reload safety (fetched 2026-10-29)
- [Synthea wiki: HL7 FHIR](https://github.com/synthetichealth/synthea/wiki/HL7-FHIR): exporter settings, POST with `application/fhir+json` (fetched 2026-10-29)
- [Synthea synthea.properties](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/synthea.properties): export defaults (fetched 2026-10-29)
- [Synthea FhirR4.java](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/java/org/mitre/synthea/export/FhirR4.java): POST + urn:uuid, `ifNoneExist` only for 3 types, MedicationRequest shape and status (fetched 2026-10-29)
- [Synthea ExportHelper.java](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/java/org/mitre/synthea/export/ExportHelper.java): search-URL formats, `UNDUPLICATED_FHIR_RESOURCES` (fetched 2026-10-29)
- [FHIR R4 RESTful API](https://hl7.org/fhir/R4/http.html): transaction atomicity, urn:uuid rewriting, conditional references, `If-None-Exist` (fetched 2026-10-29)
- [FHIR R4 Search](https://hl7.org/fhir/R4/search.html): `_count`, `next` link, `_sort`, `_include`, `_total`, `_summary=count` (fetched 2026-10-29)
- [FHIR R4 MedicationRequest](https://hl7.org/fhir/R4/medicationrequest.html): search params, status codes, `medication[x]` (fetched 2026-10-29)
- [Distroless README](https://github.com/GoogleContainerTools/distroless): no shell or package manager; `java21-debian13` exists (fetched 2026-10-29)
