# TASK-014 — 일반 사다리·라벨

Status: implemented and locally verified; no production or end-to-end PDF accuracy claim.

## Scope and behavior

- Added `domain/rules/engine.py` with frozen `ConfirmedFact`, `ConfirmedTags`, `RuleContext`, `Decision`, and `evaluate(tags, context, RulePackSnapshot)`; track modules map primitive facts to G/P/M rubric elements. The package initializer was authorized in coordinator guidance.
- Reuses TASK-000 `SourceRef`, `ElementState`, grade-to-label mapping and TASK-025 immutable `RulePackSnapshot.file_content` / canonical JSON. Domain imports only stdlib and other Domain modules; no new dependency, API/DB migration, shared contract edit, commit or push.
- Executes the actual pinned YAML branches, choosing the highest matching explicit grade while retaining explicit caps. Goal no-year exception is derived from target metric AND transition plan. Performance E3 requires method AND assurance with normalized `covered` status. Goal scope and organizational boundary remain distinct; performance uses its own calculation boundary.
- Present requires citation/binding attestations and located verified same-document SourceRefs from the same tenant. Numeric/year evidence cannot use global scopes. Absent requires an explicit verified search-coverage attestation. These are the **confirmed internal input boundary**: upstream citation/binding/numeric-check tasks must produce attestations after checking real artifacts; this evaluator does not claim to perform PDF verification itself.
- Missing facts, unknown/conflict and unapproved not-applicable facts remain unresolved. The evaluator examines possible Boolean completions only to determine grade influence; it never writes those completions into tags or treats them as observed absences. Grade-affecting uncertainty blocks grade/label; irrelevant uncertainty is retained and requests review.
- Additional P6/M4/triggered conditional requirements remain separate from the ladder candidate; missing effects use GAP-003 and unresolved evidence stays blocked. Conditional exclusions only derive from an explicitly absent trigger with search coverage. General industrial N/A is not inferred.
- Explicit original §7 goal example yields IMPL; other incomplete sublabels remain null with GAP-005. Safe-harbor, superlative and product-variant paths remain blocked for their dedicated TASK-015/016 integration. Advertising/legal applicability is rejected here.
- The semantic hash binds canonical confirmed inputs including source geometry/versions, ordered replicate hashes, model/prompt hashes, packet/tag revision, context, pinned pack hash, engine version and result. Facts are sorted, revisions frozen, and no system clock, actor or timestamp is introduced.
- `Decision.to_api_dict()` matches the existing v1 schema and excludes internal candidates, unresolved/excluded arrays and basis metadata. Internal basis references preserve the YAML's unverified status and null clause numbers.

## Test-first evidence

1. `uv run pytest tests/acceptance/test_rules.py -q` — exit 1, **38 failed**, all because `proofops.domain.rules.engine` did not yet exist. Tests import inside test execution rather than stopping collection.
2. After initial implementation, the same command — exit 0, **38 passed**.
3. Added pack-order, omitted-fact, independent-path and import checks: `uv run --no-sync pytest tests/acceptance/test_rules.py -q --tb=short` — exit 1, **1 failed, 43 passed**. Reversing the actual YAML branch list incorrectly selected E1 instead of E3; first-match selection was the root cause.
4. Added original §7 sublabel case: same command — exit 1, **2 failed, 43 passed**. Fixed common branch selection to choose the highest explicit grade and added only the exact source example's sublabel.
5. Added mutable-input and retired-pack guards: same command — exit 1, **2 failed, 45 passed**. Enforced scalar/Boolean inputs and rejected retired pack evaluation. After fixes: **47 passed**.

No tests were deleted, relaxed, mocked or replaced with expected-result adapters. Synthetic fixtures explicitly label source text as synthetic and set `local_synthetic=True`; real repository YAML is loaded and validated before snapshot construction.

## Final verification commands and results

| Command | Result |
|---|---|
| `uv run --no-sync ruff check packages/proofops/domain/rules tests/acceptance/test_rules.py` | exit 0; All checks passed |
| `uv run --no-sync ruff format --check packages/proofops/domain/rules tests/acceptance/test_rules.py` | exit 0; 6 files already formatted |
| `uv run --no-sync mypy packages/proofops/domain/rules` | exit 0; no issues in 5 source files |
| `uv run --no-sync pytest tests/acceptance/test_rules.py -q` | exit 0; 47 passed in 1.04s |
| `uv run --no-sync pytest tests/acceptance/test_rules.py tests/acceptance/test_rulepacks.py tests/contracts/test_package_contracts.py tests/unit -q` | exit 0; 131 passed, 1 skipped, 1 warning in 2.23s |
| `uv run --no-sync pytest tests/unit -q -rs` | exit 0; 17 passed, 1 skipped in 0.80s; skip: `test_legacy_characterization.py:193`, `not_run: set PROOFOPS_LEGACY_CHECKOUT to a fresh detached checkout` |
| `uv build --package proofops --wheel --out-dir /tmp/proofops-task014-dist` | exit 0; built `proofops-0.0.0-py3-none-any.whl` |

Built-wheel isolation check (exit 0, `Built wheel imports pure evaluator successfully`):

```sh
uv run --no-sync python -I -c 'import sys; sys.path.insert(0, "/tmp/proofops-task014-dist/proofops-0.0.0-py3-none-any.whl"); from proofops.domain.rules.engine import evaluate; assert not any(n.startswith(("proofops.application", "proofops.adapters", "boto3")) for n in sys.modules); print("Built wheel imports pure evaluator successfully")'
```

The integration checks exercise YAML validation → frozen snapshot → real evaluator → fixed JSONSchema projection. Security checks include tenant/document/packet/ontology mismatches, source-less or unverified present, wrong source scope, absence without search coverage, and immutable revisions. The broader suite warning is Starlette TestClient's existing deprecated AnyIO `BlockingPortal` alias, not a rules-engine failure. Other workers concurrently own unrelated files; their changes were not edited or repaired here.

Initial lint reported 7 formatting/import issues; `ruff check --fix` and `ruff format` resolved them before the final clean run. A shell edit invocation using bare `python` failed with `command not found`; no edit occurred, and it was rerun successfully using `uv run --no-sync python`.

## Important review and remaining gates

Self-review found and fixed branch-order dependence, missing exact-source sublabel, mutable normalized input and retired-demo acceptance. No remaining critical/important finding identified within the general-ladder scope.

- `not_run`: claim-detail HTTP endpoint integration, browser E2E, real parser/citation/numeric/assurance pipeline, real product model calls, AWS and deployment/security-infrastructure tests. These are separate tasks/approval scopes; only the fixed Decision projection and pure evaluator are delivered here.
- `blocked`: human clause/legal/applicability/domain-gap approval; no invented clause, industry mapping, rule gap approval or legal-effect claim.
- `not_run`: external legacy-checkout characterization as detailed in pytest's explicit skip reason.
- `python scripts/validate_package.py` was not separately run because it writes shared package-validation evidence owned by the coordinator; package/unit contract checks above ran. Documentation validation is not represented as application testing.
- The 12-fact evaluation size guard bounds enumeration; current ladder uses at most 8 primitives. If the ontology expands, replace enumeration with symbolic evaluation after contract approval.
