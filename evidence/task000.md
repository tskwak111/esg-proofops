# TASK-000 evidence — contract bootstrap

Date: 2026-09-09 (KST). No worker commit (coordinator owns Git). No live
Bedrock/product model calls, no AWS mutation, no GitHub push, no secrets.
Sibling-owned files (`docs/IMPLEMENTATION_STATUS.md`,
`evidence/contract_review_resolution.md`, `evidence/package_validation.*`,
`scripts/validate_package.py`, `tests/unit/test_package_validation.py`)
were read, never edited. Contracts/config/docs frozen and untouched.

## What was built (owned files only)

- `pyproject.toml` + `uv.lock`: uv workspace (Python 3.12), members
  `packages/proofops`, `apps/api`, `apps/worker`, `apps/agent`; dev group
  pytest/httpx/ruff/mypy/jsonschema/pyyaml.
- `packages/proofops/`: direct `proofops` namespace per catalog —
  `domain/values.py` (immutable SourceRef/LlmElement/LlmTags; source-less
  present refused; LLM grade/label fields refused; unknown keys, missing
  required fields, non-UUID, bool-as-int, infinite bbox refused; mutable
  inputs defensively copied to tuples), `domain/errors.py`,
  `application/ports/models.py` (TaggerPort), `adapters/local/models.py`
  (local-only SyntheticTagger; BedrockTagger stub refuses), `composition.py`
  (local-only root; non-local fails closed for ALL adapters).
- `apps/api/src/proofops_api/`: `dto.py` (Pydantic v2 strict/frozen/forbid —
  RunCreate scope rules, Decision grade/label map + hex + PERF/IMPL-only
  sublabel + blocked-null rule; narrow UUID-string/array pre-coercion so
  real HTTP JSON validates while bool/int still rejects), `main.py`
  (`create_app` executes the composition guard; `/v1/health/live|ready`),
  `composition.py` env boundary.
- `apps/worker`, `apps/agent`: composition-wired entrypoints; agent tagging
  boundary validates without grading; consumer lease/fencing is TASK-028
  (`NotImplementedError`, reported as not_run).
- `apps/web` + `package.json` + `pnpm-workspace.yaml` + `pnpm-lock.yaml`:
  React 19/TS/Vite runnable baseline (`typecheck` + `build`; script named
  `test` renamed to `typecheck` per coordinator — no real web tests yet).
- `tests/contracts/test_package_contracts.py`: 27 tests, incl. negative
  matrix against fixed fixtures (10 both-reject + 3 stricter-reject cases),
  real HTTP POST with JSON UUID strings/page list, startup-guard tests.
- `scripts/verify_architecture.py`: recursive `domain/*.py` purity scan
  (stdlib only; rejects adapters/composition/application imports, app
  packages, fastapi, pydantic, SDK/IO), pydantic-only DTO check, port +
  fail-closed + read-only contract checks.

## Command results (all executed, exit 0 unless noted)

- `uv lock && uv sync` (python 3.12): Resolved 37 packages, factored
  workspace; regenerated after setuptools switch for editable flat layout.
- `pytest tests/contracts/test_package_contracts.py -q`: initially 9 failed
  (no implementation, as required) → final **27 passed**.
- `ruff check packages apps tests/contracts scripts/verify_architecture.py`:
  **All checks passed** (E501/I001/F401/UP038/UP040 fixed).
- `ruff format --check` on owned files: clean.
- `mypy packages/proofops apps/api/src apps/worker/src apps/agent/src`:
  **no issues in 22 files**.
- `python scripts/verify_architecture.py`: **all checks passed**
  (recursive purity, DTO boundary, ports, 4 fail-closed rejections,
  read-only fixture validation).
- `python scripts/validate_package.py`: **Status passed, 691/691**
  (contracts untouched).
- `pnpm install && pnpm typecheck && pnpm build`: tsc clean, vite build ok
  (28 modules, dist emitted).
- Worker/agent local smoke: `profile=local-synthetic` / boundary ready.
- Negative smokes: `APP_ENV=production` worker + `create_app` raise
  `AdapterRejectedError` (exit via exception, as designed).

## Limitations / not_run

- BedrockTagger is a refusing stub (real binding is TASK-029 preflight).
- Worker lease/fencing/checkpoint (TASK-028), all business routers/parsers/
  rules/review/report (later tasks) — intentionally absent, no pretend pipeline.
- AWS/staging deployment, live model calls, load/E2E/security suites: not_run.
- `pnpm test` does not exist; web has `typecheck` + `build` only (real
  component tests arrive with UI behaviors).
- GAP-001..GAP-010 unresolved (no domain approvals supplied); tenant-scoped
  auth (403/404 semantics) belongs to TASK-037, not this baseline.
- `evidence/package_validation.json/.txt` were rewritten by the validator
  script itself (its designed side effect: 690→691 checks); content review
  left to the coordinator.

## Coordinator acceptance

Accepted after a fresh run of the application checks. A subprocess regression
first failed because importing a domain value eagerly imported composition and
adapters through the package initializer. Removed those unused re-exports;
`uv run --no-sync pytest -q` now passes **29 tests** (28 contract + 1 validator).
One upstream Starlette/AnyIO deprecation warning remains; it does not fail tests.

`ruff check packages apps scripts tests`, mypy on all four Python packages,
`verify_architecture.py`, web typecheck/build and package validation passed.
`uv build --all-packages --out-dir .local/build/task000` built four wheels and
four source distributions. A fresh interpreter imported all four entry packages
from those wheels. The source-distribution missing-README warning is deferred.
Editable `proofops.__file__` resolves to the workspace source. No product model,
cloud, representative PDF, real browser E2E or deployment verification was run.

Implementation references checked during review:
[Pydantic strict input modes](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/),
[Hatch editable path configuration](https://hatch.pypa.io/1.13/config/build/#dev-mode).
The initial accepted flat package used setuptools. A subsequent packaging regression
showed its explicit list silently omitted newly added subpackages. The failing wheel
probe now passes with Hatch's ordinary file selection/path mapping and explicit
editable parent path. No force-included copies or custom build hooks are needed.
This reuses the other three packages' existing build backend.

After that fix: **30 bootstrap/validator tests pass**, scoped Ruff passes,
`uv sync --locked` succeeds without lock changes, editable source resolution passes,
and both the source distribution and wheel build successfully. Python 3.12 is pinned
in `.python-version`; README contains the implemented local commands.
