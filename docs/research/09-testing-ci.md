# 09 — Testing strategy and GitHub Actions CI
OWNER: Devang Borkar, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
- **E2E: option C, where the CI half is B.** Every PR runs one pytest E2E: real Postgres (service container), FHIR calls served by `httpx.MockTransport` from the committed Synthea bundles, driven through the app's REST endpoints with FastAPI `TestClient`. Full `docker compose up` with real HAPI (A) is a manual rehearsal before Friday's demo, not a CI job.
- **CI jobs:** `lint` (ruff) and `test` (pytest + Postgres service), run in parallel on `pull_request` to `main` and `push` to `main`. Both are required status checks. Optional `compose-e2e` is manual-only (`workflow_dispatch`) and not required.
- **Isolation:** schema created once per session; `TRUNCATE ... RESTART IDENTITY CASCADE` at the start of each DB test; real commits (no outer transaction).
- **Layout:** `tests/<area>/test_<area>_*.py`, shared fixtures in `tests/conftest.py`, data in `tests/data/`. One marker: `e2e`. Pure tests (validation, rules, units) must not request the `db` fixture so they run without Postgres.
- Python 3.12, pip + `actions/setup-python` cache (uv swap shown below if the repo already uses uv).

## Rationale
- B exercises the real FHIR client code, rules, Postgres commit and REST read-back. Only the HAPI network hop is replaced, by real Synthea data, so "one end-to-end reconciliation" is credible. Needs the FHIR client to accept an injectable httpx transport or base client (ASSUMPTION: agree with the FHIR-client owner today).
- A in PR CI costs a 425 MB compressed HAPI image pull (hapiproject/hapi `latest`, amd64, per Docker Hub), a JVM boot (anecdotal 30-40 s, UNVERIFIED), the import job, and a flaky-failure risk on merge-critical checks the night before the demo. The demo itself is the A test.
- Real Postgres is mandatory for the rollback test. SQLAlchemy's savepoint recipe makes `commit()` inside a test not persist (it rolls back at teardown), so it hides exactly the commit/rollback behavior that test must observe. TRUNCATE on a tiny schema costs milliseconds.
- `httpx.MockTransport` ships with httpx (already needed: `TestClient` requires httpx), so no extra dependency; respx is richer but unnecessary.
- Estimated PR CI wall time 2-3 min (checkout, cached pip, image pull for `postgres:18-alpine`, a small suite). UNVERIFIED: no benchmark; measure on the first PR.
- Required-test mapping: validation/invalid inputs, per-rule (duplicate, missing, dosage mismatch), multi-finding medication, no-discrepancy patient, 500 mg vs 0.5 g are pure tests. Persistence success + rollback use `db`. E2E uses `db` + mock transport.

## Pinned versions
| Item | Pin | Note |
|---|---|---|
| pytest | `9.2.0` | PyPI latest, released 2026-10-27, Python >=3.10 |
| ruff | `0.17.3` | PyPI latest, released 2026-10-27; keep `ruff-pre-commit` rev `v0.17.3` identical if used |
| actions/checkout | `@v7` | v7.0.1 latest (Jul); v7 refuses fork-PR checkout in `pull_request_target`/`workflow_run` by default; irrelevant for `pull_request` |
| actions/setup-python | `@v7` | v7.1.0 latest (22 Oct); no input changes in v7; v6 needed runner >= 2.327.1 (GitHub-hosted is fine) |
| astral-sh/setup-uv | `@v10.3.3` | only if uv; NO floating `@v10` tag exists, tags are immutable; README pins SHA `68559e99cc807c1eb7e9238fd43a15bba460eec2` |
| Runner | `ubuntu-24.04` | image lists Python 3.12.15 cached, Docker Compose 2.38.2 |
| postgres | `postgres:18-alpine` | 18 is latest major (18.6); match the compose file's tag |
| hapiproject/hapi | `v8.12.0-2` | latest at fetch; pin the tag, never `latest` |

## Commands and config snippets
`.github/workflows/ci.yml` (DRAFT)
```yaml
name: ci
on:
  pull_request: { branches: [main] }   # no `paths:` filter, see Gotchas
  push: { branches: [main] }
  workflow_dispatch:
concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }
permissions: { contents: read }
jobs:
  lint:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with: { python-version: "3.12", cache: pip, cache-dependency-path: pyproject.toml }
      - run: pip install ruff==0.17.3
      - run: ruff check . && ruff format --check .
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    services:
      postgres:
        image: postgres:18-alpine
        env: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: medrec_test }
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/medrec_test  # scheme = app's driver
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with: { python-version: "3.12", cache: pip, cache-dependency-path: pyproject.toml }
      - run: pip install -e ".[dev]"
      - run: pytest
  compose-e2e:   # OPTIONAL: manual only, not a required check
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      - run: docker compose up -d --build --wait --wait-timeout 300   # needs healthchecks in compose
      - run: docker compose run --rm app <import-job-command>          # placeholder
      - run: pip install pytest==9.2.0 httpx && pytest tests/e2e_live
        env: { APP_URL: "http://localhost:8000" }   # tests skipif APP_URL unset
      - if: failure()
        run: docker compose logs --no-color
```
uv swap for both Python jobs: `- uses: astral-sh/setup-uv@v10.3.3` with `{ enable-cache: true, python-version: "3.12" }`, then `uv run --frozen pytest` (README example form).

`pyproject.toml`
```toml
[project.optional-dependencies]
dev = ["pytest==9.2.0", "ruff==0.17.3", "httpx"]
[tool.pytest.ini_options]
minversion = "9.0"
testpaths = ["tests"]
pythonpath = ["."]          # drop if package is pip install -e'd
addopts = "-ra --strict-markers --import-mode=importlib"   # ini_options addopts is one string
markers = ["e2e: one full reconciliation (real Postgres, mocked HAPI transport)"]
[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
ignore = ["E501"]           # formatter wraps best-effort and may leave long lines
```
Native `[tool.pytest]` (TOML types, lists for addopts) also works on pytest >= 9.0. Run locally: `docker compose up -d db`, then `pytest -m "not e2e"` for the fast loop.

`tests/conftest.py` (names in `<>` are placeholders)
```python
import os, json, pathlib, httpx, pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from <app.db> import Base

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(os.environ["DATABASE_URL"])
    assert eng.url.database.endswith("_test"), "refusing to TRUNCATE a non-test DB"
    Base.metadata.drop_all(eng); Base.metadata.create_all(eng)   # or: alembic upgrade head
    yield eng
    eng.dispose()

@pytest.fixture
def db(engine):                  # request only in tests that need Postgres
    names = ", ".join(t.name for t in Base.metadata.sorted_tables if t.name not in KEEP)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    with sessionmaker(engine)() as s:   # real commits, no outer transaction
        yield s

DATA = pathlib.Path(__file__).parent / "data"
def _fhir(request: httpx.Request) -> httpx.Response:   # extend to what the FHIR client calls
    rtype = request.url.path.rsplit("/", 1)[-1]          # e.g. /fhir/MedicationRequest
    pid = request.url.params["patient"]                  # param name: match the client
    bundle = json.loads((DATA / f"{pid}.json").read_text())
    hits = [e for e in bundle["entry"] if e["resource"]["resourceType"] == rtype]
    return httpx.Response(200, json={"resourceType": "Bundle", "type": "searchset", "entry": hits})

@pytest.fixture
def fhir_transport():
    return httpx.MockTransport(_fhir)    # inject via app.dependency_overrides[<get_fhir_client>]
```
Rollback test shape (success twin asserts `== 1` after commit):
```python
def test_failure_rolls_back(db, engine, monkeypatch):
    monkeypatch.setattr("<app.persistence.save_findings>", lambda *a, **k: 1 / 0)  # fails after run row flushed
    with pytest.raises(ZeroDivisionError):
        <persist_reconciliation>(db, <result>)
    with engine.connect() as c:          # separate connection sees committed data only
        assert c.scalar(text("select count(*) from <reconciliation_run>")) == 0
```
Reset overrides after each test: `app.dependency_overrides = {}` (fixture with `yield`, per FastAPI docs).

Branch protection (repo admin; replace OWNER/REPO; check names = job ids `lint`, `test`)
```bash
gh api -X PUT repos/OWNER/REPO/branches/main/protection \
  -H "Accept: application/vnd.github+json" --input - <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["lint", "test"] },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 1, "dismiss_stale_reviews": true },
  "restrictions": null
}
EOF
```
`strict`, `contexts`, `enforce_admins`, `required_pull_request_reviews`, `restrictions` are all required keys (nullable except `strict`/`contexts`). Newer form: `"checks": [{"context": "lint"}, {"context": "test"}]` (docs mark `contexts` as closing down; whether `checks` alone is accepted without `contexts` is UNVERIFIED). Use `--input`, not `-f` (`-f` is string-only; nested JSON is safer from a file or stdin).

## Gotchas
- TRUNCATE ... CASCADE is destructive: the engine fixture asserts a `*_test` database name. Never point `DATABASE_URL` at the compose dev DB.
- TRUNCATE also wipes the seeded pharmacy dataset. Either exclude those reference tables (`KEEP`) or re-seed inside `db`.
- No `paths:` or branch filter that can skip `ci.yml` on a PR: docs say a skipped workflow leaves required checks "Pending" and blocks merging. A job skipped by an `if:` reports success.
- Renaming a job `lint`/`test` silently breaks branch protection (check never reports); change the protection in the same PR. Do not make `compose-e2e` required.
- `workflow_dispatch` only works once `ci.yml` is on the default branch.
- Admins bypass branch protection by default; `enforce_admins: true` removes that. Flip to `false` if you want an emergency escape hatch before Friday.
- Private repo on GitHub Free: the plans page lists protected branches only under Pro/Team for private repos, so the PUT may be refused (403 per API docs; exact message UNVERIFIED). Fix: make the repo public or upgrade. Rulesets availability on Free private repos: UNVERIFIED.
- `strict: true` forces each PR to be current with `main` before merge; with 4 devs and a ~3 min CI this is acceptable, set `false` if the merge queue gets painful on Thursday night.
- Job directly on the runner reaches the service at `localhost:5432` (needs `ports`); if a job ever gets `container:`, use host `postgres`.
- `--import-mode=importlib`: tests cannot import from `conftest.py` or each other; share through fixtures. Keep file names unique anyway (`test_<area>_*.py`).
- `setup-uv` has no `@v10`; `@v10.3.3` or the SHA only. `enable-cache: auto` skips `pull_request_target`/`workflow_run`/release events, not `pull_request`.
- `docker compose up --wait` only waits for health if services define healthchecks. The HAPI starter has `/actuator/health` (exposure must be enabled) and a `java -cp /app HealthCheck` class; otherwise poll `/fhir/metadata`.
- No pytest-xdist: all tests share one database.
- pytest 9.2.0 and ruff 0.17.3 were released two days ago. If either breaks CI, pin the previous release (version not looked up).
- `httpx.MockTransport` with `AsyncClient`: the fetched docs page does not show it (it is a sync example); I recall it works for both, UNVERIFIED. Use sync `httpx.Client` in the FHIR client or test it first.
- pre-commit: skipped. CI is the gate and the team has one day. If wanted, 5 lines using `https://github.com/astral-sh/ruff-pre-commit` at `rev: v0.17.3` with hooks `ruff-check` and `ruff-format`.
- Not verified from a fetch: `timeout-minutes` semantics (standard key, kept as a safety net); `gh api` replacing `{owner}/{repo}` in endpoint paths (explicit names used instead).

## Rejected alternatives
- **A (full compose in every PR):** slow, large pull, JVM boot, flaky on required checks. Kept as manual `compose-e2e` / demo rehearsal only.
- **Transaction-per-test with SAVEPOINT (`join_transaction_mode="create_savepoint"`):** faster, but `commit()` never really commits, so the rollback/persistence tests would prove nothing; also the app's own sessions in `TestClient` calls would not share the test's transaction without extra wiring.
- **SQLite instead of Postgres:** cannot validate real commit/rollback semantics or Postgres types; contradicts the assignment's real-Postgres requirement.
- **respx, testcontainers, pytest-postgresql, tox/nox, coverage gates, Python version matrix:** extra dependencies or ceremony for no gain; a service container and one Python version suffice.
- **uv as default:** faster installs, but only worth it if `uv.lock` already exists; pip + `setup-python` cache needs nothing else.

## Sources
- [checkout releases](https://github.com/actions/checkout/releases) and [README](https://raw.githubusercontent.com/actions/checkout/main/README.md): `@v7` latest (v7.0.1), v7 fork-PR default, usage (fetched 2026-10-29)
- [setup-python releases](https://github.com/actions/setup-python/releases) and [README](https://raw.githubusercontent.com/actions/setup-python/main/README.md): v7.1.0, `@v7` usage, `cache: pip`, `cache-dependency-path`, v6 runner note (fetched 2026-10-29)
- [setup-uv releases](https://github.com/astral-sh/setup-uv/releases), [tags](https://github.com/astral-sh/setup-uv/tags), [README](https://raw.githubusercontent.com/astral-sh/setup-uv/main/README.md): v10.3.3, no floating major tags, immutable tags, SHA pin, `enable-cache` behavior (fetched 2026-10-29)
- [Creating PostgreSQL service containers](https://docs.github.com/en/actions/using-containerized-services/creating-postgresql-service-containers): service YAML, health options, `localhost` vs service label (fetched 2026-10-29)
- [Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax) and [Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows): concurrency, permissions, job name, branch filters, `workflow_dispatch` default-branch rule (fetched 2026-10-29)
- [Ubuntu 24.04 runner image](https://raw.githubusercontent.com/actions/runner-images/main/images/ubuntu/Ubuntu2404-Readme.md): Python 3.12.15 cached, Docker Compose 2.38.2 (fetched 2026-10-29)
- [pytest on PyPI](https://pypi.org/project/pytest/) and [ruff on PyPI](https://pypi.org/project/ruff/): 9.2.0 and 0.17.3, both 2026-10-27 (fetched 2026-10-29)
- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html), [good practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html), [fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html), [marks](https://docs.pytest.org/en/stable/how-to/mark.html): `ini_options` vs `[tool.pytest]`, importlib mode, `pythonpath`, conftest/yield fixtures, `--strict-markers` (fetched 2026-10-29)
- [ruff configuration](https://docs.astral.sh/ruff/configuration/), [linter](https://docs.astral.sh/ruff/linter/), [formatter](https://docs.astral.sh/ruff/formatter/), [ruff-pre-commit](https://github.com/astral-sh/ruff-pre-commit): defaults, `select`, exit codes, `format --check`, E501 note, hook ids (fetched 2026-10-29)
- [Branch protection REST API](https://docs.github.com/en/rest/branches/branch-protection?apiVersion=2022-11-28#update-branch-protection), [gh api manual](https://cli.github.com/manual/gh_api): PUT body fields, `checks`/`contexts`, `--input`, `-F`/`-f` (fetched 2026-10-29)
- [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches), [GitHub plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans), [Troubleshooting required status checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks): strict mode, admin bypass, plan limits, skipped checks stay Pending (fetched 2026-10-29)
- [SQLAlchemy 2.0 session transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html): savepoint test recipe, commit does not persist (fetched 2026-10-29)
- [httpx transports](https://www.python-httpx.org/advanced/transports/), [respx](https://lundberg.github.io/respx/): `MockTransport(handler)`, respx comparison (fetched 2026-10-29)
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/), [testing dependencies](https://fastapi.tiangolo.com/advanced/testing-dependencies/): `TestClient` needs httpx, `dependency_overrides` reset fixture (fetched 2026-10-29)
- [postgres image](https://hub.docker.com/_/postgres), [hapiproject/hapi tags](https://hub.docker.com/r/hapiproject/hapi/tags), [hapi-fhir-jpaserver-starter](https://github.com/hapifhir/hapi-fhir-jpaserver-starter): Postgres 18.x, HAPI v8.12.0-2 and 425 MB, `/fhir` path, health endpoint (fetched 2026-10-29)
- [docker compose up](https://docs.docker.com/reference/cli/docker/compose/up/): `--wait`, `--wait-timeout` (fetched 2026-10-29)
