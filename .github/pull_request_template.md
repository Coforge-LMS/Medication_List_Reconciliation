## Ticket

TEA-<!-- number --> — <!-- Linear issue link -->

## What changed

<!-- Describe the problem and resulting behavior. -->

## How it was tested

<!-- List commands and results; include relevant test IDs or manual checks. -->

## Checklist

- [ ] Linked the Linear ticket and kept changes within its scope.
- [ ] `uv run --locked ruff check .` passes.
- [ ] `uv run --locked ruff format --check .` passes.
- [ ] `uv run --locked pytest` passes (DB tests use a database ending in `_test`).
- [ ] Added or updated meaningful tests and documentation where needed.
- [ ] Used synthetic data only; included no credentials or patient data.
- [ ] CI checks `lint` and `test` pass, and a teammate has approved.
