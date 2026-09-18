# TASK-033 verification evidence

Date: 2026-09-09 (Asia/Seoul)

## Implemented boundary

- `canonical_hash` now hashes every supplied field through
  `domain.rulepacks.canonical_json`; it does not recursively remove `actor`,
  `timestamp`, or any nested source data. `provenance_hash` is a separate,
  explicit envelope containing the semantic hash, audit actor, and occurrence
  time.
- `request_signature` binds temperature, model id/profile, prompt/schema
  hashes, packet hash, tool definitions, maximum tokens, replicate, and
  extraction epoch. The cache namespace separately binds tenant, consent
  profile, document version, and role.
- `ImmutableResponseCache` uses an injected conditional immutable client for
  real put/get behavior. Raw, guarded, and decision objects use separate
  storage keys; raw reads require the same request id recovery and the request
  signature includes the replica.
- `InMemoryImmutableCacheClient` is explicitly `local-contract-test-only` and
  is used only in the acceptance tests; no AWS SDK, network call, model call,
  or customer data was used.

## TDD evidence

1. After replacing the prior projection-only acceptance test,
   `uv run pytest tests/acceptance/test_reproducibility.py -q` exited 2 at
   collection with the expected missing `CacheCollisionError` import from the
   projection-only adapter.
2. After implementing the conditional adapter, the same command exits 0 with
   `6 passed in 0.05s`.

The six tests exercise actual cache payload reads rather than comparing only
keys: tenant and replica isolation, same-request recovery restriction,
conditional overwrite rejection, raw/guarded/decision separation, stored-byte
corruption detection, and documented manifest revocation. They also run the
actual pure rule engine with identical inputs and prove that source, model,
prompt, and a second self-verifying rule snapshot change the engine semantic
hash; audit actor/time affect only the separate provenance hash.

## Verification

| Command | Result |
|---|---|
| `uv run pytest tests/acceptance/test_reproducibility.py -q` | exit 0, `6 passed in 0.05s` |
| `uv run ruff check packages/proofops/domain/provenance.py packages/proofops/adapters/cache/aws.py tests/acceptance/test_reproducibility.py` | exit 0, `All checks passed!` |
| `uv run ruff format --check packages/proofops/domain/provenance.py packages/proofops/adapters/cache/aws.py tests/acceptance/test_reproducibility.py` | exit 0, `3 files already formatted` |
| `uv run mypy packages/proofops/domain/provenance.py packages/proofops/adapters/cache/aws.py tests/acceptance/test_reproducibility.py` | exit 0, `Success: no issues found in 3 source files` |
| `uv run pytest tests/contracts/test_package_contracts.py -q` | exit 0, `29 passed`; two existing FastAPI/Starlette deprecation warnings |

## Not run / remaining limitation

### Coordinator acceptance

Two additional regression checks first failed: a new request id could recover a
prior raw response, and delimiter-bearing consent/role fields could alias another
document namespace. Storage now hashes the canonical namespace tuple and explicitly
binds raw request id, replica and extraction epoch. After correction:
`uv run --no-sync pytest tests/acceptance/test_reproducibility.py tests/contracts/test_package_contracts.py -q`
passed **37 tests** (8 focused, 29 contracts; two existing deprecation warnings).
Focused Ruff and mypy checks also exited 0. Local cache behavior is accepted;
distributed persistence and revocation remain the limitations below.

- Real AWS/DynamoDB/S3 operations, Bedrock/model calls, human-only approvals,
  and private customer processing are `not_run`.
- This in-process adapter demonstrates the exact conditional immutable cache
  contract but is not a distributed guarantee: durable manifest transactions,
  cross-worker revoke propagation, DynamoDB lease/fencing, and S3 versioned
  artifact implementation remain for the approved cloud storage task.
- Per coordinator direction, no full-suite run was attempted against unrelated
  work in progress.
