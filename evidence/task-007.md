# TASK-007 — source-backed assurance extraction and scope matching

Date: 2026-09-09 KST. Assigned pure-function implementation and AT-007: **passed**.
Real model, customer data, AWS, production approval: **not_run / blocked external gates**.

## Scope and actual behavior

Changed only `packages/proofops/application/assurance.py`,
`tests/acceptance/test_assurance.py`, and this evidence file. No shared API/schema,
DB, migration, dependency, lockfile, Git commit, push or cloud changes.
Read AGENTS, Master, original v2 assurance sections, docs 26/27/28/31/19,
TASK-007 / FR-007 / AT-007, the unchanged AssuranceMatch JSONSchema and existing
TASK-002 SourceRef, TASK-003 rich graph, and TASK-029 model invocation boundaries.

`extract_assurance(graph, source_refs, binding, *, tagged_fields, tenant_id,
statement_id, model_sha256, prompt_sha256, replicate_id)` consumes the trusted
internal CanonicalDocumentGraph and source-span field tags. Each field value is
extracted from its original cited substring, not an arbitrary model string.
`source_refs` bounds the selected opinion; `tagged_fields` maps field names to
SourceRefs within it. The function does not invoke or emulate a model. The
upstream opinion selection and semantic field-role tagging must come from human
review or an evaluated, approved extraction pipeline; string presence alone is
not a claim of semantic tagging accuracy.

It structures provider, raw standard, level, reporting period, entities,
facilities, covered metrics, dimension-specific exclusions and uninterpreted
exclusion text. Literal standard names are retained; no canonical standard,
clause, legal fact or model identifier is invented. It verifies tenant/version,
manifest, source ID, physical page, printed label, bbox, raw-text SHA-256,
Unicode code-point offsets and exact quote against preserved native candidates.
A caller-supplied public `verification_state=verified` cannot override rich-graph
quality. Unverified/conflicted/unreadable/unlocated sources remain unresolved.
Tags outside the selected statement, forged refs, empty source sets, and model
coverage/grade/label fields are rejected.

`match_assurance(statement, claim_context)` compares one opinion to one claim.
Verified matching metric, year and both entity/facility boundary are required
for covered, along with identified provider, standard and limited/reasonable
level. Same provider never grants coverage to another year, entity, facility or
metric. A claim spanning an uncovered facility is not_covered. Verified explicit
exclusions override inclusion; uninterpreted exclusions and unresolved source
parts block coverage. Missing statements/information remain undetermined.
Opinions remain separate, so reasonable assurance at another facility cannot
promote a limited opinion covering this claim.

Immutable statement snapshots retain source refs and field spans, original graph
and source hashes, model binding, model/prompt hashes, replica ID and explicit
synthetic provenance. Matches retain statement/claim linkage, semantic statement
hash, rule-policy hash and reasons. `AssuranceMatch.to_dict()` explicitly emits
only the existing v1 fields; the rich envelope must be persisted alongside it.
No previous tag, decision or report revision is overwritten by these functions.

## Test-first and exact verification record

Initial command:

```sh
uv run pytest tests/acceptance/test_assurance.py -q
```

Exit **1**, **36 failed in 0.15s**, because `proofops.application.assurance`
did not exist. After minimal extraction/matching implementation the same command
exited **0**, **36 passed in 0.08s**.

Added a regression for dropping source refs and caller-list aliasing before its
fix:

```sh
uv run --no-sync pytest tests/acceptance/test_assurance.py -q
```

Exit **1**, **1 failed, 42 passed in 0.09s**: a statement could be replaced with
an empty source set. Added invariant validation and defensive tuple snapshots.
The same command then exited **0**, **43 passed in 0.08s**.

Initial lint/type runs found import ordering/line length and two mypy errors from
heterogeneous dictionary expansion into the statement constructor. These were
fixed with explicit constructor arguments and formatting; tests were not weakened.
Final targeted commands:

```sh
uv run pytest tests/acceptance/test_assurance.py -q
uv run --no-sync ruff check packages/proofops/application/assurance.py tests/acceptance/test_assurance.py
uv run --no-sync ruff format --check packages/proofops/application/assurance.py tests/acceptance/test_assurance.py
uv run --no-sync mypy packages/proofops/application/assurance.py
```

All exit **0**: **43 passed in 0.12s**; `All checks passed!`;
`2 files already formatted`; `Success: no issues found in 1 source file`.
AT-007 also validates a real match result against the fixed JSONSchema with UUID
format checking, without mocking the matcher, graph fusion, or source validator.

```sh
uv run --no-sync pytest tests/acceptance/test_assurance.py tests/acceptance/test_parsing.py tests/acceptance/test_provenance.py tests/acceptance/test_rules.py tests/acceptance/test_preflight.py tests/acceptance/test_auth.py tests/unit tests/contracts tests/integration -q
```

Exit **0**, **289 passed, 2 warnings in 9.72s**. This includes actual local parser
execution, coordinate provenance, rules, model preflight/consent and tenant
security, unit, fixed contracts, and existing local API/run integration. Warnings
are existing Starlette/httpx and AnyIO deprecations. The later test-only refinement
asserts the exact saved provider substring offsets and was included in the final
43-case targeted run above.

```sh
uv run --no-sync python scripts/verify_architecture.py
uv build --package proofops --out-dir /tmp/task007-build
```

Both exit **0**: all architecture checks passed; sdist and wheel successfully
built outside the repository. No new dependency was added. Architecture and
contract/package validation are not represented as product accuracy testing.

## Important review and remaining limits

- Reviewed critical paths for source-less coverage, tenant/version crossover,
  source spoofing, unresolved-to-absence conversion, highest-level promotion,
  mutable snapshots and model-generated grades. Both the source-less snapshot defect and ambiguous scope cross-product
  found during review have failing-then-passing regressions. No remaining known
  critical issue was identified within the exercised pure-function scope.
- Synthetic fixtures explicitly mark both ModelBinding and parser candidates;
  positive fixtures explicitly simulate human-verified source quality. They are
  not real report/model accuracy evidence. No synthetic adapter was added to a
  production composition.
- Matching currently uses exact NFC-normalized names and explicit four-digit
  years. Uninterpreted periods such as `FY24` stay unknown. Alias resolution,
  general date interval parsing, corporate hierarchy inference and arbitrary
  prose-to-field extraction are not implemented or claimed. No fuzzy comparison
  broadens a boundary. Non-GHG metrics are supported as exact strings without
  imposing a GHG Scope ontology.
- Upstream tags must describe one coherent coverage scope. Multiple values in
  two or more of metric/entity/facility axes now explicitly produce unresolved
  scope_group and undetermined, preventing invented Cartesian coverage. If an
  opinion contains different metric/site/level groups, provide separately scoped
  extractions; this module does not infer relational coverage from prose/tables.
- Shared `GET /v1/runs/{run_id}/assurance` wiring, run retrieval/authentication and
  durable revision persistence remain coordinator/integration work. AT-007
  explicitly permits the corresponding pure-function invocation; no endpoint
  completion is claimed. No DB/API contract change or migration is required by
  this additive application implementation.
- Browser/product assurance E2E: **not_run** (HTTP/UI integration outside assigned
  files). Real assurance-model inference and independent report evaluation:
  **not_run** (approved runtime/model and human evaluation gates). Actual AWS,
  cloud isolation/load, customer data processing, rights/legal approval and
  production security review: **not_run/blocked**. No gate is bypassed and no
  production-complete, legal assurance or accuracy percentage is claimed.

## Final important-review correction

Added `test_multiple_metric_site_groups_cannot_form_invented_cross_product` before
its fix. `uv run --no-sync pytest tests/acceptance/test_assurance.py -q` exited
**1**, **1 failed, 43 passed in 0.11s**, because two separate metric/site lists
incorrectly yielded covered for their inferred cross-product. The extraction now
marks multiple unlinked scope axes unresolved, and matching gives that ambiguity
precedence over both coverage and exclusion. The policy identity includes this
behavior. After the fix the same command exited **0**, **44 passed in 0.09s**.

Reran the exact Ruff check, Ruff format check and mypy commands above: all exit
**0**, all checks passed, two files formatted, no type issues in one source file.
Reran the exact architecture and package-build commands above: both exit **0**.
Reran the exact combined acceptance/unit/contract/integration command above:
exit **0**, **291 passed, 2 warnings in 10.10s** on the current shared workspace
(the parallel workspace gained another test in addition to the new AT-007 case).
The same two existing dependency deprecation warnings remain.

An initial documentation-only update attempted bare `python`, which is not on
this shell PATH (exit 127); it was rerun successfully with `uv run --no-sync python`.
Final contract-named invocation `uv run pytest tests/acceptance/test_assurance.py -q`
also exited **0**, **44 passed in 0.07s** after the evidence update.


## Coordinator check

`uv run --no-sync pytest -q tests/acceptance/test_assurance.py` exited 0: **44 passed**. Coordinator inspected source-binding/uncertainty boundaries and ran targeted Ruff and mypy across these ingest/application modules: both exited 0. HTTP/worker integration and real corpus/model evaluation remain separately tracked.
