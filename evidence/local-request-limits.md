# Local API request controls

Date: 2026-09-09
Scope: synthetic local API identities only; no live OIDC, AWS, model, or customer data.

## Stable interface

`proofops_api.request_limits.LocalRequestLimiter.consume(limits, now=...)` atomically
consumes one or more `RequestLimit(namespace, server_identity, operation_id, requests)`
buckets and returns either `None` or an integer `Retry-After`. `AuthStore.request_limits`
owns the shared process instance used by the accepted local routers.

The implementation is a locked 60-second sliding window. It retains at most 4,096
buckets and at most 120 timestamps per bucket; expired buckets are reclaimed, and new
identities fail closed with 429 when active capacity is full. This ceiling is explicitly
process-local and is not suitable for multiple API replicas; the existing non-local
composition remains fail-closed and still requires durable atomic request control.

## Enforced operations

- `session_read`: 120/min/authenticated user.
- `tenant_switch`: 10/min/authenticated user, after live-session and CSRF/Origin checks.
- `companies_list` and `runtime_options`: 120/min/authenticated user per operation.
- `company_create` and `preflight`: 10/min/authenticated user per operation.
- `preflight_live_probe`: the existing 2/min/tenant safety ceiling, atomically combined
  with (not substituted for or double-counted as) the per-user preflight limit.

Every limiter identity comes from the live server session/auth context. `X-User-Id`,
`X-Forwarded-For`, and similar client headers are not read. Authentication, strong
membership/capability denial, and CSRF/Origin denial occur before budget consumption.

Company JSON receive is capped at 65,536 bytes using both declared length and actual
streamed bytes. Oversize input returns the normal JSON error envelope with HTTP 413 and
`PAYLOAD_TOO_LARGE`; malformed bounded JSON returns HTTP 422 `VALIDATION_ERROR`. The
multipart upload transport was not changed.

## Verification

Commands were run with the existing lock/environment (`--no-sync`) while other workers
were active:

```text
uv run --no-sync pytest tests/integration/test_request_limits.py \
  tests/acceptance/test_auth.py tests/acceptance/test_session_security.py \
  tests/acceptance/test_registry.py tests/acceptance/test_preflight.py -q
124 passed, 2 upstream deprecation warnings

uv run --no-sync pytest tests/contracts -q
29 passed, 2 upstream deprecation warnings

uv run --no-sync pytest tests/unit -q
16 passed

uv run --no-sync pytest tests/integration/test_local_api_composition.py \
  tests/integration/test_request_limits.py -q
8 passed, 2 upstream deprecation warnings

uv run --no-sync ruff check <owned source and request-limit test files>
All checks passed

uv run --no-sync ruff format --check <owned source and request-limit test files>
6 files already formatted

uv run --no-sync mypy <five owned API source files>
Success: no issues found in 5 source files

uv build apps/api --out-dir <temporary directory> --no-create-gitignore
Successfully built proofops_api-0.0.0.tar.gz and proofops_api-0.0.0-py3-none-any.whl
```

The HTTP tests use independent concurrent clients and synthetic sessions to cover atomic
10-request writes, 429 without an eleventh mutation, exact window expiry/Retry-After,
per-operation and per-user isolation, session rotation without budget reset, unauthenticated
and CSRF/role precedence, untrusted identity headers, bounded Content-Length and streamed
bodies, 120-request session reads, and the separate tenant live-probe ceiling. A mutation
check disabling the combined live-probe bucket made its focused regression fail (404 instead
of required 429), after which the implementation was restored and reverified.

Live OIDC/Cognito, distributed/multi-replica limiting, AWS-backed control, customer-data
tests, and unrelated in-progress E2E suites were not run. Route security was exercised by
the targeted auth/session/CSRF and HTTP integration suites. Remaining routers can adopt the
same stable helper in their owning tasks; no distributed dependency or framework was added.

## Remaining-route integration addendum

The shared limiter is now applied after strong authorization to every implemented fixed-contract
operation owned by this integration:

- 10/min/user writes: `document_create`, `version_create`, `upload_complete`, `run_create`,
  `run_cancel`, `run_retry`, `logout`, and `rulepack_activate`.
- 120/min/user reads: `document_get`, `version_get`, `run_get`, `cost_get`, `audit_get`,
  `source_get`, and `quality_get`.

The local-only multipart receiver is not a fixed-contract operation, so it keeps its existing
authentication, CSRF/Origin, ticket, and byte ceilings without consuming a second business-operation
bucket. Existing company/runtime/session/tenant/preflight buckets were not added again. All identities
come from the verified server session (`user_sub`), not cookies as raw identity values, client IPs, or
forwarded identity headers.

Write role and CSRF/Origin denials occur before request consumption. Actual HTTP tests cover an invalid
CSRF request followed by an allowed operation, per-operation read/write isolation, a concurrent 11-way
logout with exactly ten revocations and one live rate-limited session, and source/quality responses.
The shared browser middleware now sets `Cache-Control: no-store` on JSON responses, including source
and quality data and JSON denials.

`read_bounded_json` checks `len(data) + len(chunk)` before copying the next chunk. Documents, runs, and
rule-pack activation reuse that bounded reader; their existing fixed-contract validation envelopes are
preserved. The sliding window still retains at most 4,096 buckets and 120 timestamps per bucket, and
both capacity and ordinary limit paths cap clock-rewind `Retry-After` at 60 seconds. This remains a
per-process ceiling only; non-local composition remains fail-closed until durable atomic request control
is supplied, and no distributed framework or dependency was added.

TDD evidence:

```text
uv run --no-sync pytest tests/integration/test_request_limits.py -q
RED: 6 failed, 7 passed, 2 warnings (remaining routes/no-store/pre-copy checks absent)

uv run --no-sync pytest tests/integration/test_request_limits.py \
  tests/acceptance/test_upload.py tests/integration/test_run_lifecycle.py \
  tests/integration/test_source_api.py tests/acceptance/test_session_security.py \
  tests/acceptance/test_rulepack_api.py tests/integration/test_local_api_composition.py -q
RED: 1 failed, 99 passed, 2 warnings (`Retry-After` was 10160 after clock rewind)

uv run --no-sync pytest tests/integration/test_request_limits.py -q
14 passed, 2 upstream deprecation warnings

uv run --no-sync pytest tests/acceptance/test_upload.py \
  tests/integration/test_run_lifecycle.py tests/integration/test_source_api.py \
  tests/acceptance/test_session_security.py tests/acceptance/test_rulepack_api.py \
  tests/integration/test_local_api_composition.py -q
86 passed, 2 upstream deprecation warnings

uv run --no-sync pytest tests/contracts/test_package_contracts.py::test_run_create_real_http_post \
  tests/contracts/test_package_contracts.py::test_api_health_contract -q
2 passed, 2 upstream deprecation warnings

uv run --no-sync ruff check <eight owned source/test files>
All checks passed

uv run --no-sync ruff format --check <eight owned source/test files>
8 files already formatted

uv run --no-sync mypy <seven owned API source files>
Success: no issues found in 7 source files

uv build apps/api --out-dir <temporary directory> --no-create-gitignore
Successfully built proofops_api-0.0.0.tar.gz and proofops_api-0.0.0-py3-none-any.whl
```

No live model, AWS, customer-data, distributed-replica, or unrelated WIP E2E test was run.

## Coordinator integration verification

Review found preflight and tenant selection still parsed unbounded JSON. The shared bounded
reader now also handles those routes, after authentication/CSRF checks; tenant selection
retains its request schema and returns the fixed error envelope for malformed JSON. The
parameterized declared/streamed oversize regression first failed on both omitted routes,
then passed with 413 and without mutation.

`uv run --no-sync pytest tests/integration/test_request_limits.py
tests/integration/test_claim_api.py tests/integration/test_source_api.py
tests/integration/test_local_api_composition.py tests/acceptance/test_session_security.py
tests/acceptance/test_preflight.py tests/acceptance/test_registry.py
tests/acceptance/test_auth.py -q`: 136 passed, two existing upstream deprecation warnings.
Ruff passed for the API and four integration files; mypy passed for all 17 API source files.
