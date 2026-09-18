# TASK-045 verification evidence

## Scope

Implemented the tenant-scoped company and approved execution-option registry.
The local durable store is explicitly SQLite-only (`Registry.sqlite(...)`); it
does not claim a DynamoDB or production adapter. Approved profiles require a
tenant-bound immutable JSON artifact, canonical SHA-256, version, and recorded
approval metadata. Local synthetic fixtures are explicitly marked.

## TDD evidence

1. `uv run pytest tests/acceptance/test_registry.py -q`
   - Before implementation: exit 1; six failures all reported
     `ModuleNotFoundError: No module named 'proofops.application.registry'`.
2. `uv run pytest tests/acceptance/test_registry.py::test_profile_resolver_returns_only_a_tenant_approved_immutable_artifact -q`
   - Before resolver implementation: exit 1; `ImportError` for
     `resolve_profile`.
3. `uv run pytest tests/acceptance/test_registry.py::test_company_create_requires_aliases_per_openapi_contract -q`
   - Before the approved DTO correction: exit 1; expected `DtoValidationError`
     was not raised.
4. `uv run pytest tests/acceptance/test_registry.py -q`
   - Before durable/verified-profile implementation: exit 1; eight failures
     showed the missing artifact hash helper, default-approved profile, and
     absent SQLite constructor.

## Final verification

| Command | Result |
|---|---|
| `uv run ruff check packages/proofops/application/registry.py apps/api/src/proofops_api/routers/registry.py apps/api/src/proofops_api/dto.py tests/acceptance/test_registry.py` | exit 0, all checks passed |
| `uv run mypy packages/proofops/application/registry.py apps/api/src/proofops_api/routers/registry.py apps/api/src/proofops_api/dto.py` | exit 0, success/no issues in 3 source files |
| `pnpm --dir apps/web run typecheck` | exit 0 |
| `uv run pytest tests/acceptance/test_registry.py tests/acceptance/test_auth.py tests/contracts/test_package_contracts.py -q` | exit 0, 66 passed; two upstream Starlette/httpx deprecation warnings |
| `pnpm --dir apps/web run build` | exit 0, Vite build completed |
| `uv run pip-audit` | exit 0, no known vulnerabilities; workspace packages skipped because they are not published to PyPI |
| `git diff --check` | exit 0 |

## Integration and rollback notes

The coordinator must wire `Registry.sqlite(LOCAL_DATABASE_PATH)` into the
local composition and mount `build_registry_router(registry, auth_store,
allowed_origin=APP_ORIGIN)`. The SQLite adapter creates only
`registry_metadata` and `registry_state` with `CREATE TABLE IF NOT EXISTS` and
writes each state change in a SQLite transaction; rollback is SQLite's normal
transaction rollback on write failure. It does not use `PRAGMA user_version`
or alter other task stores.

`python scripts/validate_package.py` was attempted but `python` is unavailable
in this shell (`zsh: command not found: python`). The `uv run python` variant
was not run because that script overwrites the coordinator-owned, already
modified `evidence/package_validation.json` and `.txt`; it is documentation
validation only, not an application test.

Live Bedrock/model calls, AWS mutation, customer data, legal/right approvals,
and deployed E2E are not_run.

## Critical persistence repair (coordinator review)

The original SQLite state-row implementation loaded once at open and wrote its
whole cached state, so interleaved instances could overwrite one another. The
repair reloads state inside `BEGIN IMMEDIATE` for every write, persists and
commits the complete state atomically, reloads after rollback, refreshes every
read, and adds `close()` for connection release. The deliberate ceiling is a
single local state row/global SQLite writer; per-record transactions are the
upgrade path if local contention is measured.

Red tests:

- `uv run pytest tests/acceptance/test_registry.py::test_sqlite_instances_preserve_interleaved_tenants_profiles_and_idempotency tests/acceptance/test_registry.py::test_failed_sqlite_persistence_rolls_back_database_and_memory -q`
  exited 1 with a duplicate idempotency company from stale state and a failed
  persistence write still visible in the original instance's memory.

Green verification:

| Command | Result |
|---|---|
| same two-test command above | exit 0, 2 passed |
| `uv run ruff check packages/proofops/application/registry.py tests/acceptance/test_registry.py` | exit 0 |
| `uv run mypy packages/proofops/application/registry.py` | exit 0, success/no issues in 1 source file |
| `uv run pytest tests/acceptance/test_registry.py -q` | exit 0, 12 passed; two upstream Starlette/httpx deprecation warnings |
| `git diff --check` | exit 0 |
