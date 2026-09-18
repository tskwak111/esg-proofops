# TASK-008 — atomic claim discovery evidence

Date: 2026-09-09. Assigned scope: FR-008 / AT-008; application claims, agent extraction,
acceptance tests and this evidence file only. No commits, pushes, shared contracts,
dependencies, lockfiles, API routes or DB storage were changed by this worker.

## Implemented behavior

- `discover_atomic_claims(graph, ClaimScope(...), extractor=...)` consumes the accepted
  rich `CanonicalDocumentGraph` from TASK-003. Full mode visits every graph block;
  there is no topic/count quota. Declared subsets record omitted block/page IDs and
  full mode rejects page selection. Coverage means the supplied graph, not proof
  that the upstream parser recovered every claim in the PDF.
- Every candidate claim has a raw-text source span, physical page, canonical bbox,
  tenant/version/manifest/source hash, source quality and immutable extraction
  receipt. NFC offsets map back to raw Unicode code-point offsets through the
  existing geometry implementation. Claims remain candidate sources; this stage
  never produces `present`, grades, labels, confirmed tracks or evidence binding.
- Strict response validation rejects extra fields, hallucinated quotes, invalid
  or overlapping offsets. Omitted text becomes `unknown`; timeouts/connection
  failures preserve sanitized unknown records while later blocks continue.
  Conflict/unreadable/unlocated/empty sources remain unresolved. All upstream
  quality issues are retained, including unreadable pages with no source block.
- Frozen claim/receipt values preserve model/prompt/extraction-rule hashes,
  replicate ID, extraction epoch, packet hash and raw structured response JSON/hash.
  Changed source/response/profile creates a different deterministic claim identity;
  replays preserve identity. No revision store is overwritten or introduced.
- `Claim.to_summary()` validates against the existing v1 `ClaimSummary` JSONSchema;
  `track` and `decision` remain null. TASK-009 owns track classification.
- `SyntheticClaimExtractor` actually splits Korean performance/goal compound
  sentences and classifies a small lexical demonstration vocabulary. It is always
  explicitly synthetic, including when parsing a real local PDF. The tests use
  generated sources, never customer data. `StructuredClaimExtractor` implements
  the extraction port with caller-owned response transport; this dispatch installs
  no live provider or runtime binding.

## Failing tests and corrections

Command: `uv run --no-sync pytest tests/acceptance/test_claims.py -q`

1. Initial acceptance tests: exit 1, **15 failed in 0.08s**, because the assigned
   claims module did not exist. No stub or expected-output mock was used.
2. Minimal real extraction implementation: exit 0, **15 passed in 0.05s**.
3. Added empty-source/page-quality regression: exit 1, **1 failed, 16 passed in
   0.07s**. Empty source was silently omitted. Preserving explicit unknown records
   and graph quality issues fixed this: **17 passed in 0.05s**.
4. Real local PDF integration initially returned **1 failed, 17 passed in 0.62s**:
   the reused parser fixture placed repeated text in running headers, removed by
   OpenDataLoader before graph construction. The same generated PDF text was moved
   into the page body; all three exact expected quotes remained asserted. No parser
   code or acceptance assertion was weakened. Result: **18 passed in 0.69s**.

The suite covers compound splitting without borrowing the target year, 35 claims
with the same topic, distinct source locations with identical text, reasoned
non-claim exclusions versus unknown, declared subsets, tenant/version/manifest
identity rejection, source quality states, Unicode round-trip, immutable replay,
strict structured response guards, partial failures, existing API schema projection,
extraction-epoch identity and actual local PDF parser integration.

## Final verification

`--no-sync` retains the existing TASK-003 optional parser installation in the shared
workspace. No dependency synchronization or installation was needed.

```sh
uv run --no-sync ruff check packages/proofops/application/claims.py apps/agent/src/proofops_agent/extraction.py tests/acceptance/test_claims.py
```

Exit 0: `All checks passed!` Initial formatting checks found one import ordering
and two long-line findings; these were corrected before final checks.

```sh
uv run --no-sync ruff format --check packages/proofops/application/claims.py apps/agent/src/proofops_agent/extraction.py tests/acceptance/test_claims.py
```

Exit 0: `3 files already formatted`.

```sh
uv run --no-sync mypy packages/proofops/application/claims.py apps/agent/src/proofops_agent/extraction.py
```

Exit 0: `Success: no issues found in 2 source files`.

```sh
uv run --no-sync pytest tests/acceptance/test_claims.py tests/acceptance/test_parsing.py tests/acceptance/test_provenance.py tests/acceptance/test_auth.py tests/acceptance/test_preflight.py tests/acceptance/test_supply_chain.py tests/unit tests/contracts tests/integration -q
```

Exit 0: **259 passed, 2 warnings in 10.21s**. Includes the 18 claim cases, actual
local parser tests, source provenance, tenant/auth/preflight/security regressions,
unit tests, package contracts and current local API/run integration. Existing
Starlette/httpx and AnyIO deprecation warnings were emitted. Package contract
validation is not claimed as application coverage; application tests ran separately
in the same command.

```sh
uv run --no-sync python scripts/verify_architecture.py
uv build --package proofops --out-dir /tmp/task008-build-proofops
uv build --package proofops-agent --out-dir /tmp/task008-build-agent
git diff --check -- packages/proofops/application/claims.py apps/agent/src/proofops_agent/extraction.py tests/acceptance/test_claims.py
```

All exited 0. Architecture checks passed; both source distributions and wheels
built. Build artifacts are outside the repository. `git diff --check` does not
inspect untracked file content; Ruff check/format validated the new files.

## Important limits and handoff

- Model inference, model accuracy/recall, AWS mutation/integration, customer-data
  processing, rights/legal approvals and production E2E: **not_run / blocked by
  external gates**. No actual model requests occurred. No production-ready or
  full-document semantic-recall claim is made.
- Synthetic extraction is a lexical demonstration with known vocabulary and
  connective limitations, explicitly documented in code. Ambiguous/unrecognized
  text remains unknown. An approved model/transport and measured extraction corpus
  are required for product semantic extraction; the strict transport boundary is
  ready for that integration. Cross-page semantic sentence joining is not measured
  or implemented by the local demonstration adapter.
- `GET /v1/runs/{run_id}/claims`, persistence and worker-stage composition remain
  coordinator-owned integration work. AT-008 explicitly permits the pure function
  path, which is exercised here. No HTTP claims route or UI E2E is claimed complete.
- Shared contracts and public DTOs were reused unchanged. Track/topic domain
  approval, three final tagging replicas and rule grading belong to later tasks.
  The extraction receipt's replica identity does not represent three-vote consensus.
- Critical/important self-review found and fixed the empty-source/quality-issue
  coverage loss; no unresolved critical issue remains in the tested local scope.
  No tests were deleted, weakened or replaced by mocks.


## Coordinator check

`uv run --no-sync pytest -q tests/acceptance/test_claims.py` exited 0: **18 passed**. Coordinator inspected source-binding/uncertainty boundaries and ran targeted Ruff and mypy across these ingest/application modules: both exited 0. HTTP/worker integration and real corpus/model evaluation remain separately tracked.
