# External table recovery — 2026-09-13 KST

Evaluation-only result, not service release or verified evidence. Original physical
pages Kia45, KB30 and NAVER84 were submitted once each in standard and enhanced
modes to the existing Upstage document parser. All six calls settled. Both modes
recovered the same counts: Kia2 tables/24 cells, KB2/48, NAVER1/9; five unique tables
and81 cells overall. These are selected development examples, not accuracy estimates.
The two modes share one parser family and do not provide independent corroboration.

## Accepted implementation

`evaluation/html_table_cells.py` uses the standard library to preserve decoded cell
text, row/column positions and merged spans. It rejects malformed, ragged, nested,
overlapping and oversized grids, including rowspans inventing absent source rows.
`evaluation/upstage_table_candidates.py` converts archived responses into the
existing candidate graph types. Original bytes, tenant, physical-page mapping,
reconstructed PDF-subset request hash and raw-response hash must match. Each
conversion creates a new parse manifest. No existing graph/revision is modified.

Table rectangles use provider coordinates and the original page geometry. Rotated,
cropped or nonzero-origin pages are explicitly unsupported. Cells have no invented
coordinates. Six final-code replays produced zero located cells, zero verified
blocks and zero normalized observations. Therefore this does not yet close numeric
evidence attribution or enable automatic grades. The default runtime parser is unchanged.

Original page PNGs were inspected locally using existing pdfplumber/PDFium because
pdftoppm was unavailable. Kia's target/actual/year headers and repeated95.0 values,
KB's merged financial-impact headers and NAVER's combined achieved/in-progress
status show why flattened text alone is insufficient. KB's repeated word
`개발 개발` is present in the original; it was not automatically cleaned away.
This inspection is coordinator review, not independent human gold.

## Cost and immutable evidence

Six calls cost an estimated USD0.132 including10%VAT: standard USD0.011/page and
enhanced USD0.033/page. The existing ledger now records1151 calls, five unresolved
USD1 reservations and USD6.1444487450 committed/reserved of the authorized USD10.
Settled estimates are USD1.1444487450; reserved USD5 is not confirmed spend.
No retries, refunds, alternate ledger or additional model calls were used for replay.
`table-recovery-results.json` indexes request IDs, original/source/response/code
hashes, timings and fresh candidate artifacts. Raw local files remain immutable.

## Orchestration and review

Orca run `run_436abc222c05`: HTML parser task `task_2c9d16aed1d7` succeeded with
Muse Spark1.3 Free; coordinator added a failing rowspan regression and fixed it.
Integration review task `task_837b905e2af9` completed with Muse Spark1.2 Free.
Coordinator rejected its company/metric whitelist, approximate coordinates and
implicit graph mutation recommendations; the source-bound evaluator above replaces
those suggestions. Both dispatches settled, were released and terminals closed.
The final reclaimable-worker query returned no workers.

## Verification

- Focused HTML/converter tests:18 passed, including actual transport-receipt shape
  via offline HTTP stub, fusion, tenant/content/page/hash and malformed-input checks.
- Ruff across apps/packages/tests/evaluation: passed.
- Mypy across application and evaluation targets:153 files passed, three existing
  untyped-body notes.
- Actual archived responses:6/6 reconstructed and converted with final code; no paid calls.
- `uv run pytest -q`:1627 passed, two dependency deprecation warnings,113.42s.
  Includes unit, integration, contract, backend E2E and security tests.
- `uv run python scripts/validate_package.py`:740/740 passed (documents/contracts only).
- `uv run python scripts/verify_architecture.py`: passed.
- No dependency/API/DB/runtime changes; package/web builds and dependency audits
  from immediately preceding commit15a637f remain applicable, not rerun here.
- New browser E2E, deployment, human gold and source approval: not_run.

Next required integration work is explicit year/unit/metric binding plus actual
cell-source location validation. Unlocated cells must stay unknown; table recovery
alone cannot authorize present labels or establish service-level accuracy.

## Zero-cost glyph-location follow-up

The existing pdfplumber search was tested inside the actual provider table regions
using whitespace-flexible literal cell text. Geometric reading order found46 unique,
six ambiguous and29 unmatched cells out of81. Switching only `use_text_flow=True`
found73 unique, seven ambiguous and one unmatched (Kia22/2/0, KB44/4/0,
NAVER7/1/1). PDF content-stream order avoids many interleaved-column failures here.
Repeated95.0 values and recurring labels remain ambiguous. Unique text matches are
location candidates, not proof of correct cell assignment or independent accuracy.
No cell bbox, source-quality field, stored graph or decision was changed. Both
scripts/results and hashes are indexed in `table-recovery-results.json`. No new API
calls, dependency or runtime changes were required. A future integration must
preserve separate local-glyph/provider provenance and reject ambiguous matches.
