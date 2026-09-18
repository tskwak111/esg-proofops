# TASK-011 — 동일 문서 근거 검색

Date: 2026-09-09. Scope: FR-011 / AT-011, approved design, pure-function acceptance path. No commit/push, AWS mutation, real embedding/product model call, or customer data processing.

## Implemented

- `packages/proofops/application/evidence/retrieval.py`: `retrieve_evidence` consumes the existing rich `Claim`, a tenant-authorized immutable `CanonicalDocumentGraph` SourceStore snapshot, pinned `RulePackSnapshot`, `EvidenceSearchPort`, server context, optional GRI routes/vector and an injected token counter. `freeze_packet` produces immutable canonical JSON plus SHA-256; `EvidencePacket.to_dict()` returns a detached copy.
- Existing canonical graph, GRI entries, claim extraction receipts, rulepack source scopes and TASK-012 `verify_source_ref` are reused. Search filters pin tenant, document version, parse manifest and index generation. Returned source IDs/hashes are checked against the original graph, and every included quote is independently verified against its parser/source chain.
- Atomic claim offsets stay narrow; proximity or same page never expands direct scope. Same-table candidates carry ancestor header/row/table and footnote/caption context. Orphan cells, unverified context and omitted direct evidence block the packet. Far-page years/numbers never gain G1/G2/P1 scope; only the pinned rulepack's permitted global elements remain eligible. All binding records remain `undetermined`; retrieval never produces present/absent tags, grades or labels.
- GRI and section/table routes precede lexical20/vector20 retrieval; canonical source-ID dedupe and RRF(k=60) merge rankings. One bounded global round is used. At most 12 whole snippets, 1600 tokens per snippet and 12000 combined snippet tokens are included. The injected counter must be the selected model's tokenizer in production; tests explicitly use deterministic synthetic counters. Oversized blocks/bundles are omitted whole with coverage recorded rather than splitting number/header relationships.
- Search coverage records routes, pages, token usage, missing vector execution, provider failures, rejected hits, omitted/unprocessed source IDs, original source-quality states and parser issues. A search miss remains `unknown`. An unresolved GRI route never stops lexical/vector fallback.
- Packet identity includes original source/graph hashes, index generation, rulepack hash, query-vector hash, claim revision and the complete extraction receipt with model/prompt/rule hashes and replicate identity. Synthetic parser/extractor/search provenance propagates. No existing revisions are overwritten.
- `packages/proofops/adapters/aws/opensearch.py`: real SDK-client search adapter, with mandatory exact metadata filters in lexical and filtered k-NN query bodies, bounded response decoding, second identity checks, partial-result status and sanitized failure. Composition supplies the authorized client and explicit index; no SDK/dependency installation or fallback client is added.

`freeze_packet` is serialization, not a citation/binding authorization authority. Downstream tagging must consume a source-checked retrieval packet and still apply binding, prompt-injection and final tag validation. The candidate envelope is internal; no v1 API or database contract/migration was changed.

## Test-first and critical review

Initial command `uv run pytest tests/acceptance/test_retrieval.py -q --tb=no`: exit 1, **15 failed**, because retrieval/adapter modules did not exist. Implemented the missing real behavior, then corrected the synthetic table header's stale source end offset (kept the header-preservation assertion).

Critical review added and observed red tests for an unresolved table header leaving a packet usable and a wildcard index bypass: `uv run pytest tests/acceptance/test_retrieval.py -q --tb=short`, exit 1, **2 failed / 17 passed**. Fixed packet blocking and explicit-index validation.

A second boundary review added and observed red tests for an unknown/foreign claim SourceRef yielding KeyError instead of an authorization failure and an orphan direct cell leaving a usable packet: same command, exit 1, **2 failed / 19 passed**. Fixed reference identity validation before retrieval and direct-cell blocking. No tests were removed or relaxed.

## Verification commands and actual results

| Command | Result |
|---|---|
| `uv run pytest tests/acceptance/test_retrieval.py -q` | exit 0, **21 passed in 1.54s** |
| `uv run ruff check packages/proofops/application/evidence/retrieval.py packages/proofops/adapters/aws/opensearch.py tests/acceptance/test_retrieval.py` | exit 0, All checks passed |
| `uv run ruff format --check packages/proofops/application/evidence/retrieval.py packages/proofops/adapters/aws/opensearch.py tests/acceptance/test_retrieval.py` | exit 0, 3 files already formatted |
| `uv run mypy packages/proofops/application/evidence/retrieval.py packages/proofops/adapters/aws/opensearch.py` | exit 0, no issues in 2 source files |
| `uv run pytest tests/acceptance/test_auth.py tests/acceptance/test_session_security.py tests/acceptance/test_upload_security.py -q` | exit 0, **66 passed**, 2 existing FastAPI/Starlette deprecation warnings |
| `uv build --package proofops --out-dir /tmp/proofops-task-011-dist` | exit 0, rebuilt sdist and wheel after final code changes |
| `uv run python -m compileall -q packages/proofops/application/evidence/retrieval.py packages/proofops/adapters/aws/opensearch.py` | exit 0 |
| `git diff --check` | exit 0; new task files also checked with Ruff |

Final related unit/contract/integration regression command:

```sh
uv run pytest tests/acceptance/test_retrieval.py tests/acceptance/test_citations.py tests/acceptance/test_claims.py tests/acceptance/test_gri.py tests/acceptance/test_assurance.py tests/acceptance/test_rules.py tests/acceptance/test_provenance.py tests/contracts tests/unit tests/integration/test_local_api_composition.py tests/integration/test_local_parser_runner.py tests/integration/test_run_lifecycle.py -q
```

Result: exit 0, **300 passed, 2 existing deprecation warnings in 29.72s** after the final code changes.

The retrieval suite includes actual socket I/O through the production OpenSearch adapter to a **synthetic localhost HTTP corpus service**, plus real graph fusion, citation verification and rulepack source-scope handling. This validates adapter query/response integration and source rehydration; it does not claim live OpenSearch, vector-engine quality, real model behavior or product E2E completion.

## Concurrent/shared failures observed

- An earlier broader command ending with `tests/contracts tests/unit tests/integration -q` returned **297 passed / 6 failed** in 20.52s. The six failures were all in concurrently created `tests/integration/test_request_limits.py`, because `proofops_api.request_limits` did not yet exist. No TASK-011 assertion failed. Re-ran only the explicitly relevant completed integration files above; no shared test was edited or suppressed.
- `uv run pytest tests/security -q`: exit 1, **9 failed** because concurrently assigned `proofops.application.evidence.packet_guard` did not yet exist. Reported this to the coordinator; prompt-injection gate is not claimed passing. TASK-011's tenant/document/hash adversarial tests and existing authorization/session/upload security tests pass independently.
- An initial bare `python` edit command could not run (`command not found`); all subsequent Python execution used `uv run python`.

## Remaining gates / limitations

- **not_run**: live OpenSearch/AWS IAM/signing/index setup, real embedding/model calls, real customer or public-report production end-to-end runs, browser E2E. No authorization was given for those external actions. Production composition must provide the scoped original graph, authenticated OpenSearch client, compatible keyword/vector mappings and selected model tokenizer.
- **not_run**: production retrieval relevance/recall benchmarking, tokenizer performance and indexing chunk/overlap evaluation. Existing canonical paragraph/table units are reused; no speculative chunker, reranker model or second-round model call was added.
- **not_run by this worker**: `python scripts/validate_package.py`; it writes shared evidence files owned by the coordinator. The related package-contract/unit tests were run. This document does not confuse document validation with application tests.
- **blocked/not_run**: human domain/rights/legal/model/vision approval gates remain as defined; no standards clause numbers, model IDs or performance claims were invented.
- API route/storage composition, final tagging/prompt-injection gate and three-replicate execution belong to their assigned tasks. AT-011 explicitly permits the pure function acceptance path exercised here.

OpenSearch query shape was checked against primary documentation: [k-NN query](https://docs.opensearch.org/latest/query-dsl/specialized/k-nn/index/) and [efficient filtering](https://docs.opensearch.org/latest/vector-search/filter-search-knn/efficient-knn-filtering/). Filters require a compatible vector engine/index; this was not live-tested.
