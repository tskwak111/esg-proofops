# Reporting period versus frequency — 2026-09-19

The actual Doosan CHRO reporting claim remained blocked when preliminary
replicas chose reporting_period = null / `분기 1회` / `분기 1회`. All responses
passed literal-source validation; disagreement correctly prevented confirmation.
The root prompt distinguished target year from reporting period but did not
separate recurring reporting/meeting frequency from an observation period.

The system prompt now explicitly excludes bare frequency (`분기 1회`, `매월`,
annually, quarterly), while retaining an explicitly applicable observation
period such as `2025년 1분기` or `2024년`. This changes model guidance only;
source validation, unanimity and the Python grading rules are unchanged.

Before integration, a shadow diagnostic sent the candidate prompt on the real
failed sentence plus three agent-authored controls, each three times:

| Case | Expected reporting-period quote | Matching responses |
| --- | --- | ---: |
| Actual CHRO reporting-frequency sentence | null | 3/3 |
| 2025 first-quarter emissions result | 2025년 1분기 | 3/3 |
| 2024 annual emissions with monthly monitoring | 2024년 | 3/3 |
| Monthly management reporting only | null | 3/3 |

All 12 calls settled: USD0.006595380. This is a bounded diagnostic, not domain
accuracy or an end-to-end new review publication. Synthetic control packets
were explicitly diagnostic; no source graph or provenance was manufactured
for service acceptance. The integrated prompt is byte-identical to the tested
candidate; hashes, source text, outputs and request IDs are in the paired JSON.
Raw requests/responses stay under the private `.local/preliminary-period-probe-20260919`.

Existing claim list, first detail and cost endpoints all returned HTTP200 after
the change, and all three response bodies matched the pre-change snapshots.
Historical blocked claims/revisions remain unchanged. New runtime settings
receive the new prompt hash; frozen old runs are not silently upgraded. Rollback
is reverting this prompt change for future settings, never rewriting receipts.

Shared ledger after this diagnostic: 1,899 calls, USD11.4558179250 / USD20,
nine unsettled. No uncertain request was retried or refunded. Remaining work:
broader period phrasing and report coverage, any explicit new-run publication
trial, cold replay optimization and independent domain gold.

## Validation and stopping point

- Focused preliminary/transport/runtime tests: 92 passed.
- `uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`: 2,732 passed, seven skipped, two existing warnings, 213.00s.
- Ruff check and format: passed, 358 files; mypy: no issues in 191 source files.
- `uv build --package proofops`: source and wheel built.
- `uv run python scripts/validate_package.py`: 870 documentation/contract checks passed; separate from application/model validation.
- Actual diagnostic calls: 12 settled. Existing API readback unchanged. New full-pipeline review publication and cloud tests: not_run.
- Work stops here at the user's request; unfinished items above remain open.
