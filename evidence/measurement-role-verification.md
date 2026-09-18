# Claim measurement roles — 2026-09-09

Added restricted whole-claim measurement tagging in `evaluation/claim_dimensions.py`,
reusing the existing packet/source validation. Every selected claim must receive
exactly one allowed role: emissions_level, emissions_change, other or unknown.
Invented IDs, extra fields (including grades), omissions and duplicates fail closed.
Each proposal retains the full original claim SourceRef. These review roles are
not canonical metric IDs, accepted evidence or new grading criteria.

## Actual trial and review

One Upstage call on the same two LG Chem p24 sentences proposed emissions_level
for the 2030 baseline-level target and emissions_change for the 2025 project
savings (약 3만 톤). Neither sentence explicitly establishes the company/entity or
organizational boundary; both stay unknown. Source quality remains unverified and
binding remains undetermined. This two-claim trial is not an accuracy benchmark.

`evidence/measurement-role-results.json` combines the previous period/quantity
proposals for review only, after checking packet hash, source ID and claim span.
Per-field request provenance is retained. It also records nine same-document p97
table observations: annual emissions levels for 2023–2025, not project reduction
amounts. This is a coordinator review, not an implemented automatic semantic matcher.
No canonical metric normalization, entity/boundary acceptance, numeric comparison,
source approval, grade or immutable prior revision was changed.

Live request/response/result/budget artifacts: `.local/dimension-pilot/measurements/`.
Invocation: `.local/dimension-pilot/run_measurements.py`. Model, prompt, rule,
packet and source identities are preserved. One settled call added $0.000130515;
the shared ledger now has 88 calls and $2.036896970 committed/reserved of $10,
including two earlier unsettled calls. No Bedrock/AWS action or secret output.

## Verification

- Failing-first regression, then `uv run --no-sync pytest -q tests/integration/test_claim_dimensions.py`: 6 passed.
- `uv run --no-sync ruff check .` and `uv run --no-sync ruff format --check .`: passed (232 formatted files).
- `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`: passed, 146 source files.
- `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`: 1,437 passed in 109.52s; two existing Starlette/AnyIO deprecation warnings.
- `uv build --all-packages --out-dir .local/dimension-pilot/measurements-dist`: passed.
- Architecture and supply-chain checks passed; logs under `.local/dimension-pilot/measurements-*`.
- `uv run --no-sync python scripts/validate_package.py`: 713/713 documentation/contract checks passed (separate from application tests).
- Deployed production E2E and AWS remain not_run.

Next: validate compatible metric and entity/boundary evidence before permitting
numeric comparison. Missing dimensions remain unknown; report-wide company names
or equal ton units do not establish a compatible binding.
