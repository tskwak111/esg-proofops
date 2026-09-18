# Atomic extraction of a two-measurement sentence — 2026-09-10

Reused `extract_selected`, `selected_targets`, the pinned LG Chem section map and
original graph. Selected only p25 source 9472aedb-8736-5b50-896e-754c044f557d,
normalized range 129–214: domestic renewable energy procurement (약 93GWh) and
the associated carbon reduction effect (약 4만 톤). The whole paragraph was
available as interpretation context, while extraction was restricted to this
target. No extraction prompt or source/grade rule was changed.

## Actual result

One Upstage call returned exactly the original compound sentence as one span.
Source/schema validation passed and text coverage was full, but the two
measurements remain together. This is not successful decomposition or proven
atomicity. There was no subsequent semantic tagging call on the unchanged span.

The first clause explicitly supplies 국내 사업장; the second refers back through
이를 통해. Splitting requires retaining that relationship without silently
inventing an entity, year or boundary in a new quote. The extractor prompt permits
keeping a compound quote if splitting loses qualifiers, but this response gives
no explanation establishing why the model did not split. No automatic scope
inheritance, numeric binding, evidence acceptance, revision or grade was created.

## Replay and checks

`ReplayClient` replayed the exact archived model request with no network fallback.
The replay again returned one identical span. JSON-canonical comparison confirmed
unchanged SourceRefs and the original request hash/reference. Local quantity
extraction found both amounts. `evidence/atomic-expanded-review.json` explicitly
records full text coverage and unresolved atomic decomposition as separate facts.

`uv run --no-sync pytest -q tests/integration/test_atomic_pilot.py tests/acceptance/test_claims.py`
— 23 passed in 1.15s. The exact replay and verification commands are under
`.local/atomic-expanded/` (`replay.py`, `verify.py`). The first post-replay check
compared in-memory tuples with JSON lists; comparing canonical serialized refs
corrected that verification-only mismatch without changing source data or code.
No application code changed; full build/E2E/cloud checks were not rerun.

Original discovery, source selection and call receipts are in
`evidence/atomic-expanded-results.json`; original request/response are under
`.local/atomic-expanded/live/`. Prompt/model/rule, section-map, application-packet
and wire-packet hashes remain preserved. The new source remains unverified.

One call added $0.000191070. Ledger: 100 calls, $2.040014315 committed/reserved
of $10, including two earlier unsettled calls. No retry, Bedrock/AWS action or
credential output. Further work must handle multiple assertions and shared
context explicitly; neither text coverage nor this single call establishes
end-to-end claim/evidence accuracy.

`uv run --no-sync python scripts/validate_package.py` — 726/726 documentation and
contract checks passed, separately from application tests.
