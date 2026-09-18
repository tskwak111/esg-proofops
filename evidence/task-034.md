# TASK-034 verification evidence

Date: 2026-09-09 (Asia/Seoul)

## Scope

- Added an executable `local_synthetic` load profile: two real `POST /v1/runs` acceptances per tenant, followed by a barrier-released
  burst of 20 concurrent summary reads while those two runs remain active.
- The measurement object always reports `certification_status=not_certified`; its targets
  (read p95 1.0 s, accept p95 2.0 s) remain goals, not an availability claim.
- Added a durable SQLite fault-injection test: an expired lease cannot commit over the
  recovery worker's fenced checkpoint.

## Red-green record

1. `uv run pytest tests/acceptance/test_slo.py -q`
   - RED: collection failed with `ModuleNotFoundError: No module named 'tests.load'`.
2. After adding the minimum load-profile implementation:
   `uv run pytest tests/acceptance/test_slo.py -q`
   - GREEN: `1 passed in 0.01s`.

## Executed verification

| Command | Result |
| --- | --- |
| `uv run pytest tests/acceptance/test_slo.py tests/integration/test_worker_recovery.py tests/integration/test_run_lifecycle.py -q` | 39 passed; only upstream `TestClient` deprecation warnings |
| `uv run pytest tests/contracts/test_package_contracts.py -q` | 29 passed; only upstream `TestClient` deprecation warnings |
| `uv run ruff check tests/load/read_api.py tests/acceptance/test_slo.py tests/integration/test_worker_recovery.py` | passed |
| `uv run ruff format --check tests/load/read_api.py tests/acceptance/test_slo.py tests/integration/test_worker_recovery.py` | 3 files already formatted |
| `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src` | Success: no issues in 116 source files |
| `uv run python scripts/verify_architecture.py` | all checks passed |
| `uv run pytest tests/acceptance/test_slo.py -q` | 1 passed; only upstream `TestClient` deprecation warnings |
| `uv run python scripts/validate_package.py` | 705/705 contract/document checks passed; it does not execute app/model/cloud benchmarks |

## Local synthetic measurement sample

The corrected isolated temporary-DB sample exercised the real SQLite-backed run-creation
route, then 20 actual summary reads in the same database with two queued runs.
Each run has three unprocessed pages and zero extracted claims; this measures
local ASGI/SQLite overhead, not a populated-corpus or network performance benchmark.
Acceptance is measured before the read burst, not concurrently with that burst. It is not an account, pilot, staging, or
production measurement and is explicitly non-certified.

```json
{
  "environment": "local_synthetic",
  "certification_status": "not_certified",
  "read_count": 20,
  "read_status_codes": [200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200],
  "read_p95_seconds": 0.07512795785441995,
  "read_p95_target_seconds": 1.0,
  "accept_count": 2,
  "accept_status_codes": [202, 202],
  "accept_p95_seconds": 0.00897462503053248,
  "accept_p95_target_seconds": 2.0
}
```

## Not run

- Real AWS, Bedrock, customer document, approved account/pilot, staging deployment, and
  production availability measurements: `not_run` (no authorization or approved environment).
- Therefore no account/pilot SLO result or availability achievement is claimed.

Coordinator correction: the original profile read health on a separate empty DB
before creating any runs. A new check first failed with "read load must include
two active runs". The corrected shared-DB summary profile plus fencing check
passed 2 tests (`uv run pytest tests/acceptance/test_slo.py tests/integration/test_worker_recovery.py -q -s --tb=short`).
No deployed availability, steady-state throughput, or populated-report p95 is claimed.

Coordinator type-check follow-up: including `tests/load/read_api.py` exposed an
untyped default-argument lambda that the application-only mypy command did not
cover. Replaced it with stdlib `functools.partial`; the scoped six-module mypy
check, load-profile ruff check, and one SLO integration test passed afterward.
