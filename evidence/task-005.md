# TASK-005 — numeric repair evidence

2026-09-09 KST. This record supersedes the earlier unaccepted TASK-005 completion claim. The bounded repair and own review pass local focused checks; coordinator acceptance and production approval remain separate.

## Scope and contract

Read AGENTS, Master/original v2, docs 26/27/28/31/19, TASK-005, the execution order, and existing normalization, claim discovery, SourceRef, source geometry, citation verification and confirmed-fact boundaries. Only `packages/proofops/domain/numeric.py`, `tests/acceptance/test_numeric.py`, and this evidence file were edited. No Git command, commit/push, dependency/lockfile change, application/API/schema edit, model/AWS call, customer processing, or delegation occurred.

The coordinator explicitly authorized the minimum accepted source-bound aggregation relation and structural claims/original-snapshot inputs via Orca question response in dispatch `ctx_546afb5f7474`. The coordinator also reviewed the implementation and authorized an additive internal exact-ratio result for recurring reductions and the accepted space-joined multi-reference quote invariant. No application import or I/O is added to Domain.

`check_numeric_consistency(observations, bindings, *, tenant_id, claims=(), original=None)` accepts existing internal records through structural protocols. The caller must load the trusted claim registry and canonical snapshot in an authorized run; caller/model JSON projections are not trusted originals. Existing callers still construct/call the interface, but missing verified context now fails closed. No HTTP/storage contract or migration is introduced.

- Binding now carries parse manifest, current reporting period, explicit baseline period for reduction, explicit absolute/intensity kind, accepted-binding state, and the exact numeric source span inside its actual registered claim. Comparison/sum periods must match; reductions require distinct explicitly ordered baseline/current periods. Metric, subject, Scope, Scope 2 basis, organizational boundary, canonical unit, and intensity denominator must match. Unknown quantity kind and intensity without its denominator are not comparable.
- Claim, observation and relation SourceRefs must be verified and located, and are checked against the original selected raw candidate, full raw hash, exact span, geometry, page, manifest, artifact and tenant chain. Candidate flags, arbitrary same-version claim references, unknown/unverified quality and malformed provenance cannot produce consistent. Observations retain field-to-source parent associations; raw values and source-bound units/scales must agree with their normalized Decimal values.
- `AggregationRelation` requires explicit `accepted` state and `disjoint_complete_components` semantics, exact target claim and ordered observation IDs, verified statement references and a SHA-256 of the complete binding with `aggregation=None`. That hash pins period, boundary, dimensions and claim/value sources. Acceptance is supplied by the upstream semantic binding boundary, never inferred/defaulted here. It means members are all disjoint leaf components of this target, excluding overlapping totals/subtotals. Missing, changed or unresolved relations return `not_comparable / aggregation_relation_unresolved` without a computed value. Renamed duplicate source cells are also blocked.
- Raw displayed decimal precision and the normalizer's source-backed scale determine intervals. Sum combines all actual input intervals; reduction evaluates exact endpoint ratios and rejects a baseline interval containing zero. Decimal parsing and finite Decimal output are exact; stdlib Fraction intermediates prevent division/interval rounding from depending on ambient Decimal precision, rounding or traps. No fixed tolerance or computed-output display interval is invented. Recurring quotients are still classified using exact rational intervals; `computed_value=None`, `reason=non_terminating_decimal`, and `exact_ratio=(numerator, denominator)` preserve their exact result without fabricated decimal precision.
- Results carry numeric statuses, original values and source references only, including selected observation and aggregation sources. They assign no grades/labels and do not mutate claims, tags, receipts, revisions, originals or reports. Unknown/conflict/unreadable states remain unresolved rather than absence.

## Test-first and own review

All source-quality confirmations and accepted semantic bindings in AT-005 are explicitly synthetic fixtures. Real graph fusion, normalization, synthetic claim extraction and citation verification run over those fixtures; no LLM or customer document is involved. The positive sum fixture includes an explicit source statement identifying the table data rows as all disjoint components, rather than treating ordinary matching rows as proof.

Existing public intent is retained: exact `0.1 + 0.2 = 0.3` now requires an explicit accepted aggregation relation; zero/missing baselines are not computable; `1.2` versus `1.24` accepts display rounding; dimension mismatch is not a numerical failure; foreign tenants and source-less bindings are rejected.

| Exact command / stage | Actual result |
|---|---|
| `uv run --no-sync pytest tests/acceptance/test_numeric.py -q` — initial behavioral regressions against original implementation | Exit 1: **3 failed, 8 passed in 0.36s**; unverified, unknown-quality and unsupported sum returned consistent |
| Same command — full new regression contract before implementation | Exit 1: **58 failed in 0.52s**; required aggregation/source-scope interface absent |
| Same command — first implementation | Exit 0: **58 passed in 0.31s** |
| Same command — own-review regressions before their fixes | Exit 1: **3 failed, 61 passed in 0.43s**; renamed duplicate cell, fabricated source scale, clipped first digit of a larger claim number |
| Same command — after those fixes | Exit 0: **64 passed in 0.47s** |
| Same command — explicit unknown/intensity-kind regressions before their fix | Exit 1: **2 failed, 64 passed in 0.33s**; explicit quantity kind absent |
| Same command — explicit quantity-kind implementation | Exit 0: **66 passed in 0.28s** |
| Same command — coordinator-review regressions before their fixes | Exit 1: **3 failed, 65 passed in 0.27s**; recurring reductions lacked an exact-ratio representation and space-joined multi-reference claims were rejected |
| Same command — final numeric check | Exit 0: **68 passed in 0.28s** |

Meaningful regressions include all comparison dimensions, cross-year sums, explicit reduction periods, missing intensity denominator, unverified/candidate/rejected/unlocated refs, forged same-version refs/hashes/spans, missing claim registry/original provenance, changed aggregation membership/target/hash/acceptance, unknown value-state preservation, scaled source intervals, accumulated sum rounding, reduction input intervals, false computed rounding tolerance, exact values exceeding 28 digits under ambient precision 4, normalized/raw tampering, and prohibition of an arbitrary 5% tolerance. Coordinator review added recurring reduction consistent/inconsistent and space-joined multi-reference cases; original numeric token boundaries are checked against the full source even if a claim ref ends inside a number. Tests were not deleted or weakened to pass; previous positive fixtures were upgraded to actually carry verified source and explicit semantic binding evidence.

## Verification

| Exact command | Actual result |
|---|---|
| `uv run --no-sync pytest tests/acceptance/test_numeric.py tests/acceptance/test_tables.py tests/acceptance/test_citations.py tests/acceptance/test_claims.py tests/acceptance/test_provenance.py -q` | Exit 0: **172 passed in 1.92s** |
| `uv run --no-sync pytest tests/contracts/test_package_contracts.py -q` | Exit 0: **29 passed, 2 existing Starlette/httpx/anyio deprecation warnings in 0.52s** |
| `uv run --no-sync pytest tests/integration/test_local_api_composition.py -q` | Exit 0: **1 passed, 2 same deprecation warnings in 0.36s** |
| `uv run --no-sync pytest tests/contracts/test_package_contracts.py tests/integration/test_local_api_composition.py -q` — final after coordinator review fixes | Exit 0: **30 passed, 2 same deprecation warnings in 0.83s** |
| `uv run --no-sync ruff check packages/proofops/domain/numeric.py tests/acceptance/test_numeric.py` | Exit 0: `All checks passed!` |
| `uv run --no-sync ruff format --check packages/proofops/domain/numeric.py tests/acceptance/test_numeric.py` | Exit 0: `2 files already formatted` |
| `uv run --no-sync mypy packages/proofops/domain/numeric.py` | Exit 0: `Success: no issues found in 1 source file` |
| `uv run --no-sync python -m compileall -q packages/proofops/domain/numeric.py` | Exit 0; syntax compilation only, not a wheel build |
| `uv run --no-sync python scripts/verify_architecture.py` | Exit 0: purity, DTO, ports, composition and fixed fixture checks all passed |
| `uv run --no-sync python -c 'import importlib.util; print("hatchling:", importlib.util.find_spec("hatchling") is not None)'` | Exit 0: `hatchling: False`; declared wheel backend is absent from the existing environment |

Intermediate lint caught line-length formatting and mypy caught two protocol/union typing issues; both were repaired before the final clean commands above. No full WIP test run or unrelated repair was performed. Security verification here consists of the adversarial numeric/provenance tests and the domain architecture boundary check, not a deployment penetration test.

## Explicit remaining boundaries

- Reported numeric spans currently use the binding's canonical unit. Raw observation scaling supports the accepted normalizer's `1` and explicit `천 ` → `1000` mapping. Scientific notation, other unit conversions, raw scaled claim-value conversion, and unrecognized field/unit source layouts remain unsupported and fail closed. Numeric spans must be whole original numeric tokens rather than substrings; ordinary sentence punctuation is kept separate from fractional display precision.
- Original source quality and semantic claim/aggregation acceptance are upstream responsibilities. This pure checker validates pinned records; it neither authorizes human acceptance nor decides that an arbitrary natural-language sentence proves non-overlap. The synthetic acceptance fixture is not human approval data or a production source-quality gate.
- Wheel build: **not_run** because the existing no-sync environment lacks its declared `hatchling` backend; no installation/sync was performed. UI E2E, full WIP suite, live model/AWS/deployment, real-corpus accuracy/performance and customer/legal/rights approvals: **not_run** in this bounded repair. No production or accuracy claim is made.
