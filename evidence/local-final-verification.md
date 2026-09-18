# Local implementation verification

Date: 2026-09-09 (Asia/Seoul). These are actual local results, not AWS deployment,
customer-data accuracy, legal approval, or production readiness evidence.

## Backend, contracts and security

```text
uv run --no-sync pytest tests/unit tests/contracts tests/integration tests/acceptance tests/security tests/load -q --tb=short
exit 0: 1326 passed, 2 upstream deprecation warnings in 87.29s

uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load
exit 0: no issues in 135 source files

uv run --no-sync ruff check packages apps scripts tests evaluation
exit 0: All checks passed!

uv run --no-sync ruff format --check .
exit 0: 210 files already formatted

uv run --no-sync python scripts/verify_architecture.py
exit 0: all checks passed, including rejection of synthetic/Bedrock staging and production composition
```

The full test command includes actual parser execution, deterministic rules, HTTP contracts,
tenant/session isolation, revisions, audit, exports, retention fences, and local load/fault
checks. The composed API test now asserts every declared operation is mounted with its
fixed operation ID (45 operations); this does not imply live AWS adapters are implemented.
The two warnings concern upstream Starlette/httpx and anyio deprecations.

The first full lint/format pass found formatting failures in previously delivered tests
and three existing modules. Imports/line breaks were corrected without changing assertions
or runtime behavior. The full backend run passed, and the refreshed lint/format checks pass.

## Dependency verification

```text
uv sync --locked --dry-run
exit 0: 73 packages resolved; existing environment would not change

uv export --locked --no-emit-workspace --format requirements-txt --output-file /tmp/proofops-final-audit.txt
exit 0

uv run --no-sync pip-audit --strict --no-deps --disable-pip -r /tmp/proofops-final-audit.txt
exit 0: No known vulnerabilities found

pnpm audit --json
exit 0: 124 dependencies, zero info/low/moderate/high/critical advisories
```

Audits describe advisories available when these commands ran, not a permanent absence of
vulnerabilities. No new package dependency was added for export, retention or comparison.

## Build and configuration checks

```text
uv build --all-packages --out-dir /tmp/proofops-final-build
exit 0: proofops, proofops-api, proofops-worker and proofops-agent wheels/source distributions built

pnpm --dir apps/web exec tsc --noEmit --project ../../infra/cdk/tsconfig.json
exit 0: existing IAM/quarantine TypeScript checks
```

Running `uv run --no-sync python scripts/verify_rulepack.py` without metadata returned
exit 2 because `--pack` is required. The documented command was corrected to show this
argument. The full backend suite includes actual CLI acceptance/negative cases; no
approved production rule-pack metadata was invented for a green standalone invocation.
The existing draft YAML remains a draft. TypeScript checking is not CDK synthesis.

## Browser verification

Actual same-origin browser testing uses the explicit synthetic fixture harness in
`tests/e2e/local_browser_server.py`. The form-driven export check and subsequent deletion
request check ran against built React assets and a fresh shared SQLite database, without
mocked HTTP responses. Export ZIP bytes matched the authorized SHA; deletion revoked
previously issued tickets and hid document/version/run/export reads. Exact results are in
`evidence/local-export-web.md` and `evidence/task-040.md`.

The earlier routed review/source keyboard, conflict and tenant transition checks are in
`evidence/local-review-web.md`, `evidence/local-run-web.md`, and task accessibility evidence.
Controlled-response React checks are explicitly separate from actual API/browser flows.

The offline staging gate's final coordinator check passed 29 tests in 1.09s:
`uv run --no-sync pytest tests/e2e/test_staging_gate.py -q --tb=short`.
Its lint/type checks passed, and CI now includes these offline tests and the gate's type check.
Running `uv run --no-sync python infra/cdk/staging_gate.py` against the repository's missing
approval/evidence bundle correctly exited 1 with `evidence_complete=false` and
`aws_actions_performed=false`; the ten staging evidence groups remain `not_run`.
Offline preparation is accepted; TASK-044's actual staging acceptance remains blocked.

The final comparison follow-up passed 18 acceptance/API/composition tests in 3.11s,
including the new missing-approval regression added after the 1326-test broad run.
Scoped Ruff and mypy checks passed. These follow-up counts overlap the broad suite;
they are not added to it as distinct tests.

The coordinator rebuilt the final React app (`pnpm --dir apps/web build`, exit 0,
52 modules), reloaded the mounted `/runs/{run_id}/comparison` route and ran
`tests/e2e/comparison_http_check.mjs` through Orca against actual same-origin HTTP.
The harness used `--include-prior-version` and `ENABLE_YEAR_COMPARISON=true`, generated
current/prior PDF versions and a fresh shared SQLite database. The real document and
ready prior version were selectable. POST returned 202 and the stored comparison GET
returned `not_run/prior_comparison_artifact_missing` with no invented changes. The page
displayed the reason. All five returned verification flags were true. Controlled-response
React checks separately cover permissions, environment disabling, idempotent retries,
pagination and late responses; see `evidence/local-comparison-web.md`.

After the final comparison changes, `uv build --all-packages --out-dir
/tmp/proofops-final-comparison-build` again exited 0 and built all four wheels and source
distributions. An earlier attempt to pass `--package` twice was rejected by uv (exit 2);
the supported all-packages command above completed successfully.

Real AWS/model/customer processing, approved domain/retention policies and actual cloud
backup recovery remain not_run. Deployment code/runtime wiring and real staging acceptance
are still incomplete; local passing checks do not establish production readiness.

Final documentation/contract verification: `uv run --no-sync python
scripts/validate_package.py` exited 0 with **705/705 checks passed** (34 numbered documents,
43 requirements, 46 tasks and 45 API operations). This is separate from application testing.
