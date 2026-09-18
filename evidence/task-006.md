# TASK-006 evidence — GRI Index 경로 (P0)

Date: 2026-09-09 KST. No commit/push; coordinator owns Git and shared contracts.

## Implemented contract

Implemented `build_gri_index :: CanonicalDocumentGraph + printed-page map ->
IndexEntry[]` in `packages/proofops/application/ingest/gri.py` and AT-006 in
`tests/acceptance/test_gri.py`.

- Reads only selected `table_row` blocks from the immutable canonical graph.
- Extracts GRI indicator codes and trailing printed-page references, including
  bounded numeric ranges.
- Accepts either printed-label -> physical-page candidates or physical-page ->
  printed-label maps, and resolves each label independently. It never assumes a
  document-wide page offset.
- Preserves tenant, document version, parse manifest, original index-row text,
  and the row `SourceRef` (physical page, bbox, hash/offset provenance).
- A missing printed label keeps any known candidates and returns
  `resolution_state="unresolved"`; it is never promoted to a confirmed
  `mismatch`. Confirmed content mismatch is not inferred from a page map alone.
- A caller-supplied foreign tenant is rejected as `NOT_FOUND`; graph candidate
  identity/provenance is checked before rows are read.

The test graph/parser is explicitly synthetic (`synthetic=True`, parser/version
names contain `synthetic`). It uses the real TASK-002/TASK-003 immutable graph,
fusion, and source-reference code; no mocks or model calls are used.

## TDD record

```sh
uv run pytest tests/acceptance/test_gri.py -q
```

Initial RED result: exit 1, `3 failed`; all failed with
`ModuleNotFoundError: No module named 'proofops.application.ingest.gri'`.

After the first implementation run, two tests passed and one failed because the
test helper classified a prose fixture beginning with `GRI` as a `table_row`.
The fixture prose was changed to preserve the same non-table behavior assertion;
no production expectation was removed or weakened. Final result: exit 0,
`3 passed in 0.02s`.

Mutation check: removing per-label lookup breaks the non-offset/candidate test;
returning `mismatch` or discarding partial candidates breaks the unresolved
test; removing the tenant guard breaks the foreign-tenant test.

## Fresh verification

```sh
uv run ruff check packages/proofops/application/ingest/gri.py tests/acceptance/test_gri.py
```

Exit 0: `All checks passed!`.

```sh
uv run ruff format --check packages/proofops/application/ingest/gri.py tests/acceptance/test_gri.py
```

Exit 0: `2 files already formatted`.

```sh
uv run mypy packages/proofops/application/ingest/gri.py tests/acceptance/test_gri.py
```

Exit 0: `Success: no issues found in 2 source files`.

```sh
uv run pytest tests/acceptance/test_gri.py -q
```

Exit 0: `3 passed in 0.02s`.

```sh
uv run pytest tests/acceptance/test_gri.py tests/acceptance/test_parsing.py tests/acceptance/test_provenance.py tests/contracts/test_package_contracts.py tests/integration/test_local_api_composition.py -q
```

Exit 0: `63 passed, 2 warnings in 3.72s`. Both warnings are existing
Starlette/httpx and AnyIO deprecations.

```sh
uv run pytest tests/unit -q
```

Exit 0: `16 passed in 0.85s`.

```sh
uv run python scripts/verify_architecture.py
```

Exit 0: `verify_architecture: all checks passed`.

```sh
uv run python scripts/validate_package.py
```

Exit 0: `Status: passed`; `Checks: 697 | passed: 697 | failed: 0`.
This is documentation/contract validation, not an application test.

```sh
uv build --package proofops --out-dir /tmp/task006-build.wSloeY
```

Exit 0: source distribution and wheel built successfully outside the repository.

The first two attempted `pip-audit --locked` forms were not valid for this uv
workspace (`--locked` required a project path, then reported no supported
lockfiles). The corrected locked export audit was:

```sh
uv export --frozen --no-dev --no-emit-workspace --no-hashes | uv run pip-audit --progress-spinner off -r /dev/stdin
```

Exit 0: `No known vulnerabilities found`.

## not_run / remaining gates

- `GET /v1/runs/{run_id}/quality` HTTP wiring and browser E2E: **not_run / out
  of assigned TASK-006 files**; the acceptance contract permits invoking the
  pure function, which was exercised. No shared API/schema file was changed.
- Real customer/public ESG reports, actual GRI licensing/rights approval, and
  human legal/data approval: **not_run / human-only gates**.
- Live Bedrock/model/AWS calls and AWS mutations: **not_run / prohibited for
  this dispatch**. No LLM grade/label path exists in this change.
- Confirming that a resolved target page semantically lacks the promised
  disclosure needs separately verified content binding; this page-map-only
  function does not manufacture an `index_mismatch` finding.

Changed files: `packages/proofops/application/ingest/gri.py`,
`tests/acceptance/test_gri.py`, `evidence/task-006.md`.


## Coordinator check

`uv run --no-sync pytest -q tests/acceptance/test_gri.py` exited 0: **3 passed**. Coordinator inspected source-binding/uncertainty boundaries and ran targeted Ruff and mypy across these ingest/application modules: both exited 0. HTTP/worker integration and real corpus/model evaluation remain separately tracked.
