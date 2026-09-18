# TASK-044 — AWS staging 실증·배포·복구 게이트

Execution date: 2026-09-09 KST (runner UTC 2026-09-08).
Full task outcome: **blocked / not completed**. Offline preparation: implemented and verified.
No commit, push, AWS mutation, product model call, customer processing or human approval occurred.

## Scope and implementation

Read AGENTS.md, Master, source v2, priority docs 26/27/28/31/19, TASK-044 in docs/20,
infra/deployment DoD, NFR-002/SEC-006, runtime preflight/schema, existing IAM/compute,
and local review/export/retention tests. Coordinator confirmed the bounded offline
scope and retained actual staging acceptance blocked.

Files owned by this task:

- `infra/cdk/staging_gate.py`: stdlib-only, read-only evidence verifier; no deployment executor.
- `tests/e2e/test_staging_gate.py`: real subprocess/filesystem/hash acceptance tests, synthetic input envelopes.
- `docs/DEPLOYMENT_EVIDENCE.md`: internal bundle format, trust boundary, current gates and actual recovery sequence.
- `evidence/task-044.md`: this execution record.

No dependency, shared contract, API, DB, migration, domain rule or existing revision changed.
Other workers' modifications under tests/e2e and elsewhere were preserved.

The verifier checks immutable image references and scoped current/previous release identities,
detached approval snapshot hash, required report and log hashes, explicit non-synthetic staging
provenance, timestamps, exact booleans, rollback target equality, actual restored/original file
byte equality and finite measured SLO/recovery targets. Missing reports stay not_run;
blocked/failed reports cannot become complete. JSON reads are capped at 1MiB and artifact
reads at 100MiB using limit+1 reads, including files that grow after metadata inspection.
The CLI writes only stdout and never runs report commands.

**Trust limitation:** supplied approval/log provenance must be authenticated outside this
CLI by protected CI/review. Checksums are not signatures or proof that AWS operations
happened. `evidence_complete=true` means supplied bundle consistency only; it is neither
AWS authorization nor a claim of deployment completion. Report assertions about tenant,
source, replica, schema and model operations still require the actual external run/log review.
RuntimeBinding/model ARN availability and image registry contents are not remotely verified here.

## Red → green evidence

| Exact command | Actual result |
|---|---|
| `uv run pytest tests/e2e/test_staging_gate.py -q` (before implementation) | exit 1; **26 failed** at `missing offline staging evidence gate` |
| Same command, first implementation | exit 1; 1 failed / 25 passed; valid fixture timestamp was 2026-09-09 UTC, ahead of runner UTC 2026-09-08 |
| Same command after fixture date correction to 2026-09-08 | exit 0; **26 passed**; future timestamp rejection retained |
| `uv run pytest tests/e2e/test_staging_gate.py::test_restore_requires_original_and_restored_bytes_not_just_boolean_claims -q` | RED exit 1: mismatched restored bytes incorrectly returned 0; after actual byte verification, suite **27 passed** |
| `uv run pytest tests/e2e/test_staging_gate.py::test_unbounded_numeric_input_fails_closed_with_json_result -q` | RED exit 1: 10**400 measurement caused overflow/no JSON; after range check before float conversion, suite **28 passed** |
| `uv run pytest tests/e2e/test_staging_gate.py::test_oversized_evidence_is_rejected_before_reading_entire_file -q` | RED exit 1: >1MiB report incorrectly returned 0; after bounded reads, suite **29 passed** |

The complete fixture is explicitly synthetic test data, including its claimed staging
report envelope. No fixture, invented account/image/model identity or synthetic approval
was copied into a real deployment evidence bundle. Existing application regressions use
explicit local synthetic adapters and real local behavior, not AWS substitutes.

## Verification commands and outcomes

| Exact command | Exit / observed output |
|---|---|
| `uv run ruff check infra/cdk/staging_gate.py tests/e2e/test_staging_gate.py` | 0; `All checks passed!` |
| `uv run ruff format --check infra/cdk/staging_gate.py tests/e2e/test_staging_gate.py` | 0; `2 files already formatted` |
| `uv run mypy infra/cdk/staging_gate.py` | 0; `Success: no issues found in 1 source file` |
| `uv run pytest tests/e2e/test_staging_gate.py -q` (final after review fix) | 0; **29 passed in 1.17s** |
| `pnpm --dir infra/cdk exec tsc --noEmit` | 254; `Command "tsc" not found` in the infra workspace |
| `pnpm --dir apps/web exec tsc --project ../../infra/cdk/tsconfig.json --noEmit` | 0; existing web-installed TypeScript successfully checked infra; no install or lock change |
| `pnpm --dir apps/web build` | 0; tsc and Vite build passed; 50 modules transformed, built in 457ms |
| `git diff --check -- infra/cdk tests/e2e/test_staging_gate.py docs/DEPLOYMENT_EVIDENCE.md evidence/task-044.md` | 0; no whitespace errors |

Initial ruff run found 11 line-length violations before formatting. Initial mypy runs
found nullable dict/measurement narrowing errors (2, then 3 diagnostics); explicit runtime
type checks fixed them, and the final commands above pass without weakening validation.

Local acceptance/integration command:

```sh
uv run pytest tests/e2e/test_staging_gate.py tests/acceptance/test_preflight.py tests/acceptance/test_supply_chain.py tests/acceptance/test_reviews.py tests/acceptance/test_exports.py tests/acceptance/test_retention.py tests/integration/test_retention_api.py tests/integration/test_deleted_document_access.py tests/integration/test_local_api_composition.py -q
```

Exit 0: **195 passed, 2 warnings in 16.50s**, before the final two added gate regressions.
Verified real local preflight denial, supply-chain guards, tenant access, review CAS,
immutable export behavior, SQLite deletion/tombstone restoration and composed API behavior.
The two warnings are existing Starlette/httpx and anyio BlockingPortal deprecations.

Contract/unit/security command:

```sh
uv run pytest tests/contracts/test_package_contracts.py tests/unit/test_package_validation.py tests/security/test_prompt_injection.py tests/e2e/test_staging_gate.py -q
```

Exit 0: **67 passed, 2 warnings in 2.90s**, before the final two added gate regressions.
Includes fixed-schema/domain boundaries, wheel packaging, contract-validator units and
prompt-injection regression. The package-validator tests are not counted as AWS or app E2E.
After the bounded-read review correction, final gate/lint/format/mypy were rerun successfully.

## Required task commands (actually attempted)

| Command | Actual outcome | Interpretation |
|---|---|---|
| `pnpm --dir infra/cdk exec cdk synth` | exit 254; `ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command "cdk" not found` | IaC synth blocked; no CDK CLI dependency or deployment entrypoint exists |
| `pnpm --dir apps/web exec playwright test` | exit 254; `ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command "playwright" not found` | requested browser runner unavailable; browser E2E not_run by this worker |
| `uv run python scripts/preflight.py` | exit 1; `ready=false`, configuration fail, supply_chain fail, live_model_probe not_run, binding_sha256 null | existing gate correctly blocks absent approval/build artifacts |
| `uv run python infra/cdk/staging_gate.py` | exit 1; `evidence_complete=false`, `aws_actions_performed=false`, release_or_approval fail, ten required reports not_run | new default gate blocks absent external evidence |

Existing preflight stdout:

```json
{"ready":false,"checks":[{"name":"configuration","status":"fail","reason":"missing, invalid or inaccessible approval artifacts"},{"name":"live_model_probe","status":"not_run","reason":"offline CLI never calls a model"},{"name":"supply_chain","status":"fail","reason":"build/license checks blocked; inspect deployment evidence"}],"binding_sha256":null,"checked_at":"2026-09-08T21:26:35.370496+00:00"}
```

## Review and remaining gates

Coordinator critical/important review accepted the bounded offline scope, with one
important correction: replace unbounded `Path.read_bytes()` with a single bounded-read
helper and an oversized-input regression. The requested RED → GREEN fix is implemented;
29 final gate tests, lint/format and mypy pass. No broad refactor was added.

Coordinator separately reported an actual local same-origin browser export→deletion flow
on the shared SQLite harness (Orca, no HTTP mocks), with ZIP SHA validation and denial of
old document/run/export/download accesses after tombstone. That is **coordinator-reported
local evidence**, not a browser run by this worker and not AWS staging evidence; see
`evidence/task-040.md` for the coordinator's own record.

| Unexecuted gate | Status / reason |
|---|---|
| Actual AWS infrastructure synthesis/deployment and runtime wiring | blocked; CDK runner/entrypoint absent; cloud mutation outside authorization |
| Account/region/model/consent, legal/data rights and license approval | blocked; human-only approved artifacts absent; none fabricated |
| Approved public PDF → actual parser/model replicas → report in staging | not_run; approved external inputs/model execution unavailable |
| Actual staging tenant isolation, review contention, export integrity | not_run; no deployed staging artifact |
| Previous-image/runtime/rule/index rollback and schema compatibility | not_run; no AWS rollback exercise performed |
| S3 versions/DDB PITR restore, tombstone replay, lease reset, recovery cutover | not_run on AWS; local SQLite restoration regressions passed separately |
| Staging p95 query/acceptance and RPO/RTO | not_run; no performance figures claimed |
| Production deployment | not_run; separately approved action, not part of this worker execution |

Full TASK-044 acceptance remains unfulfilled. Do not mark AWS staging, recovery, or
production complete based on the local gate/test results.
