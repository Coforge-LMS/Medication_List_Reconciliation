# Medical_List_Reconciliation

Medication reconciliation using synthetic FHIR and pharmacy data.

## Local Compose stack (TEA-49)

Requires Docker with Compose v2.20+ and enough memory for HAPI (2 GiB container
limit) plus two Postgres instances. Run commands from the repository root.

The root Compose file in `infra/docker-compose.yml` starts HAPI and two databases, imports FHIR bundles, and seeds intake CSVs before starting the app. All seed inputs are committed.

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
docker compose logs --timestamps importer app-seed
curl --fail http://127.0.0.1:8000/healthz
```
