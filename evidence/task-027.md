# TASK-027 verification evidence

Date: 2026-09-09 (Asia/Seoul)

Scope: `packages/proofops/application/coverage.py`, `apps/web/src/features/runs/CoveragePanel.tsx`, and `tests/acceptance/test_coverage.py`. Fixtures are explicitly local synthetic counters; no model, AWS, customer data, legal decision, or external mutation was used.

## Red → green

- `uv run pytest tests/acceptance/test_coverage.py -q` before implementation: exit 2, collection failed with `ModuleNotFoundError: No module named 'proofops.application.coverage'`.
- `uv run pytest tests/acceptance/test_coverage.py -q` after implementation: exit 0, `16 passed in 0.04s`.

The acceptance suite covers full-scope completion, review-pending separation, forced `partial` on `BUDGET_EXHAUSTED`, declared subsets, unreadable pages, invalid/negative/boolean counters, non-completed states, and concurrent deterministic projection.

## Verification

- `uv run ruff check packages/proofops/application/coverage.py tests/acceptance/test_coverage.py`: exit 0, `All checks passed!`.
- `uv run mypy packages/proofops/application/coverage.py`: exit 0, `Success: no issues found in 1 source file`.
- `pnpm --dir apps/web typecheck`: exit 0, TypeScript emitted no errors.
- `pnpm --dir apps/web build`: exit 0, Vite built 31 modules (`dist/assets/index-Brgz22Va.js`, 214.26 kB; gzip 67.45 kB).
- `uv run pytest tests/unit -q`: exit 0, `16 passed in 1.41s`.
- `uv run pytest tests/contracts/test_package_contracts.py -q`: exit 0, `29 passed, 2 warnings in 2.07s`; warnings are existing FastAPI/Starlette deprecations.
- `uv run pytest tests/integration/test_run_lifecycle.py -q`: exit 0, `35 passed, 2 warnings in 8.56s`; same existing deprecations.
- `uv run pytest tests/integration/test_local_parser_runner.py -q`: exit 0, `15 passed, 2 warnings in 9.48s`; same existing deprecations.
- `uv run pytest tests/acceptance/test_coverage.py tests/acceptance/test_jobs.py tests/acceptance/test_claims.py -q`: exit 0, `51 passed in 2.63s`.
- `uv run pytest tests/acceptance/test_session_security.py -q`: exit 0, `13 passed, 2 warnings in 2.15s`; same existing deprecations.
- `uv run python scripts/verify_architecture.py`: exit 0, all purity, DTO-boundary, port, composition, and fixed LLM-tag contract checks passed.
- `git diff --check -- packages/proofops/application/coverage.py apps/web/src/features/runs/CoveragePanel.tsx tests/acceptance/test_coverage.py`: exit 0, no output.

## Gates and limits

- E2E: `not_run`; this web package has no `test` script or Playwright configuration. Typecheck and production build are the available component checks.
- Real model/AWS/staging: `not_run` by task boundary. The parser integration is local synthetic and is not evidence of AWS deployment or model accuracy.
- Dependency/license scan: not applicable; no dependency or lockfile changed.
- Human legal/data/rights approval: blocked/not_run by contract and not required for the synthetic coverage calculation.
- The fixed API schema has no explicit chunk/claim excluded or failed fields; the implementation preserves its approved counters and leaves unprocessed claims visible as the residual instead of converting them to absent. No shared contract was changed.
