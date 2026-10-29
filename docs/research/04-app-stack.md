# 04 — App stack: FastAPI, Jinja2/HTMX, SQLAlchemy, httpx
OWNER: Sarthak Kakkar, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
- **Web**: FastAPI 0.162.0 + Uvicorn 0.54.0 + Jinja2 3.1.6 (server-rendered) + python-multipart 0.0.32 (for `Form()`).
- **UI**: HTMX 2.0.11, vendored as `app/static/htmx.min.js`; every page must work as a plain form first (`hx-boost` / `hx-post` is optional polish).
- **Data**: pydantic 2.14.1, SQLAlchemy 2.0.55 (sync), psycopg[binary] 3.3.6, URL `postgresql+psycopg://`.
- **HTTP/FHIR**: httpx 0.28.1 + plain dicts + our own small pydantic models (no FHIR library).
- **Routes**: plain `def` everywhere (routes, dependencies); no `async def`.
- **Deps**: `pyproject.toml` + `uv.lock` (uv 0.13.6); `uv export` to requirements.txt is the pip fallback.
- **Tests**: pytest 9.2.0, FastAPI `TestClient`, `app.dependency_overrides` for DB session + FHIR client, `httpx.MockTransport` for the FHIR client.
- **Deviations from the default proposal** (all deliberate): SQLAlchemy 2.0.55 not 2.1.6; htmx 2.0.11 not 4.0.0; httpx 0.28.1 not httpx2.

## Rationale
- FastAPI wins on "REST endpoints + HTML pages in one app": pydantic validation is native, `/docs` gives a free API demo, and dependency injection makes the DB and FHIR client trivially swappable in tests. Flask is the real runner-up; if the team knows Flask much better, use it (cost difference is small).
- Sync is the right default: FastAPI docs say libraries without `await` support (most DB libs) belong in plain `def` routes, which run in an external threadpool; "if you just don't know, use normal def". AnyIO's default limit is 40 worker threads, ample for a demo.
- Blocking calls (sync httpx, SQLAlchemy, PDF generation) inside `async def` would block the event loop, so don't mix.
- SQLAlchemy 2.0.55 over 2.1.6: 2.1.0 shipped only 2026-09-24 (6 patch releases in 4 weeks); 2.0 is still maintained (2.0.55 on 2026-10-16) and is what most docs/snippets target. 2.1 would also work on 3.12 (needs >=3.11). Nothing in 2.1 is needed for us.
- htmx 2.0.11 is the npm `latest` tag; 4.0.0 is only on `next` and htmx.org says 4 becomes `latest` "at some point in 2027". Size ~16k min+gz per htmx.org.
- httpx 0.28.1 is the last stable release (2024-12-06). Only 1.0.devN pre-releases exist, so a plain `pip install httpx` stays on 0.28.1. See Gotchas for the Starlette/httpx2 wrinkle.
- FHIR client: we need ~5 fields from Patient and MedicationRequest plus Bundle paging. A 30-line httpx wrapper beats a library here:
  - `fhirclient` 4.4.0 (2026-02-10): R4 4.0.1, but built around SMART OAuth flows (out of scope); HTTP layer is not httpx (`requests`, UNVERIFIED).
  - `fhir.resources` 8.3.0 (2026-07-03, pydantic v2, 2.3 MB wheel): default is R5; R4 is served by the `R4B` subpackage ("no separate R4"); full-resource strict validation can reject sparse synthetic data. Reasonable later upgrade, overkill for day one.
  - `fhirpy` 2.3.2 (2026-10-27, py 3.9-3.12): thin and active, but sync client rides on requests and async on aiohttp, so no httpx mocking and two more deps.
- uv over pip+requirements.txt: a lockfile pins transitive deps (FastAPI shipped ~10 releases in 3 days, Starlette 1.10.0 floats under it), and FastAPI's own Docker docs show the uv path. pip stays available through `uv export`.

## Pinned versions
Checked on PyPI/npm 2026-10-29. "OK on 3.12" is from `requires_python`/classifiers only, not from a test run.
| Package | Pin | Released | requires-python | 3.12 |
|---|---|---|---|---|
| fastapi | 0.162.0 | 2026-10-23 | >=3.10 (classifiers 3.10-3.14) | OK |
| starlette (transitive) | 1.10.0 | 2026-10-24 | >=3.11 | OK |
| uvicorn | 0.54.0 | 2026-09-25 | >=3.10 | OK |
| jinja2 | 3.1.6 | 2025-03-05 | >=3.7 | OK |
| python-multipart | 0.0.32 | 2026-06-04 | >=3.10 | OK |
| pydantic | 2.14.1 | 2026-10-11 | classifiers 3.10-3.15 | OK |
| sqlalchemy | 2.0.55 (alt 2.1.6, 2026-10-21, >=3.11) | 2026-10-16 | >=3.7 | OK |
| psycopg[binary] | 3.3.6 (+ psycopg-binary 3.3.6) | 2026-09-18 | >=3.10; cp312 manylinux x86_64 and aarch64 wheels exist | OK |
| httpx | 0.28.1 | 2024-12-06 | >=3.8 | OK |
| htmx.org (JS) | 2.0.11 | npm `latest` (date UNVERIFIED) | n/a | n/a |
| pytest (dev) | 9.2.0 | 2026-10-27 | >=3.10 | OK |
| uv (tool) | 0.13.6 | 2026-10-27 | n/a | n/a |
Optional, not recommended: respx 0.23.1 (2026-04-08, needs httpx>=0.25); httpx2 2.16.0 (2026-10-21, >=3.11).

## Commands and config snippets
`pyproject.toml`:
```toml
[project]
name = "medrec"
version = "0.1.0"
requires-python = "==3.12.*"
dependencies = ["fastapi==0.162.0", "uvicorn==0.54.0", "jinja2==3.1.6", "python-multipart==0.0.32",
  "pydantic==2.14.1", "sqlalchemy==2.0.55", "psycopg[binary]==3.3.6", "httpx==0.28.1"]
[dependency-groups]
dev = ["pytest==9.2.0"]
[tool.uv]
package = false   # app, not a library: uv installs deps only
```
Setup: `uv lock && uv sync` then `uv run pytest`, `uv run uvicorn app.main:app --reload`. Vendor HTMX once and commit it:
`curl -L -o app/static/htmx.min.js https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js`
Dockerfile (add `.venv` to `.dockerignore`; use Debian `-slim`, not Alpine):
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_NO_DEV=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
pip fallback: `uv export --format requirements-txt --no-dev --no-emit-project --output-file requirements.txt`, then `pip install --no-cache-dir -r requirements.txt`.
GitHub Actions steps (uv docs pin actions by SHA; tags shown for readability):
```yaml
- uses: actions/checkout@v7.0.1
- uses: astral-sh/setup-uv@v9.0.0
  with: { enable-cache: true, python-version: "3.12" }
- run: uv sync --locked
- run: uv run pytest
```
FHIR client (inject the `httpx.Client`; follow Bundle `next` links, which the spec says are opaque):
```python
class FhirClient:
    def __init__(self, c: httpx.Client): self.c = c   # base_url=FHIR_BASE_URL, timeout set
    def search(self, path, **params):
        url, params = path, params
        while url:
            r = self.c.get(url, params=params or None, headers={"Accept": "application/fhir+json"})
            r.raise_for_status(); b = r.json()
            yield from (e["resource"] for e in b.get("entry", []))
            url = next((l["url"] for l in b.get("link", []) if l["relation"] == "next"), None); params = {}
```
Test wiring:
```python
@pytest.fixture
def client(db_session):
    mock = httpx.Client(base_url="http://fhir.test/fhir", transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_fhir] = lambda: FhirClient(mock)
    with TestClient(app) as c: yield c          # `with` is what runs lifespan
    app.dependency_overrides.clear()
```
`handler(request)` returns `httpx.Response(200, json=<fixture Bundle>)`. Test DB: Postgres service container in CI (high fidelity) or SQLite in-memory with `check_same_thread=False` (FastAPI's SQL tutorial says a request can use several threads; extra pool settings UNVERIFIED).
Layout:
```
pyproject.toml  uv.lock  Dockerfile  docker-compose.yml  .dockerignore
app/ main.py (FastAPI(lifespan=...), mount /static, include routers)  config.py (env vars)  deps.py (get_db yield Session, get_fhir, templates)
     routes/pages.py (HTML)  routes/api.py (JSON)  fhir/{client,models}.py  pharmacy/loader.py
     rules/{base,v1_*}.py  db/{models,session}.py  pdf.py
     templates/ base.html patients.html patient.html compare.html findings.html history.html _findings.html
     static/ htmx.min.js  app.css
tests/ conftest.py  fixtures/*.json  test_rules.py  test_fhir_client.py  test_pages.py
```
HTMX partial vs plain form (same route; branch on the `HX-Request` header htmx sends):
```html
<!-- plain: full page via 303 redirect -->  <form method="post" action="/patients/{{ p.id }}/run"><button>Run</button></form>
<!-- htmx: swaps only the target (default swap is innerHTML) -->
<button hx-post="/patients/{{ p.id }}/run" hx-target="#findings" hx-disabled-elt="this">Run</button><div id="findings"></div>
```
```python
@router.post("/patients/{pid}/run")
def run(pid: str, request: Request, db: DB, fhir: FHIR):
    result = service.run(pid, db, fhir); db.commit()          # commit here, not in dep teardown
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_findings.html", {"result": result})
    return RedirectResponse(f"/runs/{result.id}", status_code=303)
```
Cutting HTMX = delete the `hx-*` attributes and the `if` branch; nothing else changes.

## Gotchas
- **FastAPI churn**: 0.157.0 to 0.162.0 shipped Oct 21-23; 0.160.0 and 0.162.0 are flagged breaking (parameter-model `extra` handling; "restore default handling for omitted boolean form fields"). Pin exactly, commit `uv.lock`, don't upgrade before Friday. Declare checkbox fields with an explicit default and test the unchecked case.
- **TestClient and httpx**: Starlette 1.10 `TestClient` prefers `httpx2`; with plain httpx it works but emits a `StarletteDeprecationWarning`. Ignore it, or add dev dep `httpx2==2.16.0` to silence it (TestClient tries httpx2 first; app code still uses httpx). Not run locally, so "works with httpx 0.28.1" is from Starlette's source/docs only (UNVERIFIED by execution).
- **`TemplateResponse(request, "x.html", ctx)`**: request is the first argument (old name-first form is pre-0.108.0).
- **Autoescape** is on for `.html`; never use `|safe` on FHIR or pharmacy strings.
- **Yield dependencies**: teardown runs after the response is sent (default scope), so commit inside the route.
- **Lifespan**: use `lifespan` for `create_all`; `on_event` is deprecated and ignored when `lifespan` is set. In Compose the app may start before Postgres is ready (healthcheck or retry).
- **Driver URL**: use `postgresql+psycopg://`. SQLAlchemy 2.1 makes bare `postgresql://` mean psycopg 3; on 2.0 a bare URL would not (default driver on 2.0 UNVERIFIED here).
- **htmx** doesn't swap 4xx/5xx responses (it fires `htmx:responseError`): return 200 with an error fragment or add a handler.
- **FHIR**: send `Accept: application/fhir+json` (`_format` exists for clients that can't set headers); set an explicit httpx timeout; never build page URLs, follow `next`.
- **Don't** install `fastapi[standard]`: it adds opentelemetry-sdk, email-validator, pydantic-settings, uvicorn[standard], fastapi-cli, etc. `fastapi` + the explicit list above is enough.
- Not done: no `uv lock`, no install, no test run; resolution of the pin set together is UNVERIFIED.

## Rejected alternatives
- **Flask 3.1.3 + Jinja2** (2026-02-19, >=3.9): fine and equally small, but no built-in pydantic validation or DI-based test overrides; we'd hand-roll both.
- **Django 6.1.2** (2026-10-06, >=3.12): brings its own ORM/migrations/settings, conflicts with the fixed SQLAlchemy choice, and is heavy for 3 rules and ~7 pages.
- **Streamlit 1.66.1** (>=3.11): quickest demo UI, but it is not a REST backend, reruns the script on every interaction, and is awkward for history, PDF export and layered tests.
- **React SPA + API**: Node build tooling, CORS, second container; out of scope.
- **httpx2 2.16.0 as app client**: Pydantic-maintained successor to httpx, but 4 releases in Oct 18-21 alone, import name `httpx2` (not documented as drop-in), respx compatibility UNVERIFIED. Revisit after the demo.
- **htmx 4.0.0**, **SQLAlchemy 2.1.6**, **fhir.resources / fhirclient / fhirpy**, **pip-only requirements.txt**: see Rationale.
- **Async stack** (async SQLAlchemy, asyncpg): extra moving parts for no benefit at this scale.

## Sources
- PyPI/npm pins (version, date, requires-python): [fastapi](https://pypi.org/project/fastapi/), [fastapi 0.162.0 metadata](https://pypi.org/pypi/fastapi/0.162.0/json), [uvicorn](https://pypi.org/project/uvicorn/), [jinja2](https://pypi.org/pypi/jinja2/json), [python-multipart](https://pypi.org/pypi/python-multipart/json), [pydantic](https://pypi.org/project/pydantic/), [SQLAlchemy](https://pypi.org/project/SQLAlchemy/), [sqlalchemy 2.0.55](https://pypi.org/pypi/sqlalchemy/2.0.55/json), [psycopg](https://pypi.org/project/psycopg/), [psycopg-binary](https://pypi.org/project/psycopg-binary/), [httpx](https://pypi.org/project/httpx/), [pytest](https://pypi.org/project/pytest/), [uv](https://pypi.org/project/uv/), [htmx npm latest](https://registry.npmjs.org/htmx.org/latest), [htmx dist-tags](https://registry.npmjs.org/-/package/htmx.org/dist-tags) (fetched 2026-10-29)
- [Starlette PyPI](https://pypi.org/project/starlette/), [starlette 1.10.0 metadata](https://pypi.org/pypi/starlette/1.10.0/json), [testclient.py](https://raw.githubusercontent.com/Kludex/starlette/main/starlette/testclient.py), [TestClient docs](https://starlette.dev/testclient/), [templates docs](https://starlette.dev/templates/), [release notes](https://starlette.dev/release-notes/): httpx2 vs httpx in TestClient, autoescape, Python >=3.11 from 1.8 (fetched 2026-10-29)
- [httpx2 PyPI](https://pypi.org/project/httpx2/): successor project, 2.16.0, release cadence (fetched 2026-10-29)
- FastAPI docs: [templates](https://fastapi.tiangolo.com/advanced/templates/), [testing](https://fastapi.tiangolo.com/tutorial/testing/), [testing dependencies](https://fastapi.tiangolo.com/advanced/testing-dependencies/), [async/threadpool](https://fastapi.tiangolo.com/async/), [Docker](https://fastapi.tiangolo.com/deployment/docker/), [forms](https://fastapi.tiangolo.com/tutorial/request-forms/), [yield deps](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/), [SQL tutorial](https://fastapi.tiangolo.com/tutorial/sql-databases/), [lifespan](https://fastapi.tiangolo.com/advanced/events/), [release notes](https://fastapi.tiangolo.com/release-notes/), GitHub releases [0.162.0](https://github.com/fastapi/fastapi/releases/tag/0.162.0) and [0.160.0](https://github.com/fastapi/fastapi/releases/tag/0.160.0) (fetched 2026-10-29)
- [AnyIO threads](https://anyio.readthedocs.io/en/stable/threads.html): default 40 worker threads (fetched 2026-10-29)
- SQLAlchemy: [2.1 migration notes](https://docs.sqlalchemy.org/en/21/changelog/migration_21.html), [2.1 changelog](https://docs.sqlalchemy.org/en/21/changelog/changelog_21.html), [2.0 changelog](https://docs.sqlalchemy.org/en/20/changelog/changelog_20.html), [PostgreSQL dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html): 2.1.0 on 2026-09-24, 2.0.55 current, `postgresql+psycopg://` form (fetched 2026-10-29)
- htmx: [homepage](https://htmx.org/), [docs](https://htmx.org/docs/), [GitHub releases](https://github.com/bigskysoftware/htmx/releases), [htmx.min.js 2.0.11](https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js): version, 4xx/5xx handling, hx-boost, vendoring URL (fetched 2026-10-29)
- Mocking: [httpx transports](https://www.python-httpx.org/advanced/transports/), [respx docs](https://lundberg.github.io/respx/), [respx PyPI](https://pypi.org/project/respx/) (fetched 2026-10-29)
- FHIR libs: [fhirclient PyPI](https://pypi.org/project/fhirclient/), [client-py](https://github.com/smart-on-fhir/client-py), [fhir.resources PyPI](https://pypi.org/project/fhir.resources/), [fhir.resources repo](https://github.com/nazrulworld/fhir.resources), [fhirpy PyPI](https://pypi.org/project/fhirpy/), [fhir-py repo](https://github.com/beda-software/fhir-py), [FHIR R4 HTTP](https://hl7.org/fhir/R4/http.html) (fetched 2026-10-29)
- uv: [Docker guide](https://docs.astral.sh/uv/guides/integration/docker/), [GitHub Actions guide](https://docs.astral.sh/uv/guides/integration/github/), [project config](https://docs.astral.sh/uv/concepts/projects/config/), [dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/) (fetched 2026-10-29)
- Alternatives: [Flask](https://pypi.org/project/Flask/), [Django](https://pypi.org/project/Django/), [Streamlit](https://pypi.org/project/streamlit/) (fetched 2026-10-29)
