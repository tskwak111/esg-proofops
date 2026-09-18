# TASK-004 — 표 정규화

2026-09-09 KST. Assigned local implementation and AT-004: **passed**. Production, model, AWS and human approval gates: **not_run/blocked**.

## Scope and interface

Read repository AGENTS, Master, domain v2, priority docs 26/27/28/31/19, TASK-004, AT-004/FR-004, execution order, graph and Observation/SourceRef schemas, and the accepted TASK-003 parser/graph implementation. Changed only `packages/proofops/application/ingest/normalize.py`, `tests/acceptance/test_tables.py`, and this evidence file. No shared schema/API, dependency, lockfile, legacy or Git mutations.

`normalize_tables(graph: CanonicalDocumentGraph, *, tenant_id: str) -> NormalizationResult` accepts the **rich internal graph**, validates its tenant/version/source/candidate associations, and returns immutable `observations`, `conflicts`, and the original `graph`. `Observation.to_dict()` projects the unchanged v1 Observation schema. Keep the internal result when storing artifacts; the public projection alone cannot carry all provenance or quality fields. AT-004 explicitly permits exercising the pure function instead of HTTP.

Implemented explicit long-form headers, year columns, Year + named metric columns, merged row fields and two-level year/basis headers. Each value keeps its own table/row/column, original text, exact Decimal string, source refs, full raw candidate blocks, source/manifest/version identities, field-to-cell parent relations and linked table/cell footnotes. Scope, subject, period, basis, boundary, method, baseline, category and denominator are retained when explicitly supplied. IDs change with source bindings; normalization does not mutate an existing graph or observation revision.

Different years, entities and market/location bases remain separate observations. `천 tCO2e` retains its raw unit and multiplies by exactly 1000; percent and percentage points remain distinct. Empty, `-` and N/A are not zero. Unreadable/unlocated/unknown/conflicted values or bindings do not become missing or a selected numeric value. Conflicts keep both parser candidates without a mean or majority winner. Evidence refs stay candidate, never verified/present merely because a number was parsed. Ambiguous duplicate field headers, invalid alignment/spans and more than 100,000 expanded cells produce review issues.

## Test-first record

All test commands below call real application behavior, with no normalization/parser mocks.

- Initial test collection found an incorrect test-module import (exit 2); corrected to the repository's relative import pattern. A shell `python` invocation was unavailable; subsequent Python commands used `uv run python`.
- `uv run pytest tests/acceptance/test_tables.py -q`: **15 failed**, exit 1, because `proofops.application.ingest.normalize` did not exist.
- After initial implementation: **1 failed, 14 passed**, exit 1. Real parser-to-observation succeeded, but JSONSchema rejected tuple bbox serialization. Converted API bbox to a JSON array without changing the schema/test.
- Same command: **15 passed in 0.80s**, exit 0.
- Added explicit multilevel header, missing binding, cell footnote and source-quality cases before fixes: **3 failed, 16 passed in 0.84s**, exit 1. Implemented those bindings and fail-closed states; **19 passed in 0.85s**, exit 0.
- Added ambiguous-header/expansion-limit and revision checks: **1 failed, 20 passed in 0.76s**, exit 1. The failure exposed duplicate entity headers silently overwriting one another. Rejected ambiguous headers and excessive expansion; final task command: **21 passed in 0.75s**, exit 0.
- Initial Ruff reported four long lines; mypy reported a nullable table-key type. Formatting and explicit string validation resolved them; no tests were removed or weakened.

## Final verification

| Exact command | Actual result |
|---|---|
| `uv run pytest tests/acceptance/test_tables.py -q` | Exit 0; **21 passed in 0.75s** |
| `uv run ruff check packages/proofops/application/ingest/normalize.py tests/acceptance/test_tables.py` | Exit 0; `All checks passed!` |
| `uv run ruff format --check packages/proofops/application/ingest/normalize.py tests/acceptance/test_tables.py` | Exit 0; `2 files already formatted` |
| `uv run mypy packages/proofops/application/ingest/normalize.py` | Exit 0; `Success: no issues found in 1 source file` |
| `uv run pytest tests/acceptance/test_tables.py tests/acceptance/test_parsing.py tests/acceptance/test_provenance.py tests/unit tests/contracts tests/integration -q` | Exit 0; **131 passed, 2 warnings in 9.16s** |
| `uv run pytest tests/acceptance/test_auth.py tests/acceptance/test_session_security.py tests/acceptance/test_upload_security.py -q` | Exit 0; **66 passed, 2 warnings in 3.08s** |
| `uv run python scripts/verify_architecture.py` | Exit 0; `verify_architecture: all checks passed` |
| `uv run python scripts/check_licenses.py --root . --env ENABLE_LEGACY_PYMUPDF=false` | Exit 0; `supply-chain gate: PASSED`; human rights/license and deployed-image gates remain separate |
| `uv build --package proofops --out-dir /tmp/proofops-task-004-dist` | Exit 0; built source distribution and `proofops-0.0.0-py3-none-any.whl` |

The two existing warnings concern Starlette/httpx and AnyIO deprecations. The wider suite was first run at 128 passing cases and rerun after the final implementation change; parallel workers added another test during this shared-workspace session, giving the final observed 131. No claim of whole-repository CI completion is made.

The local integration test constructs an explicitly **synthetic** PDF using the existing test helper, runs actual OpenDataLoader + pdfplumber on physical page 2, normalizes `Emissions / 2025 / 1234 tCO2e`, checks source locations, and validates the output against the fixed JSONSchema with format checking. The parser remains `fast_preview`; no vision verification is implied. Other table fixtures are explicitly synthetic candidate batches fed through the real graph fusion function.

## Remaining boundaries

- HTTP observations route, persistence/composition and browser E2E: **not_run in this task**; coordinator-owned integration. Local PDF→parser→normalization→v1 serializer is exercised above.
- Live product LLM/vision, AWS, deployed images, private documents, real-corpus accuracy/cost/performance, rights/legal approvals: **not_run/blocked** under the dispatch restrictions. This is not production approval or an accuracy claim.
- No cross-table/page continuation merge is attempted. Unrecognized/ambiguous layouts remain unresolved; general semantic header extraction is not simulated. Unsupported units remain raw (no guessed conversion); missing intensity denominators remain null for downstream comparability guards. Domain gaps remain unchanged.
- `scripts/validate_package.py` was not rerun because it writes coordinator-owned shared evidence and only validates documentation/contracts. Real app tests and schema validation were run as listed above.
- No new dependency, model call, cloud mutation, commit or push.


## Coordinator check

`uv run --no-sync pytest -q tests/acceptance/test_tables.py` exited 0: **21 passed**. Coordinator inspected source-binding/uncertainty boundaries and ran targeted Ruff and mypy across these ingest/application modules: both exited 0. HTTP/worker integration and real corpus/model evaluation remain separately tracked.
