# TASK-013 — 주장 귀속 검증

Date: 2026-09-09. FR-013 / AT-013; approved pure-function acceptance path.
Outcome: assigned implementation and validation completed. No commit/push,
shared contract/API/database/dependency changes, real model calls, AWS mutation,
private customer processing or human approval substitution.

## Implementation and integration contract

`packages/proofops/application/evidence/binding.py` provides:

```python
context = ClaimContext(claim, dimensions)
state = accept_binding(
    context, source_ref, relation_tags,
    original=trusted_canonical_graph, tenant_id=authorized_tenant,
    rulepack=pinned_rulepack, element_id="P1",
)
# state: accepted | undetermined | rejected
```

- Reuses the existing rich `Claim`, `SourceRef`, `CanonicalDocumentGraph`,
  `RulePackSnapshot` and TASK-012 citation verifier. This binding-specific
  ClaimContext wraps the existing Claim; it does not change TASK-007's assurance
  ClaimContext or any shared DTO. Dimensions and relation tags map semantic roles
  to literal SourceRefs or null, never uncited strings, grades or labels.
- Checks tenant/document version/parse manifest/original hash identity and every
  cited literal span against the original parser candidate chain, coordinates and
  raw hash. An externally supplied verified flag cannot bypass those checks.
- Compares entity, metric, reporting period and supplied applicable product,
  material, facility, Scope and boundary axes. Each role is itself source-backed;
  a matching product citation from another row cannot supply the selected ratio.
  Missing/null roles remain undetermined. Known differences reject the binding.
- Atomic claim spans remain bounded. Numeric/target-year evidence requires the
  claim span or the same identified table with matching year column. Table
  identity includes parser run, physical page and native table ID. Invalid or
  missing row/column coordinates do not become accepted bindings. Same-row
  product anchors are supported; period anchors require the same column, and
  different-row column headers require an explicit table_parent edge.
- Reads element source scopes from the pinned rulepack. Matching global
  scope/method/assurance references may bind; global G1/G2/G3/G5/P1 numbers/years
  cannot bind. Unresolved nonnumeric explicit_link cases preserve GAP-004 rather
  than inventing approval. Binding acceptance does not establish assurance
  coverage, grant present, calculate grades/labels or establish legal compliance.
- No input/revision/report is changed. ClaimContext snapshots its dimension map.
  The pure result belongs beside the existing source/tag receipts and pinned
  graph/rulepack in a new caller-owned revision; model/prompt/rule hashes and
  replica remain in those immutable input envelopes, not discarded or replaced.

The upstream semantic tagger must supply all applicable axes and their correct
roles. This guard checks literal provenance and declared attribution, not natural
language role accuracy. Unresolved aliases and unproven merged/cross-page table
relationships are not inferred. No new fallback parser, model or adapter exists.

All fixtures are explicitly synthetic. Tests exercise real graph fusion, citation
verification, binding, rulepack policy, immutable retrieval packet construction
and concurrent calls. The retrieval integration uses the existing test-only
SyntheticSearch and an explicit synthetic token counter; it is not a live search
engine, production tokenizer or model result.

## Test-first and important review

1. `uv run pytest tests/acceptance/test_binding.py -q --tb=no`: exit 1,
   **37 failed in 0.44s**, because the assigned binding module did not exist.
2. `uv run pytest tests/acceptance/test_binding.py -q --tb=short`: first
   implementation exit 1, **1 failed / 36 passed in 0.80s**. G3 global numeric
   evidence incorrectly followed the unresolved explicit-link branch; added the
   direct-number restriction without changing its expected assertion.
3. `uv run pytest tests/acceptance/test_binding.py -q`: exit 0,
   **37 passed in 0.85s** after the correction.
4. Added coordinate, atomic-span and retrieval integration cases. Initial run:
   **6 failed / 40 passed in 1.04s**. Four failures exposed bool/negative table
   coordinates being accepted or misclassified; strict coordinate checks fixed
   them. Two fixture errors were corrected without relaxing assertions: the
   atomic-span fixture was made a paragraph (same-table direct evidence is
   explicitly allowed), and the retrieval fixture now keeps canonical kind and
   selected candidate kind consistent and uses a declared synthetic token counter.
   Final run for that set: **46 passed in 1.00s**.
5. Added same-column header, same-row product and wrong-year-column cases:
   **1 failed / 48 passed in 1.11s** exposed borrowing the period from another
   column in the same row. Fixed the shared attribution check to require period
   column equality; **49 passed in 1.12s**.
6. Added a shared-context concurrent acceptance/rejection test that also checks
   snapshotting a caller-owned dimension map: **50 passed in 1.12s**.

No tests were removed or weakened, no behavior was replaced with mocked outcomes,
and no other worker's files were modified. Critical/important self-review found
no remaining issue in this tested pure-function scope; full semantic extraction
accuracy is a separate evaluation gate.

## Exact verification commands and results

| Command | Actual result |
|---|---|
| `uv run pytest tests/acceptance/test_binding.py -q` | exit 0, 50 passed in 1.12s |
| `uv run ruff check packages/proofops/application/evidence/binding.py tests/acceptance/test_binding.py` | exit 0, All checks passed |
| `uv run ruff format --check packages/proofops/application/evidence/binding.py tests/acceptance/test_binding.py` | exit 0, 2 files already formatted |
| `uv run mypy packages/proofops/application/evidence/binding.py` | exit 0, no issues in 1 source file |
| `uv run python scripts/verify_architecture.py` | exit 0, all purity/DTO/ports/composition/contracts checks passed |
| `uv build --package proofops --out-dir /tmp/proofops-task-013-dist` | exit 0, sdist and wheel built |
| `git diff --check -- packages/proofops/application/evidence/binding.py tests/acceptance/test_binding.py` | exit 0; Ruff separately checks new untracked content |

Related unit/contract/integration/security regression:

```sh
uv run pytest tests/acceptance/test_binding.py tests/acceptance/test_retrieval.py tests/acceptance/test_citations.py tests/acceptance/test_claims.py tests/acceptance/test_rules.py tests/acceptance/test_numeric.py tests/acceptance/test_provenance.py tests/unit tests/contracts tests/integration tests/security -q
```

Exit 0: **390 passed, 2 warnings in 18.01s**. This run preceded the additional
pure concurrency test (49 binding cases at that point); all 50 binding cases were
then rerun successfully. Warnings are existing Starlette/httpx and AnyIO
DeprecationWarnings. No unrelated shared failure remains in that observed run.

Wheel-content verification:

```sh
uv run python -c 'import zipfile; from pathlib import Path; archive = zipfile.ZipFile(next(Path("/tmp/proofops-task-013-dist").glob("*.whl"))); assert "proofops/application/evidence/binding.py" in archive.namelist(); print("PASS: binding module included in wheel")'
```

Exit 0: `PASS: binding module included in wheel`.
Initial Ruff import/format/line-length findings were corrected in the two assigned
Python files; final lint, format and type checks above pass.

## Remaining gates and ownership

- **not_run**: live model/Bedrock, AWS/search-service integration, approved vision
  profiles, private/public customer document validation and model accuracy work.
  Human-only data/rights/legal/domain gates remain blocked/not_run as specified.
- **not_run**: browser/product E2E and claim GET route composition. AT-013 allows
  the pure function exercised here; API/storage/three-replicate integration
  remains with the coordinator and its assigned workers. No DB migration or
  rollback is needed for these additive internal functions.
- **not_run by this worker**: `python scripts/validate_package.py` as a top-level
  command, because it writes coordinator-owned evidence files. Existing package
  unit/contract tests were actually run; document validation is not represented
  as application testing.
- No new dependency or runtime I/O was introduced. Tenant/provenance/adversarial
  acceptance cases, the existing security suite and architecture checks provide
  the relevant security validation; no new network dependency audit was run.
