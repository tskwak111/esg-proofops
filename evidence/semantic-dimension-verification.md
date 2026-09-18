# Semantic dimension extraction — 2026-09-09

Added a restricted entity/metric/boundary prompt and validator in
`evaluation/claim_dimensions.py`. The validator expands only these three fields
into the existing exact-source dimension validator; other dimensions remain unknown.
Every claim is required exactly once. Quotes must occur uniquely within that own
claim, even when another claim in the same source block names the entity/boundary.
Extra fields/grades are rejected. No new dependency, API/DB contract, domain grading
rule, source-quality approval or immutable revision changed.

## Actual trials

1. Thirteen existing LG Chem E-section sentence targets in one Upstage request:
   rejected. The model proposed LG화학 for all 13 claims, including ten whose own
   selected sentence does not contain that name. Two metric quotes also failed
   unique exact-source matching. The entire response remains failed/unresolved;
   no valid-looking fields were salvaged or accepted as evidence.
2. The same p24 baseline-level target alone, with the same prompt: source/schema
   validation passed, but entity, metric and boundary were all null. This avoids
   the invented entity in this one case but fails to extract the explicit metric.
   Isolation is not established as a sufficient remedy or general accuracy gain.

This experiment does **not** establish usable automatic semantic extraction.
Unknown remains unknown, and neither trial accepts a binding or numeric comparison.
The next extraction experiment should constrain semantic spans/candidate roles;
prompt-only free quoting is not ready to promote into the product path.

Receipts, raw returned fields, source identity, hashes, per-field quote diagnostics
and budget summaries: `evidence/semantic-dimension-results.json`. Full immutable
packets/request/response artifacts and runners are in `.local/dimension-pilot/`
(`semantics`, `semantics-isolated`, `run_semantics.py`, `run_semantics_isolated.py`).
The first launcher failed on PYTHONPATH before any model call; it was corrected
with `PYTHONPATH=.`. There were exactly two actual model calls, no automatic retries.

Added settled cost: $0.000628320. Cumulative ledger: 90 calls, $2.037525290
committed/reserved of $10, including two earlier unsettled calls. No Bedrock/AWS
actions or secret output. This is a development sample, not a corpus benchmark.

## Verification

Failing-first regression then seven focused tests passed. The regression uses two
claims in the same original block and rejects borrowing an entity/boundary from
the adjacent claim, while preserving explicit source quotes and null uncertainty.
Ruff lint/format passed (232 files), mypy passed (146 source files), four-package
builds, architecture and supply-chain checks passed. Deployed production E2E/AWS
remain not_run.

`PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`:
1,438 passed in 117.48s, two existing Starlette/AnyIO deprecation warnings.
`uv run --no-sync python scripts/validate_package.py`: 714/714 documentation and
contract checks passed, separately from application tests.
