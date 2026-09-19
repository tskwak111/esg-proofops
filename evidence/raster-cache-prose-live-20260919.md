# Raster v5 cache and prose trial — 2026-09-19

The successful replay cache retains at most 64 entries per process. Keys include
snapshot, job identity, original source, base graph, native receipt, scoped durable
registrations/receipts, current raster/native policy hashes, PDF reader versions
(including pdfminer.six) and platform. Failed replays are not cached. Returned
coverage/reference containers are fresh. Durable binding validation, envelope
coverage/reference comparison and final graph-hash validation still run on every
read; warm-cache tamper tests cover coverage, receipt and graph hash.

Saved Doosan v5 evidence read with both provider methods forbidden:

| Run | Cold seconds | Warm seconds | Verified blocks |
| --- | ---: | ---: | ---: |
| Previous selection | 51.002 | 0.173 | 22 |
| Prose-priority selection | 52.752 | 0.144 | 23 |

The first graph hash matches the prior uncached measurement exactly. These are
single cold/warm observations on a shared machine, not load-test percentiles.
Cold reads remain expensive; cache entries are not shared across worker processes.

A fresh actual parse-only trial used four crops, one provider call, USD0.044,
and completed in 132.926s. Strict correspondence recovered one CHRO paragraph
out of four requested crops (16 eligible, 15 still unresolved). The coordinator
viewed its original page-27 crop and found the extracted paragraph consistent.
This validates visible text correspondence only, not the claim's truth or E scope.
Two other prose crops differ in quote glyphs; the navigation crop differs in
order/noise. Matching was not weakened to raise recovery counts. Extract/tag
stages were not run for this new trial.

Shared ledger: 1,826 calls, USD10.3994877500 committed or reserved, eight unsettled;
USD20 cap unchanged. No uncertain call was retried or refunded. Machine-readable
run IDs, source/receipt hashes, coverage and measurements are in the paired JSON.
Independent semantic gold, broader report coverage and cold-read improvements
remain outstanding. This is not a production-readiness or accuracy claim.

## Validation

- `uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`: 2,732 passed, seven skipped, two existing deprecation warnings, 218.03s.
- `uv run ruff check .` and `uv run ruff format --check .`: passed, 358 files formatted.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`: no issues in 191 source files.
- `uv build --package proofops`: source and wheel built.
- `uv run python scripts/validate_package.py`: 867 documentation/contract checks passed; not an application accuracy test.
- Actual OCR: one paid request settled; cold/warm evidence replay made no provider calls. Cloud and new-trial extraction/tagging: not_run.
