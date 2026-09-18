# Local analysis API evidence

Date: 2026-09-09 (Asia/Seoul)

## Scope

- Added local read projections for `observations_get`, `assurance_get`, and
  `safe_harbor_get` without changing domain rules, DTO contracts, shared stores,
  composition, or `main.py`.
- `LocalAnalysisStore` reloads the fence-published parser graph and calls
  `normalize_tables(...).observations` plus `Observation.to_dict()`.
- Assurance currently calls the accepted `match_assurance(None, ClaimContext(...))`
  convention for each discovered claim. It returns `undetermined` and does not
  infer a provider, period, metric, boundary, or coverage from report text.
- Safe-harbor reads the current immutable tag head. Missing confirmation/category
  is represented as `applicable=null`, `category=null`, `mapping_status=unresolved`,
  and `GAP-002`; an explicit confirmed category is passed to
  `record_safe_harbor`, which preserves `GAP-001`, a null reasonable-basis result,
  and `legal_effect=not_determined`.

## Transaction and HTTP boundaries

- Heavy graph, extraction, and tag-input replay occurs before the SQLite writer.
  The caller-owned transaction then rechecks the immutable run snapshot and
  `mutation_epoch`, reads current tag heads, and creates the shared
  `catalog_pages` snapshot.
- Continuations read only the signed 15-minute stored catalog snapshot, so a head
  mutation does not alter later pages or open a nested artifact-loader transaction.
- Routes require `viewer`, use independent 120/min/user operation buckets, return
  `Cache-Control: no-store`, validate UUID path/query types, and validate the full
  serialized response through strict extra-forbidding Pydantic DTOs.
- Missing/foreign runs return 404, unpublished inputs return 409, invalid/expired
  cursors return 400, catalog capacity returns 503, and an unreplayable confirmed
  safe-harbor head returns `409 SAFE_HARBOR_PENDING` only on that route.

## Verification

Initial TDD red run:

```text
uv run pytest tests/integration/test_analysis_api.py -q
3 failed: ModuleNotFoundError: proofops.adapters.local.analysis_store
```

Scoped implementation and domain regressions:

```text
uv run pytest tests/acceptance/test_tables.py tests/acceptance/test_assurance.py \
  tests/acceptance/test_safe_harbor.py tests/integration/test_analysis_api.py -q
80 passed, 2 upstream deprecation warnings

uv run pytest tests/contracts/test_package_contracts.py -q
29 passed, 2 upstream deprecation warnings

uv run pytest tests/integration/test_analysis_api.py \
  tests/integration/test_local_api_composition.py \
  tests/contracts/test_package_contracts.py -q
36 passed, 2 upstream deprecation warnings

uv run pytest tests/integration/test_analysis_api.py \
  tests/integration/test_local_api_composition.py \
  tests/contracts/test_package_contracts.py tests/acceptance/test_tables.py \
  tests/acceptance/test_assurance.py tests/acceptance/test_safe_harbor.py -q
111 passed, 2 upstream deprecation warnings

uv run pytest tests/acceptance/test_auth.py tests/integration/test_request_limits.py -q
43 passed, 2 upstream deprecation warnings

uv run pytest tests/integration/test_analysis_api.py tests/integration/test_claim_api.py \
  tests/integration/test_revision_coverage.py \
  tests/integration/test_local_api_composition.py -q
18 passed, 2 upstream deprecation warnings

uv run ruff check packages/proofops/adapters/local/analysis_store.py \
  apps/api/src/proofops_api/routers/analysis.py tests/integration/test_analysis_api.py
All checks passed

uv run mypy packages/proofops/adapters/local/analysis_store.py \
  apps/api/src/proofops_api/routers/analysis.py
Success: no issues found in 2 source files

uv run python scripts/validate_package.py
Status: passed; 705/705 documentation and contract checks
```

The integration fixture uploads a generated PDF, runs the real local parser and
immutable checkpoint replay, then performs HTTP requests. It asserts fixed JSON
schemas, candidate (not fabricated verified) source flags, explicit assurance and
safe-harbor uncertainty, tenant isolation, pending gates, typed UUIDs, cursor
tampering/limit mismatch, pagination after a tag-head mutation, capacity failure,
and viewer rate limiting.

## Not run and handoff

- No AWS, network, product-model, OCR, vision, or human-approval operation ran.
- Root completed composition and route mounting with
  `LocalAnalysisStore(runs.store, uploads, parser, claims, tags)` and
  `build_analysis_router(analysis, auth_store)`; the composed API/contract checks
  above passed after that wiring.
- No public confirmed-tag reconstruction helper exists in the current tree. The
  adapter therefore uses the same strict `ConfirmedTags`/`ConfirmedFact` and
  `_source_ref_from_dict` reconstruction already used by rescore code; no new
  domain helper or dependency was added.

Coordinator verification: composed routes plus analysis and rescore tests passed
49 tests; scoped ruff and mypy (4 modules) passed. Review of changed-pack behavior
confirmed that existing `create_rescore` rejects changed safe-harbor checklists
with `RETAG_REQUIRED`, so a compatible rescore preserves the checklist used with
the pinned tags. A focused regression for that existing gate passed (1 test);
no redundant changed-pack gate or rule override was added to this projection.
