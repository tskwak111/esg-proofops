# Reconciliation benchmark verification

Date: 2026-09-21 (Asia/Seoul)

Final coordinator replay: `real-benchmark-final.json` supersedes the v2 run below
after formatting the evaluator. It records the final evaluator hash and preserves
the same 9/9 original, 3/3 statement identity, 3/3 catalog identity and 372/372
expectation/source matches. Overall status remains `fail` solely because all
three candidate catalogs are truncated. The table below records the worker's
handoff snapshot, not the later formatting-only source hash.

## Delivered files

| File | SHA-256 |
|---|---|
| `evaluation/reconciliation_benchmark.py` | `72e99b7cb612a001e0f84954dfffb6b032435a915be773970fbcc803ef740945` |
| `tests/reconciliation/test_benchmark.py` | `09311799ea1fd2326e41e50c9a92309e2a51d6f1fb501ab69e1812da04226d16` |
| `docs/RECONCILIATION_EVALUATION.md` | `681b6b1ebed9e9f922b8fc54d4a361c49e8d21e82b9e5a7afc5cbb44ff6d2bab` |
| `evidence/reconciliation-completion/evaluation/real-benchmark-20260921-v2.json` | `ab637ebe29fa45a1d0f609f933c1fcff0fc2b2b2af23a7b77391591636bc77ef` |

## Verification results

Environment variables used for local test discovery only:

```text
PYTHONPATH=packages;apps/api/src;apps/worker/src;apps/agent/src
PYTHONUTF8=1 (full reconciliation suite)
```

Commands and results:

```text
uv run --no-sync pytest tests/reconciliation/test_benchmark.py -q
21 passed in 1.53s

uv run --no-sync ruff check evaluation/reconciliation_benchmark.py tests/reconciliation/test_benchmark.py
All checks passed!

uv run --no-sync mypy evaluation/reconciliation_benchmark.py
Success: no issues found in 1 source file

uv run --no-sync pytest tests/reconciliation -q
615 passed, 3 warnings in 95.72s
```

The full suite used `PYTHONUTF8=1`. The successful run emitted three pre-existing warnings:
one duplicate ZIP-member warning from an adversarial test and two dependency deprecation
warnings.

## Real-original run

Command (the output path did not previously exist):

```text
uv run --no-sync python -m evaluation.reconciliation_benchmark \
  --manifest .local/reconciliation-completion-benchmark.json \
  --output evidence/reconciliation-completion/evaluation/real-benchmark-20260921-v2.json
exit 1 (expected fail-closed result because every catalog declared truncation)
```

Observed objective results:

| Metric | Numerator | Denominator | Value |
|---|---:|---:|---:|
| Original artifact hash match | 9 | 9 | 1.0 |
| Original statement row identity match | 3 | 3 | 1.0 |
| Catalog/company identity match | 3 | 3 | 1.0 |
| Candidate expectation exact match | 372 | 372 | 1.0 |
| Candidate source verification | 372 | 372 | 1.0 |
| Whole-case pass | 0 | 3 | 0.0 |

The 372 expected rows comprise 10 Samsung development expectations, 226 Ottogi holdout
expectations, and 136 Dongsuh holdout expectations. All expectation/source checks passed.
All three cases failed only with `candidate_catalog_truncated_incomplete_search`, so these
results do not claim complete source discovery or recall.

## Covered behavior

- Exact original-byte SHA-256 checks and original-lineage binding.
- Exact candidate type, prepared artifact SHA-256, locator, and UTF-8 quote SHA-256 matching.
- Re-verification of prepared source bytes, locator, and quote with `FileSourceReader`.
- Fail-closed tamper behavior for prepared and original artifacts.
- Strict development/holdout overlap rejection by declared `company_id`.
- Binding of each eight-digit company ID to the catalog DART corporation code.
- Cross-split original-digest reuse rejection even under different company labels.
- Strict DART statement JSON row corporation/year/receipt checks against catalog identity.
- Malformed unhashable split/item/candidate-type values become `InputRejected`.
- Missing, empty, malformed, and duplicate expectation rejection.
- Explicit truncated-catalog incomplete-search failure.
- Zero-case metrics return `not_run`, null values, and zero denominators; overall status fails.
- Immutable output refusal and omission of source paths/quotes from reports.

## Limitations and not-run work

- The real manifest was authored by the coordinator. This worker verified its referenced local
  originals and candidates but did not independently establish issuer authenticity or author
  the expectations.
- Company disjointness is enforced only within the manifest's declared corpus. The harness
  cannot prove globally disjoint provenance or discover earlier exposure in unavailable data.
- Candidate relevance, evidence-search completeness/recall, normalization correctness beyond
  the pinned objective tuple, C1–C4 semantics, grades, labels, accounting interpretation,
  policies, and human review quality are not measured.
- No human gold labels were created or inferred, and no policy was approved.
- No cloud, DART, model, or other network call was made. Intel macOS was excluded and not run.

## Read-only source-audit review

`evaluation/reconciliation_source_audit.py` and its tests were reviewed without edits. Its
temporary-root reconstruction, `FileSourceReader` byte/locator replay, immutable output,
explicit truncation, and unapproved account-mapping boundary were sound; its focused result
was 10 passing tests plus clean Ruff and mypy checks. The review found that its original
`quote_sha256` used canonical JSON-string hashing rather than plain UTF-8 quote hashing and
that its report lacked an evaluator-code hash; the owning coordinator corrected both and
added a focused assertion after receiving the finding.
