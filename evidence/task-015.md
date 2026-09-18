# TASK-015 — 최상급·제품·범주형 특칙

Status: implemented and locally verified against synthetic confirmed inputs; no production/PDF accuracy claim.

## Implementation and ownership

- Added `packages/proofops/domain/rules/exceptions.py` and `tests/acceptance/test_exceptions.py`. Coordinator explicitly approved exclusive `engine.py` exception wiring through Orca ask: “Approved: you exclusively own engine.py exception wiring during TASK015; preserve public contracts and run general-ladder regression.” No public DTO, API, DB, config, lockfile or dependency changes; no commit/push.
- `apply_source_exceptions(tags, context, pack)` returns frozen override/cap/gap, unresolved primitive names, applied rule IDs and ordinal qualification. It reuses the general evaluator's identity/source/pack validation; standalone callers cannot bypass that boundary. Existing `evaluate` applies results before label assignment and semantic hashing. Engine version is `explicit-ladders-exceptions-2`.
- Source: original v2 §4.4; priority docs 00/26/27/28/31/19, TASK-015/FR-015/AT-015, existing rubric snapshots and v1 Decision/LLM schemas. The original domain is retained, with unverified clause references still null.
- Superlative E0 requires a confirmed `has_superlative` fact whose original source quote contains `superlative_quote`, plus verified-search `comparison_basis=absent` AND `external_verification=absent`. `comparison_basis` means the full comparison group/unit/source condition, not merely the ladder's `comparison_baseline` year. One present operand prevents the override. Missing/unknown/conflict/unapproved N/A operands or an unverified superlative quote cannot be treated as absence. Explicit unknown superlative tagging blocks silent general-ladder fallback. Safe-harbor overlap preserves GAP-001/GAP-006 and null public grade/label.
- Management product variants use the pinned `direct_product_material_ratio_or_target` binding fact. Verified absence caps the general ladder at E1, including when unknown boundary/verification could only change grades above that cap. Present direct quantity retains GAP-007 for the still-unapproved product/general-boundary combination; unknown/conflict remains blocked evidence. A product flag on another track remains GAP-007. Model/material specificity never automatically grants E2.
- Performance facts containing `categorical_ordinal` select categorical P1 qualification. Both its nonempty ordinal value and a nonempty named `certification_provider` must have verified, accepted same-document evidence; that qualification supplies value/unit equivalence only. A verified absent component makes the conjunction unqualified; an unresolved conjunction stays unresolved. Raw facts are never rewritten. Existing quantitative claims without the categorical primitive keep their existing P1 path. This is a confirmed-input convention, not raw LLM output or an automatic text classifier. Provider naming does not grant covered assurance or comparison, and cannot alone produce E3.
- Global numeric/product evidence, wrong tenant/document, unreadable/candidate source, source-less present and rejected bindings remain rejected. `external_verification` explicitly permits same-document global-bound evidence across tracks as allowed by the master contract. Direct product binding is an upstream attestation of the particular claim/product/material, not a same-page string-match inference.
- All raw facts, SourceRefs, geometry, document/tag revisions, model/prompt/replica/packet hashes and pinned pack hash remain in the unchanged immutable input/hash path. No existing revision is overwritten. API projection still validates against the unchanged v1 Decision schema. Rule IDs and unverified §4.4 basis identify exception effects.

## Test-first record

| Command | Observed result |
|---|---|
| `uv run pytest tests/acceptance/test_exceptions.py -q --tb=short` before implementation | exit 1; 28 failed, 16 passed in 0.87s. Missing exception module and blocked/incorrect existing engine behavior caused expected failures; pre-existing source guards already passed. |
| `uv run --no-sync pytest tests/acceptance/test_exceptions.py tests/acceptance/test_rules.py -q --tb=short` after initial implementation | exit 0; 91 passed in 2.08s. |
| `uv run --no-sync pytest tests/acceptance/test_exceptions.py -q --tb=short` after adding review regressions | exit 1; 2 failed, 45 passed in 1.17s. Product cap failed to resolve uncertainty only above E1; explicit unknown superlative with null quote silently entered general grading. |
| `uv run --no-sync pytest tests/acceptance/test_exceptions.py tests/acceptance/test_rules.py -q` after fixes | exit 0; 94 passed in 2.12s. |

The two review issues were corrected at their shared decision points: apply caps to possible ladder grades before checking grade ambiguity, and retain explicit unresolved superlative triggering. No test was deleted, weakened or mocked. Existing synthetic source/pack builders are reused and `local_synthetic=True` is required for draft rulepacks. There is no new adapter and no claim that these synthetic attestations came from actual PDFs/models.

Initial lint found 9 formatting/import issues. `uv run --no-sync ruff check --fix packages/proofops/domain/rules/engine.py packages/proofops/domain/rules/exceptions.py tests/acceptance/test_exceptions.py` fixed the import issue and reported 8 remaining line-length issues; `uv run --no-sync ruff format packages/proofops/domain/rules/engine.py packages/proofops/domain/rules/exceptions.py tests/acceptance/test_exceptions.py` formatted all three files. Final checks below passed.

## Final verification

| Exact command | Result |
|---|---|
| `uv run pytest tests/acceptance/test_exceptions.py -q` | exit 0; 47 passed. |
| `uv run --no-sync ruff check packages/proofops/domain/rules tests/acceptance/test_exceptions.py` | exit 0; All checks passed. |
| `uv run --no-sync ruff format --check packages/proofops/domain/rules/engine.py packages/proofops/domain/rules/exceptions.py tests/acceptance/test_exceptions.py` | exit 0; 3 files already formatted. |
| `uv run --no-sync mypy packages/proofops/domain/rules` | exit 0; no issues in 6 source files. |
| `uv run --no-sync pytest tests/acceptance/test_exceptions.py tests/acceptance/test_rules.py tests/acceptance/test_rulepacks.py tests/contracts/test_package_contracts.py tests/unit -q -rs` | exit 0; 177 passed, 2 warnings in 3.63s. |
| `uv build --package proofops --wheel --out-dir /tmp/proofops-task015-dist` | exit 0; built `proofops-0.0.0-py3-none-any.whl`. |
| `git diff --check -- packages/proofops/domain/rules/engine.py packages/proofops/domain/rules/exceptions.py tests/acceptance/test_exceptions.py` | exit 0; clean. |

Built-wheel isolation/import check — exit 0, `Built wheel imports pure engine and exceptions successfully`:

```sh
uv run --no-sync python -I -c 'import sys; sys.path.insert(0, "/tmp/proofops-task015-dist/proofops-0.0.0-py3-none-any.whl"); from proofops.domain.rules.exceptions import apply_source_exceptions; from proofops.domain.rules.engine import evaluate; assert not any(n.startswith(("proofops.application", "proofops.adapters", "boto3", "httpx", "scripts", "legacy")) for n in sys.modules); print("Built wheel imports pure engine and exceptions successfully")'
```

Integration here is real repository YAML → validated frozen snapshot → shared confirmed-source checks → exceptions → general evaluator → existing JSONSchema projection. Security checks exercise wrong identity/source scope, missing source, unreadability and rejected product binding; frozen revisions and reproducible hashes are asserted. Two warnings come from the existing Starlette TestClient httpx/AnyIO deprecations. Concurrent workers' unrelated files were neither changed nor repaired.

## Important review and remaining gates

No remaining critical/important issue identified within the delivered confirmed-input exception scope. The important input conventions above must be retained by future tagging/binding integration; raw LLM tags must never be passed as confirmed facts.

- `blocked`: product upper-grade/general-boundary mapping GAP-007, safe-harbor grade/priority mappings GAP-001/GAP-006, full sublabel mappings GAP-005, clause/legal/rights approvals. No approval was inferred or domain policy invented.
- `not_run`: claim-detail HTTP endpoint delivery, browser E2E, actual PDF parsing/citation/product-binding pipeline, real product model calls, AWS changes/tests and deployment security infrastructure. These are separate task/approval scopes; the existing Decision projection was exercised locally.
- `not_run`: separate `python scripts/validate_package.py`; it writes shared coordinator-owned evidence and checks documentation/contracts, not the application. Relevant executable contract/unit tests ran above.
- No public API/DB change or migration is required. Rollback of the exception module/engine wiring restores the earlier conservative special-path block; already saved decisions remain immutable and subsequent scoring creates new revisions.
