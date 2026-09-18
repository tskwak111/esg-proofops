# TASK-025 HTTP activation integration evidence

Date: 2026-09-09 (Asia/Seoul)  
Dispatch: `task_83ba709dad52` / `ctx_ffd202c50625`

## Implemented scope

- Added the actual local `POST /v1/rule-packs/{rule_pack_id}/activate` FastAPI router.
- Reused accepted `proofops.application.rulepacks.activate_rulepack`; no grade, label,
  clause, legal effect, approver, or repository-draft approval was invented.
- Enforced live session membership, admin capability, configured-origin CSRF, tenant-scoped
  lookup, strict `ActionReason`, 16..128-character `Idempotency-Key`, and quoted positive
  `If-Match` revision.
- Returned only the contracted v1 `RulePack` fields and an `ETag` carrying the resulting
  revision. Cross-tenant and missing packs share the same 404 error family.
- Added stdlib SQLite durability for immutable RulePack revisions, CAS heads, active
  tenant/mode pointers, frozen run snapshots, 24-hour idempotency replay, and activation
  audit records. Activation changes only the pointer/current status revisions; existing
  run snapshots remain unchanged.
- Added `list_active_packs(tenant_id) -> tuple[RulePackRecord, ...]` so RuntimeOptions can
  read the durable active pointer rather than a second stale registry.
- No dependency, cloud resource, contract file, product model, commit, or push was added.

## Fail-first evidence

1. `uv run pytest tests/acceptance/test_rulepack_api.py::test_approved_activation_changes_new_run_pointer_not_inflight_snapshot -q`
   failed because `proofops.adapters.local.rulepack_store` did not exist.
2. The same test then failed 401/403 until the real session cookie and issued CSRF token
   were used; after the minimal router/store implementation it passed.
3. `uv run pytest tests/acceptance/test_rulepack_api.py::test_missing_or_short_idempotency_key_uses_contract_error_shape -q`
   failed twice because FastAPI returned its default `detail` body instead of the contracted
   `Error` body; manual header validation made both cases pass.
4. `uv run pytest tests/acceptance/test_rulepack_api.py::test_invalid_action_reason_uses_contract_error_shape -q`
   failed twice for the same default-body mismatch; explicit Pydantic validation made the
   short-reason and approval-injection cases pass.
5. `uv run pytest tests/acceptance/test_rulepack_api.py::test_generated_openapi_matches_activation_contract -q`
   failed because session-cookie security and contracted error responses were absent; the
   route now publishes those exact operation/header/response contracts.
6. `uv run pytest tests/acceptance/test_rulepack_api.py::test_active_pack_reader_uses_durable_pointer_after_reopen -q`
   failed with missing `list_active_packs`; the tenant-scoped durable reader was then added
   and passed.

## Local schema, migration, and rollback

Forward initialization is idempotent `CREATE TABLE IF NOT EXISTS` for component-owned
`rulepack_*` tables plus `rulepack_schema_metadata(component='rulepacks', version=1)`.
It deliberately does not claim global `PRAGMA user_version`, and a test proves an unrelated
table and pre-existing global version survive initialization. Unknown component schema
versions fail closed.

Rollback was defined but not executed: stop the affected writer/router and retain
the shared database, immutable revisions, run snapshots and activation audit. Back
up `.local/state.sqlite3` before changing application versions. Do not drop tables
or replace the database with an older backup that loses later immutable records.
Production migration and rollback remain the DynamoDB adapter task.

## Verification run

- PASS — `uv run pytest tests/acceptance/test_rulepack_api.py -q`: 22 passed; two upstream
  TestClient deprecation warnings.
- PASS — `uv run pytest tests/acceptance/test_rulepack_api.py tests/acceptance/test_rulepacks.py tests/acceptance/test_auth.py tests/acceptance/test_session_security.py tests/acceptance/test_registry.py tests/contracts/test_package_contracts.py -q`:
  141 passed; two upstream TestClient deprecation warnings.
- PASS — focused `ruff check`, `ruff format --check`, and `mypy` on the two implementation
  files and HTTP test: clean / formatted / no type errors.
- PASS — `uv run python scripts/verify_architecture.py`: all checks passed.
- PASS — `uv run python scripts/validate_package.py`: 696/696 package checks passed.
  The documented bare `python scripts/validate_package.py` command was also attempted but
  returned 127 because this environment exposes Python through `uv run python`.
- PASS — `uv run pip-audit`: no known third-party vulnerabilities; four local workspace
  packages were skipped because they are not PyPI distributions.
- PASS — `pnpm --dir apps/web typecheck` and `pnpm --dir apps/web build`; Vite built 28
  modules.
- NOT CLEAN (outside owned files, concurrent work) — full `uv run ruff check .` stopped on
  17 formatting/line-length findings in active TASK-030/audit/upload files.
- NOT CLEAN (outside owned files, concurrent work) — full `uv run mypy packages apps/api
  apps/worker apps/agent` found one type error in `packages/proofops/application/budget.py:134`.
- NOT CLEAN (outside owned files, concurrent work) — full `uv run pytest tests/unit
  tests/contracts tests/acceptance tests/integration -q` stopped during collection because
  active `test_audit.py` and `test_jobs.py` referenced the not-yet-present
  `proofops.adapters.local.audit_store`.
- NOT RUN — direct `verify_rulepack.py` success invocation: the CLI requires a separate
  pack-descriptor JSON and the repository intentionally contains only the unapproved YAML
  draft. Its real synthetic descriptor path is covered by passing
  `test_repository_draft_config_validates_without_approval` in `test_rulepacks.py`.
- NOT RUN — web lint/unit/E2E: `apps/web/package.json` defines no lint, test, or Playwright
  scripts.
- NOT RUN — DynamoDB/AWS, Cognito, real model, cloud deployment, and product-data tests;
  no account-backed action was authorized or attempted.
