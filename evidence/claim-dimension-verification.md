# Claim-dimension and period-role pilot — 2026-09-09

## Result and limitation

Added `evaluation/claim_dimensions.py`: source-bound dimension proposal validation
and a narrower local-year-candidate / model-role path. This is opt-in evaluation,
not an API/DB change or accepted evidence binding. No old claim or source revision
was changed. General metric/Scope/unit/entity extraction is NOT ready for use.

Four real Upstage development trials over two pinned LG Chem p24 sentence targets:
1. English nested-field prompt + JSON mode returned all 24 fields null. Structural
   validation passed, but no useful dimensions were extracted. New per-claim
   populated_fields/review_reason makes all_dimensions_unknown explicit.
2. Korean field descriptions + JSON mode returned the field descriptions as values.
   Exact source checks rejected them; no proposed dimensions were admitted.
3. Same Korean input without JSON mode returned malformed JSON, fabricated entity/
   boundary text, and also treated 2030 as a reporting period. Rejected without
   JSON repair or partial promotion. Thus JSON mode alone does not explain the
   problem, and source-exactness alone would not prove semantic role correctness.
4. Locally enumerated year mentions + flat ID/role response returned 2019년 as
   baseline_period, 2030년 as target_period and 2025년 as reporting_period. All
   three source refs resolve within their own selected sentence, and coordinator
   comparison with the original text supports these roles in this small case.

The fourth path lets the model classify existing quotes rather than create quotes.
No fields outside periods were populated by that path. Missing company, Scope,
unit and other dimensions remain unknown. A single development case is not a
precision/recall result or evidence that all annual reports are handled correctly.

## Contracts and traceability

Original candidate artifacts are rebound to their authorized graph before use.
The fixed-field validator requires every claim exactly once and all allowed keys,
rejects extra grade fields, invented/ambiguous/nonlocal quotations, and returns
immutable source refs via existing quote/location helpers. Overlapping dimensions
may refer to the same original text; no quote is rewritten or borrowed.
Null values remain unknown, never absent. Proposed dimensions keep the original
unverified quality and binding_status=undetermined.

The period path enumerates only 1900–2099 year mentions and accepts one explicit
role or unknown per candidate. Missing/duplicate candidate decisions and multiple
years assigned to a single claim-period role are rejected. Repeated identical year
quotes can remain ambiguous under the existing quote validator. Other date formats
and general dimension extraction are still outside this bounded experiment.

Requests, raw responses, packets and budgets are retained separately in
`.local/dimension-pilot/{first,second,plain-json,periods}/`; local runner scripts
preserve the actual invocation options. Nothing was overwritten between trials.
`evidence/claim-dimension-results.json` preserves the successful period refs and
prompt/model/rule hashes, plus all trial statuses. A passed schema status in the
first trial must not be mistaken for successful semantic extraction.

Only a year-overlap review was done against nine previously normalized p97 global
observations: no 2019/2030 column among those nine, and three 2025 observations.
The latter are Scope 1+2, Scope 1 and Scope 2 totals, NOT automatically evidence of
project-level 30,000-ton savings. All bindings remain undetermined. Absence in these
nine observations is not document-wide absence; no numeric comparison or grade ran.

Four calls added $0.000982410. Shared ledger after: 86 calls,
$2.036561360 committed/reserved of $10, including two earlier unsettled calls.
No Bedrock/AWS actions, retries outside these explicit trials, or secret output.

## Validation

Failing-first tests cover exact period refs, unknown preservation, fabricated quotes,
missing decisions, prohibited grades, all-null review status and restricted period
role IDs. Targeted tests pass. Ruff lint/format, 146-source mypy, four-package build,
architecture and supply-chain gates pass. Final full suite: `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q` — 1,433 passed in 110.63s, two existing Starlette/AnyIO warnings. `uv run --no-sync python scripts/validate_package.py` — 711/711 documentation/contract checks passed.
Production E2E/AWS not_run. The next step is to evaluate candidate-role tagging for
Scope/unit/value and metric aliases, without broadening evidence acceptance.
