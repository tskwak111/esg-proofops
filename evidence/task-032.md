# TASK-032 verification evidence

Date: 2026-09-09
Scope: local synthetic dataset records and fixed prediction artifacts only.

## Implemented

- `ElementFact` accepts only strict booleans, including `False` predictions. `GoldDataset`
  separately rejects positive gold facts whose source binding is not verified, so an invalid
  prediction is scored as an exact-tuple false positive and false negative rather than dropped.
- Gold grade/label pairs may remain `None` for unresolved rule gaps. Overall grade/label metrics
  exclude unresolved gold but count missing predictions as wrong; selective metrics additionally
  exclude pending predictions and carry their scored denominators.
- `EvaluationResult.ordinal_confusion` is an immutable E0-E3 matrix indexed by gold grade then
  predicted grade. Automatic coverage still uses all gold claims as its denominator.
- `verify_split` supports `development` and returns immutable verified item assignments.
  `evaluate_dataset(..., *, split_manifest=...)` re-verifies that manifest, requires exact gold
  membership for the evaluated split, and rejects prediction element claim IDs outside the fixed
  gold dataset.
- Non-provided claim, parsing, retrieval, and assurance stage metrics are emitted with
  `status=not_run`, `value=null`, and denominator `0`; no upstream performance is inferred.
- Existing duplicate, tenant, review-to-fewshot, company overlap, deterministic label, and
  conflicting element assignment guards remain active.

## TDD evidence

1. Baseline: `uv run pytest tests/acceptance/test_evaluation.py -q`
   - Exit 0: `7 passed in 0.01s`.
2. After adding the acceptance cases, before production changes:
   `uv run pytest tests/acceptance/test_evaluation.py -q`
   - Exit 1: `9 failed, 3 passed in 0.05s`; failures matched missing development support and
     manifest argument, rejected `False` prediction binding, rejected unresolved gold, and absent
     selective/ordinal/not-run outputs.
3. After the minimum implementation: `uv run pytest tests/acceptance/test_evaluation.py -q`
   - Initial exit 1: `1 failed, 11 passed in 0.02s`; this exposed that the existing overall
     grade/label metrics had been changed to selective semantics.
   - The implementation was corrected to preserve overall metrics and add separate selective
     metrics.
4. Focused rule-gap check:
   `uv run pytest tests/acceptance/test_evaluation.py::test_pending_gold_and_predictions_are_excluded_from_selective_scores -q`
   - Exit 0: `1 passed in 0.02s`.

## Final scoped verification

- `uv run pytest tests/acceptance/test_evaluation.py -q`
  - Exit 0: `12 passed in 0.01s`.
- `uv run ruff check evaluation/metrics/elements.py evaluation/metrics/pipeline.py evaluation/splits/company_split.py tests/acceptance/test_evaluation.py`
  - Exit 0: `All checks passed!`.
- `uv run mypy evaluation/metrics/elements.py evaluation/metrics/pipeline.py evaluation/splits/company_split.py`
  - Exit 0: `Success: no issues found in 3 source files`.

Before formatting, the same scoped Ruff command reported five E501 findings in the expanded
acceptance test; `uv run ruff format ...` reformatted two owned files, after which the final Ruff
run above passed. Human gold collection/adjudication, real model calls, AWS tests, real PDF parsing,
and upstream performance measurements were `not_run`.
# Coordinator acceptance

The 12 repaired metric/split cases passed independently. One additional regression
first failed because mutable nested grade/label arrays changed a frozen gold
snapshot after construction. The evaluator now freezes inner pairs and requires
an explicit grade/label entry (nullable) for every gold element claim, preventing
an omitted unresolved claim from shrinking the automatic-coverage denominator.
`uv run pytest tests/acceptance/test_evaluation.py -q` passed 13 tests; scoped Ruff
and mypy passed for the three evaluation source files. No accuracy claim follows
from these synthetic fixed-prediction checks. CLI/persistent API integration is
separate task task_3b07c4357ff7.
