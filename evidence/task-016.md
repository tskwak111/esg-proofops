# TASK-016 Evidence — 세이프하버 기록 경로

Date: 2026-09-09  
Fixture: AT-016  
Requirement: FR-016  
Operation contract: `GET /v1/runs/{run_id}/safe-harbor` (validated through the
allowed pure-function path; no API file was assigned to this task)

## Implemented

- Added immutable `SafeHarborRecord` and checklist items projected to the fixed
  `SafeHarborRecord` JSON Schema.
- `record_safe_harbor` reuses the existing `ConfirmedTags`, `RuleContext`,
  `RulePackSnapshot`, and shared source/tenant/document validation boundary.
- Category checklists come from the pinned `regulatory/safe_harbor.yaml` snapshot.
  Missing checklist facts stay `unknown`; `unknown` and `conflict` are preserved.
- The current null grade/boolean mappings produce `mapping_status=unresolved`,
  `reasonable_basis_documented=null`, `legal_effect=not_determined`, and `GAP-001`.
  The record has no grade/label fields, so missing numeric evidence cannot become E0.
- Synthetic fixtures are marked local-only and make no legal, AWS, or model claims.

Files created:

- `packages/proofops/domain/rules/safe_harbor.py`
- `tests/acceptance/test_safe_harbor.py`
- `evidence/task-016.md`

No dependency, lockfile, API, database, migration, or shared contract was changed.

## TDD evidence

### RED

Command:

```sh
uv run pytest tests/acceptance/test_safe_harbor.py -q
```

Result: exit 2; collection failed with
`ModuleNotFoundError: No module named 'proofops.domain.rules.safe_harbor'`.

### GREEN

Command:

```sh
uv run pytest tests/acceptance/test_safe_harbor.py -q
```

Result: exit 0; `9 passed in 0.25s` after the initial implementation.

### Unknown-to-absent mutation check

The missing-fact fallback was temporarily changed from `unknown` to `absent` and
the focused check was run:

```sh
uv run pytest tests/acceptance/test_safe_harbor.py::test_unreported_checklist_item_defaults_to_unknown_not_absent -q
```

Result: exit 1; the assertion showed
`scenario_or_premises: absent != unknown`. The correct implementation was restored.

Final focused command:

```sh
uv run pytest tests/acceptance/test_safe_harbor.py -q
```

Result: exit 0; `10 passed in 0.25s`.

## Verification

### Lint, format, and type check

```sh
uv run ruff check packages/proofops/domain/rules/safe_harbor.py tests/acceptance/test_safe_harbor.py && uv run ruff format --check packages/proofops/domain/rules/safe_harbor.py tests/acceptance/test_safe_harbor.py && uv run mypy packages/proofops/domain/rules/safe_harbor.py
```

Result: exit 0; `All checks passed!`, `2 files already formatted`, and
`Success: no issues found in 1 source file`.

### Related acceptance / local integration coverage

```sh
uv run pytest tests/acceptance/test_safe_harbor.py tests/acceptance/test_rules.py tests/acceptance/test_exceptions.py tests/acceptance/test_rulepacks.py -q
```

Result: exit 0; `142 passed in 2.41s`.

```sh
uv run pytest tests/acceptance -q
```

Result: exit 1; `303 passed, 6 failed, 2 warnings in 4.73s`. The failures are
outside TASK-016: one existing auth status-order assertion in
`tests/acceptance/test_auth.py` and five concurrent upload-security failures in
`tests/acceptance/test_upload_security.py`. The TASK-016 and connected rule tests
passed in this same run; no out-of-scope files were changed.

```sh
if [ -d tests/integration ]; then uv run pytest tests/integration -q; else echo 'not_run: tests/integration does not exist'; fi
```

Result: exit 0; `not_run: tests/integration does not exist`. The repository CI
currently labels `tests/acceptance` as its local acceptance/integration gate.

### Unit and contract

```sh
uv run pytest tests/unit tests/contracts -q
```

Result: exit 0; `45 passed, 2 warnings in 1.30s`. Both warnings are existing
Starlette/httpx deprecations from `test_run_create_real_http_post`.

### Architecture / purity

```sh
uv run python scripts/verify_architecture.py
```

Result: exit 0; `PASS purity:packages/proofops/domain/rules/safe_harbor.py` and
`verify_architecture: all checks passed`.

### Package build

```sh
TASK016_BUILD_DIR=$(mktemp -d /tmp/proofops-task016-build.XXXXXX) && uv build --package proofops --out-dir "$TASK016_BUILD_DIR"
```

Result: exit 0; sdist and wheel built successfully under
`/tmp/proofops-task016-build.Ec2KQl/`.

### Dependency security

```sh
uv export --locked --no-emit-workspace --format requirements-txt --output-file /tmp/proofops-task016-audit.txt && uv run --no-sync pip-audit --strict --no-deps --disable-pip -r /tmp/proofops-task016-audit.txt
```

Result: exit 0; `No known vulnerabilities found` (with pip-audit's existing
`--no-deps` advisory warning). TASK-016 added no dependency.

### E2E and external/human gates

```sh
if [ -d tests/e2e ]; then uv run pytest tests/e2e -q; else echo 'not_run: tests/e2e does not exist'; fi
```

Result: exit 0; `not_run: tests/e2e does not exist`.

- Real product model calls: `not_run` (prohibited for this dispatch).
- AWS mutation/deployment: `not_run` (prohibited for this dispatch).
- Private customer data processing: `not_run` (prohibited for this dispatch).
- Approved checklist-to-grade/reasonable-basis mapping: `blocked_rule_gap`
  (`GAP-001`); non-null mappings are rejected until their semantics are approved.
- Legal effect/applicability approval: `not_run`; output remains
  `legal_effect=not_determined`.

## Critical/important review

No critical or important issue was found in the assigned diff. The deliberate
ceiling is the approved mapping path: it is not invented, and should be added only
after GAP-001 is resolved with an approved truth table and boundary vectors.
