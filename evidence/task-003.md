# TASK-003 — parsing and conflict preservation

Date: 2026-09-09 KST. Local implementation and AT-003: passed. Live vision, AWS and production gates: **not_run**, not production approval.

## Scope and contracts

Implemented the assigned OpenDataLoader adapter, immutable candidate/graph fusion, acceptance tests, and the coordinator-approved `application/ports/parsing.py`. Shared API/JSON schemas, composition, dependency manifests/lockfiles and Git remain coordinator-owned. Read AGENTS, Master, original domain v2, docs 26/27/28/31/19, TASK-003 in docs/20, the fixed document graph and quality issue contracts, and existing geometry/source types. Reused TASK-002 `NativeSource`, `PageGeometry` and normalization/coordinate helpers and TASK-038 real quarantine PDF verification; no legacy policy/scorer/label code was copied.

The adapter entry point is `OpenDataLoaderParser(artifact_root).parse(source, profile, tenant_id=...)`. `SourceArtifact` pins tenant/document/version, verified content hash and object version; `ParserProfile` pins manifest ID, physical page selection, Java executable and resource limits. `fuse_candidates(tuple[CandidateBatch, ...], tenant_id=...)` is pure and preserves each parser run's native candidate and edges. `CanonicalDocumentGraph.to_dict()` emits the unchanged public document graph schema; the internal graph and separately persisted quality/candidate artifacts carry unresolved conflicts and provenance. Consumers must retain that envelope: conflicted blocks have no winner and cannot produce a selected SourceRef.

## Actual behavior exercised

- Executed installed OpenDataLoader PDF **2.5.7**, Java **21.0.12.1** selected only for the subprocess, and actual **pdfplumber 0.11.10** table extraction. Generated text and ruled-table PDFs with pypdf using indirect content/font objects. These PDFs and direct conflict candidate fixtures are explicitly synthetic; no parser invocation was mocked.
- Verified selection of physical page 2 from a three-page document, extracted `1234 tCO2e` table cell, retained both parser provenances, rewired native aliases/edges, and validated the public graph with JSON Schema plus format checking.
- Disagreeing `1,234` / `1,284` candidates remain conflict/open with both raw texts, no winner, and no verified/present evidence. Matching parser-family outputs do not become independent verification. Missing geometry stays null/unlocated. Tenant/version/source/manifest mismatch and dangling edges fail closed.
- Actual OD 2.5.7 output is already rotation/CropBox-relative **display bottom-left**. Preserve its original bbox plus affine and derive original PDF-native coordinates before using TASK-002 geometry. Tests cover CropBox `[50,100,550,750]` and rotations 0/90/180/270; x=72 in original PDF becomes x=22 on the unrotated cropped page. OD can omit rotated text; missing output is explicitly unreadable, never evidence absence. pdfplumber's top-left MediaBox coordinates have a separate transform/provenance. Mutable caller geometry is snapshotted; invalid or inconsistent affine/bbox data is rejected.
- Publish source JSON/Markdown, page geometry/printed labels, auxiliary output, canonical graph, full candidates, quality issues and hash manifest under tenant/version/manifest directories. Preserve source object/hash, parser/config/run/family versions, JAR hash, JVM version and physical page mapping. Files are read-only and final directory publication is atomic; concurrent identical manifest attempts produce one result and one `PARSE_MANIFEST_EXISTS`, with no temporary-directory residue or overwritten revision.
- Verify real PDF input before execution. Run parser in a separate process group with deadline, aggregate output limit, sampled process-group RSS (including Java descendants), child CPU/file-size limits, suppressed stdout/stderr, and group termination on failure. Real tiny output/memory limits reject without a successful manifest. Blank PDF extraction records `no_extractable_text` / unreadable.

## Test-first and verification record

Initial acceptance tests failed because the assigned parser/fusion modules did not exist (5 failures); implementing fusion alone left the two actual-parser tests failing until real parser execution was implemented. During the coordinate extension, a test fixture import error (`RectangleObject`) was corrected without weakening assertions. The explicit immutable-provenance regression was then run **before** its fix:

```sh
uv run --no-sync pytest tests/acceptance/test_parsing.py -q
```

Result: **1 failed, 8 passed in 2.94s**, exposing caller list mutation changing stored parser bbox. After snapshot/affine validation implementation, the same command returned **9 passed in 2.58s**. Formatting passes initially reported import ordering/line-length findings; `ruff check --fix` and `ruff format` corrected these, and the final read-only checks below passed.

```sh
uv run --no-sync ruff check packages/proofops/adapters/parsing/opendataloader.py packages/proofops/application/ingest/graph_fusion.py packages/proofops/application/ports/parsing.py tests/acceptance/test_parsing.py
```

Exit 0: `All checks passed!`.

```sh
uv run --no-sync ruff format --check packages/proofops/adapters/parsing/opendataloader.py packages/proofops/application/ingest/graph_fusion.py packages/proofops/application/ports/parsing.py tests/acceptance/test_parsing.py
```

Exit 0: `4 files already formatted`.

```sh
uv run --no-sync mypy packages/proofops/adapters/parsing/opendataloader.py packages/proofops/application/ingest/graph_fusion.py packages/proofops/application/ports/parsing.py
```

Exit 0: `Success: no issues found in 3 source files`.

```sh
uv run --no-sync pytest tests/acceptance/test_parsing.py tests/acceptance/test_provenance.py tests/acceptance/test_upload.py tests/acceptance/test_upload_security.py tests/acceptance/test_supply_chain.py tests/unit/test_legacy_characterization.py tests/contracts/test_package_contracts.py tests/integration/test_local_api_composition.py -q
```

Exit 0: **156 passed, 2 warnings in 7.00s**. Warnings concern existing Starlette/httpx and AnyIO deprecated APIs. This includes actual local parser integration, source coordinate/offset regression, upload quarantine security, supply-chain/legacy characterization, package contracts and existing local API composition; it does not claim the quality HTTP endpoint is wired to this parser.

```sh
uv run --no-sync python scripts/verify_architecture.py
uv build --package proofops --out-dir /tmp/task003-build
```

Both exited 0: architecture checks passed; source distribution and wheel built successfully. `--no-sync` follows coordinator instructions to retain the already-installed optional parsing extra. Build outputs are outside the repository.

## Explicit limits and remaining gates

- Table vision cross-check: **not_run** (approved product model/runtime/account absent; calls prohibited in this dispatch). Every detected table gets an open `table_vision_not_run` issue; manifests/graph retain `fast_preview`. No grade/label/absence is inferred from skipped verification.
- Local artifact storage is explicitly `local_synthetic_storage=true`; generated sources are `synthetic_source=true`. This does not implement or validate S3/object-lock/vault deployment. Local file permissions protect accidental writes, not a malicious process with the same OS account.
- Production sandbox, network egress policy, container memory isolation, deployed JVM/JAR SBOM, actual AWS/model execution, customer-data rights/legal approval and production E2E: **not_run/blocked by external gates**. Local RSS supervision is sampled, not a hard container memory limit. No customer documents, credentials, cloud mutations or product model requests were used.
- Graph region alignment uses the docs/27 development IoU default of 0.8 and conservative text equality, not an accuracy claim; pairwise grouping is quadratic and documented in code. Large-document throughput/accuracy benchmarks are not_run. Immutable native candidates enable later review without changing prior revisions.
- Shared quality API/run orchestration and downstream table normalization are coordinator/downstream tasks. This change supplies `graph.issues` and persisted `quality.json`, not an unapproved new endpoint. Browser E2E is not_run for this parser-only scope.
- Dependency installation/lock/SBOM/license audit belong to coordinator; see `evidence/dependencies-task003.md`. No source-less present, unknown-to-absent conversion, LLM grade, revision overwrite, commit or push was introduced.

Coordinator independently reran the nine real-parser acceptance cases together
with observability and local API composition: **26 passed**, two existing dependency
warnings. Targeted Ruff and mypy passed for the parser, fusion and port. TASK-004,
006, 007 and 008 may consume the rich graph while downstream HTTP wiring proceeds.
