# TASK-037 · coordinator acceptance repair evidence

Owned files only:

- `packages/proofops/application/authorization.py`
- `packages/proofops/adapters/local/auth_store.py`
- `apps/api/src/proofops_api/auth.py`
- `tests/acceptance/test_auth.py`
- `evidence/task-037.md`

No public DTO, contract, manifest, lockfile, composition, Git commit, or push
was changed. The adapter remains explicitly local in-memory; non-local
composition continues to fail closed.

## Root causes and repaired behavior

1. `GET /v1/session` reused tenant-scoped `authorize`, so a live session with
   no selected tenant incorrectly returned 403 and could not obtain the CSRF
   token needed for its first selection. The read route now authenticates the
   session independently and returns 200 with `tenant_id=null`, `role=null`,
   user, expiry, and a usable CSRF token; tenant-scoped `authorize` still raises
   `CapabilityDeniedError` (403 mapping) for that same session.
2. Rotation checked session liveness before entering the store lock, while
   `set_active_tenant` rotated any record it found. The `SessionPort` rotation
   call now carries explicit `now`; the local store checks existence,
   revocation, absolute expiry, and idle expiry under its lock before rotating.
   A two-thread race on one old SID yields exactly one new session and one
   `SessionExpiredError`, and the old SID remains revoked.
3. The local store keyed records by raw SID, retained the raw SID in stored
   `SessionRecord`, and kept raw CSRF tokens in a side table. It now keys by
   SHA-256 SID hash and stores a private record with no SID; `get(cookie_sid)`
   projects the boundary record. CSRF tokens are deterministically derived
   using a per-store random HMAC key, while only their hashes are retained.
   Seed hash/token mismatch is rejected, issuance is checked against the stored
   hash, and request comparison uses `secrets.compare_digest`.
4. Tenant POST checked CSRF before absolute/idle expiry, so an expired request
   without valid CSRF returned 403. It now authenticates liveness first and
   returns 401 `SESSION_EXPIRED`; valid live requests still require both CSRF
   and Origin.
5. Session deadlines and explicit `now` accepted NaN/Infinity, making expiry
   comparisons fail open, and runtime-invalid roles could reach a dictionary
   `KeyError`. Immutable records now reject non-finite timestamps, non-boolean
   revocation flags, unknown roles, and unknown membership statuses.

## Failing-first evidence

- Corrected the old incorrect GET test first:
  `uv run --no-sync pytest
  tests/acceptance/test_auth.py::test_get_session_without_active_tenant_is_200_with_csrf_for_first_selection
  -q` → failed with **expected 200, got 403**.
- Added the store-lock race before changing the port:
  `...::test_session_rotation_checks_liveness_atomically_under_store_lock -q`
  → failed with **0 successes instead of 1** because both calls rejected the
  missing `now` parameter (the old port could not perform the required atomic
  expiry check).
- Added hash-only storage and seed-integrity cases before changing the adapter:
  both focused tests failed; the raw SID was the `_sessions` key and mismatched
  CSRF seed data did not raise.
- Added the real HTTP first-selection chain and expired POST case before the
  POST ordering fix. The chain exercised GET CSRF → first POST → new cookie
  and CSRF → second POST; the expired POST failed with **expected 401, got
  403**.
- Added malformed/non-finite record tests before validation: four focused cases
  failed because NaN, Infinity, non-finite `now`, and an unknown role were all
  accepted.

All tests use the real local store, application functions, and FastAPI
`TestClient`; no authorization or session mock returns expected values.

## Final verification (2026-09-09 KST, repository root)

- `uv run --no-sync pytest tests/acceptance/test_auth.py -q`
  → **27 passed**, two upstream FastAPI/Starlette deprecation warnings.
- `uv run --no-sync pytest tests/acceptance/test_auth.py
  tests/contracts/test_package_contracts.py -q --tb=short`
  → **56 passed in 0.63s**, the same two upstream warnings.
- `uv run --no-sync mypy packages/proofops/application/authorization.py
  packages/proofops/adapters/local/auth_store.py
  apps/api/src/proofops_api/auth.py tests/acceptance/test_auth.py`
  → **Success: no issues found in 4 source files**.
- `uv run --no-sync ruff check packages/proofops/application/authorization.py
  packages/proofops/adapters/local/auth_store.py
  apps/api/src/proofops_api/auth.py tests/acceptance/test_auth.py`
  → **All checks passed**.
- `uv run --no-sync ruff format --check` over the same four files
  → **4 files already formatted**.
- `uv run --no-sync python scripts/verify_architecture.py`
  → **all checks passed**, including local synthetic construction and
  staging/production fail-closed checks.
- `uv run --no-sync python scripts/validate_package.py`
  → **695/695 documentation/contract checks passed**; this is not an
  application/model/cloud benchmark.
- `uv build --package proofops --out-dir /tmp/proofops-task037-repair-build`
  and the corresponding `--package proofops-api` command
  → both source distributions and wheels built successfully.

## Explicitly not_run / blocked

- Real Cognito OIDC/PKCE, MFA policy, DynamoDB/KMS session persistence, AWS,
  and model calls were not run; required account bindings and approvals remain
  external gates.
- This local HMAC derivation is process-local by design. A durable deployment
  must use its approved session-secret/KMS boundary and distributed atomic
  store; none was fabricated here.
- Web E2E and private customer processing were not run. The focused real HTTP
  TestClient chain covers this repair's API behavior without widening into
  unrelated work-in-progress suites.
