# Scope / unit / value candidate tagging — 2026-09-09

Extended the successful period-candidate approach in `evaluation/claim_dimensions.py`.
The local extractor enumerates literal Scope bundles, supported units and unit-bearing
amounts. The model selects only a candidate ID and one allowed role (scope, unit,
baseline_value, reported_value, target_value or unknown). It cannot create quote text.
Period and quantity validators share the existing exact-source dimension guard.
No production API/DB, graph/source-quality revision, binding approval or grade changed.

## Actual trial

One Upstage call over the same two LG Chem p24 targets produced five proposals:
- Goal sentence: Scope 1 및 Scope 2; unit tCO₂e; baseline_value 951만 tCO₂e.
- Performance sentence: unit 톤; reported_value 약 3만 톤.

Each result resolves to its own original sentence span. Approximation, scale and
literal units are preserved; 톤 is not rewritten to tCO₂e. The unstated performance
Scope, company/entity and metric dimensions remain unknown. No target amount was
inferred from the baseline. These are model-proposed roles with unverified source
quality and undetermined binding, not confirmed real-world outcomes.

`evidence/quantity-candidate-results.json` also provides a review-only combination
with the previous period tags: baseline 2019 / target 2030 for the goal and reporting
2025 for the performance sentence. Original packet hash, source ID and claim spans
must agree, and only disjoint populated fields are joined. Each field retains its
originating request ID. This does not change old claims/revisions and is not an
independent replica, consensus score or evidence acceptance.

Live artifacts: `.local/dimension-pilot/quantities/`; invocation script:
`.local/dimension-pilot/run_quantities.py`. Request/response/budget and original
prompt/model/rule hashes are retained. After rejecting unsupported partial Scope
ranges, the real candidate list was regenerated and matched the archived wire list
exactly; revalidation metadata is separate from the original call receipt.

## Limits and checks

The extractor deliberately covers explicit supported units (CO2/CO2e ton forms,
톤, energy units and percent), not arbitrary numeric text. Years, Scope labels and
8건 are not emitted as reported amounts. English words such as whole must not
create Wh units. Percentage points (%p / %포인트) and unsupported Scope ranges
must not become truncated percent/Scope candidates. Unsupported units, complex
amount syntax, repeated ambiguous quotes and multiple values for one field need
separate review; no unknown/absent substitution or guessed normalization occurs.
No metric alias resolution, entity/boundary match, numeric comparison or grade ran.
This remains a small development case, not a corpus accuracy benchmark.

Failing-first regressions cover Scope bundles, approximation, units, allowed-role
boundaries, word collisions, percentage points and unsupported partial ranges.
All five focused tests pass. Ruff lint/format, 146-source mypy, four-package builds,
architecture and supply-chain checks pass. Final full suite: `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q` — 1,436 passed in 110.39s, two existing Starlette/AnyIO warnings. `uv run --no-sync python scripts/validate_package.py` — 712/712 documentation/contract checks passed.
Deployed production E2E/AWS remain not_run.

Additional settled estimate $0.000205095. Shared ledger: 87 calls,
$2.036766455 committed/reserved of $10, including two earlier unsettled calls.
No Bedrock/AWS calls, no automatic retry, and no secret output.

Next: evaluate metric/entity candidate tagging and compare source-bound dimensions
against relevant table observations while retaining quality and boundary blockers.
