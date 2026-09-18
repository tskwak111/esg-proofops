# Original table layout context — 2026-09-13

Baseline 11cff6b. Optional `evaluation.table_role_pilot --layout` now reads native
PDF words inside the already located table using installed pdfplumber. Source
SHA, tenant, table identity and compatible page geometry are checked. Word indices,
full coordinates and reader version stay in the archived packet; compact positioned
fragments reach the model. No dependency, canonical cell repair or domain change.

Whitespace grouping separates adjacent runs; it does not determine semantic
ownership. Rotated/nonzero-origin geometry is rejected. Empty text is unreadable,
not absent. This evaluation helper is not a production ingestion worker and does
not provide OCR, a resource-isolated parser or automatic column reconstruction.

## Actual source replay

Three original PDFs, five selected tables, zero clipped words:

| Report / physical page | Words | Fragments |
| --- | ---: | ---: |
| KB / 30, two tables | 321 | 84 |
| Naver / 84 | 105 | 24 |
| Kia / 45, two tables | 38 | 22 |

Naver's `(진행 중)` is recovered at x407.05–433.1725, y255.5035–263.0035,
separate from the 6MW PPA bullet at x443.095–576.0025,
y243.5035–251.0035. This agrees with the original page image reviewed in the
previous wave. Both flattened parser receipts remain unchanged. Layout recovery
does not establish which activity the status qualifies.

One actual Pro3 call with the new context still mislabeled the mixed Naver cell;
the existing validator rejected it. Thus geometry context alone has not solved
semantic extraction. KB was blocked before reservation by the existing serialized
request-byte limit; do not use the raw UTF-8 text length as that limit's measure.
Kia was a local replay only. No retries or model upgrade were attempted.

Call cost USD0.000578655; shared committed/reserved USD7.275933120 / USD10,
1,247 ledger entries and six pre-existing unsettled reservations unchanged.
Artifacts remain under `.local/complex-table-layout-v11`; public hashes and counts
are in `layout-comparison.json`. These are diagnostics, not an accuracy benchmark.

## Remaining work

Mixed cells need source-bound atomic target extraction before reliable role
classification; merely appending layout to a whole-cell tagging request is
insufficient. Large table packets require bounded per-table requests. Neither is
silently enabled here. Source approval and production grades remain untouched.

## Verification

Fail-first geometry separation/source mismatch checks and a real generated-PDF
packet integration check pass. Focused suite: 21 passed. Ruff passed; mypy passed
158 files. All four Python packages built; documentation/contracts validator
749 passed (not application accuracy). `uv run pytest -q`: 1,762 passed,
two existing dependency warnings, 138.79 seconds. Separate staging-gate mypy and
the pilot CLI help check passed. Tests cover repository behavior, not general
report accuracy; no AWS or production deployment was run.
