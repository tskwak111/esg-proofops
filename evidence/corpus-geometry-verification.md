# Corpus geometry verification — 2026-09-09 KST

Finite parser boxes outside page bounds previously aborted an entire PDF. Fusion v3
preserves the original candidate and coordinates, sets its canonical bbox to null,
and records `source_geometry_invalid` / `unreadable`. No coordinate clipping is used.
Invalid candidates cannot become numeric values or SourceRefs. GRI indexing skips
invalid rows; authenticated source previews work without a highlight. Existing
strict validation still rejects malformed boxes and mismatched affine transforms.
No dependency, API-field or database-schema change was needed. Versioned replay
and rollback behavior are specified in `docs/27_PARSING_AND_PROVENANCE.md`.

## Actual PDF results

The 21 relevant originals (13 prior successes and 8 geometry failures) were rerun,
using the preceding three-page selections: **21/21 parsed and replayed, 63 pages**.
All **99 invalid candidates** remain in their saved graphs. The remaining 29 input
rejections were not rerun; their preceding classifications remain 23 PDF_INVALID,
3 resource-limit rejections, 2 password-required and 1 oversized input.

| Recovered report | Invalid candidates retained |
| --- | ---: |
| HDEC 2026 | 34 |
| HMM 2025 | 30 |
| HD Hyundai Electric 2025 | 19 |
| POSCO Future M 2025 | 1 |
| LG Chem 2025 | 2 |
| EcoPro BM 2025 | 7 |
| Hyundai Mobis 2026 | 1 |
| Kakao 2025 | 5 |

LG Chem's **119/119 physical pages** parsed in six bounded batches (1–20, 21–40,
41–60, 61–80, 81–100, 101–119), with verified graph reload for each. This is a
full-page batched smoke test, not one merged full-document manifest.
The original **50 SHA256 hashes are unchanged**; **4 v1 and 13 v2 manifests** replay
without changing their contents. Fresh runs write separate v3 manifests.

Actual downstream processing of all 21 sample graphs completed without an exception,
with invalid SourceRefs rejected. It yielded **0 numeric observations, 1 GRI entry,
and 701 normalization issues**. Numeric safety is additionally checked with a
constructed table regression, including forged block quality. These real samples
therefore establish parser availability and candidate retention, not useful numeric
extraction, table completeness, accuracy, or production readiness.

## Executed checks

Commands run from the repository root; Python tools use the locked local environment.

| Command | Result |
| --- | --- |
| `uv run --no-sync pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q` | 1382 passed, 2 warnings, 121.37s; before final GRI guard |
| `uv run --no-sync pytest tests/acceptance/test_geometry_issues.py tests/acceptance/test_gri.py tests/acceptance/test_tables.py tests/integration/test_source_api.py -q` | Final code: 32 passed, 2 warnings, 4.18s |
| `uv run --no-sync ruff check .` | Passed |
| `uv run --no-sync ruff format --check .` | 211 files passed |
| `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py` | 136 source files passed |
| `uv build --all-packages --out-dir .local/corpus-geometry/build` | Four packages: wheels and sdists built |
| `uv run --no-sync python scripts/validate_package.py` | See tracked `evidence/package_validation.json`; document/contract validation, not app tests |
| `uv run --no-sync python .local/corpus-geometry/run.py` | 21/21 actual parses and verified reloads |
| `uv run --no-sync python .local/corpus-geometry/full_document.py` | 119 pages, 6/6 batches and reloads |
| `uv run --no-sync python .local/corpus-geometry/check_downstream.py` | 21/21 graph safety checks |
| `uv run --no-sync python .local/corpus-repair/verify_legacy.py` | Four unchanged v1 manifests |
| `uv run --no-sync python .local/corpus-repair/verify_final.py` | Thirteen unchanged v2 manifests and 50 original hashes |

Overlapping test counts are not added. Warnings are existing Starlette/httpx and
AnyIO BlockingPortal deprecations. Geometry, preview and GRI regressions were each
observed failing before their corresponding fixes; logs are under
`.local/corpus-geometry/{red,preview-red,gri-red}.log`.

Local raw artifacts, result JSON, downstream checks and logs are retained under
`.local/corpus-geometry/`, excluded from Git along with user PDFs. Tracked regression
tests exercise the changed behavior independently of those private inputs.
Kiro independently inspected upstream coordinates and reviewed downstream callers;
its report is `evidence/corpus-geometry-review.md`. Orca run `run_42162c31c4d6`,
task `task_39897e118560` completed; dispatch released and owned terminal closed.
No Codex worker fallback was used.

Not run: all 7,454 corpus pages, independent gold/visual accuracy evaluation,
vision/OCR hybrid, browser UI rerun, actual product-model calls, AWS/staging.
No GitHub push, cloud mutation, or original PDF modification was performed.
