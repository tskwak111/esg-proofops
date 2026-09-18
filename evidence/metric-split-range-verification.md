# Real-source split audit and numeric-range repair — 2026-09-10

Scanned parsed E-section paragraphs (physical pages 16–49) of the pinned LG Chem
report for unit-bearing amounts followed by `의`. Eleven pattern hits appeared
on p24, p25, p26 and p46. These are selected diagnostic phrases, not eleven new
model extractions, independent claims or a representative corpus benchmark.
The repeated p24/p26 text remains two source locations; source quality is unverified.

## Defect and repair

The shared `quantity_candidates` regex found the endpoint `50%` inside `20~50%`.
It similarly found `35%` inside `20~35%`. Existing literal quote verification alone
could not catch a model-selected phrase starting at that endpoint, because the
substring does exist in the source.

The common extractor now suppresses individual endpoints of unsupported numeric
ranges, including tilde and dash variants, with optional units on both endpoints.
Ordinary signed values such as -5% remain candidates. The metric splitter also
requires its prefix amount to match a complete candidate in the original block,
not merely inside the proposed metric quote. This also blocks a quote cutting
into a larger original number. Range interpretation is not invented: these
amounts remain unresolved rather than becoming a single value.

Failing-first regressions reproduced both the shared extractor defect and the
metric-substring bypass. Six range spellings/forms plus a signed-value control
are covered; all 21 focused dimension tests pass after the fix.

## Expanded real-source evaluation

Coordinator-selected source phrases exercise literal splitting for emissions,
renewable energy, carbon reduction effects and industrial water. Input origin
is explicitly recorded in `evidence/metric-split-real-cases.json`; neither model
recall nor semantic precision is scored. Expected future reductions are not
converted into achieved reported values, and tonnes are not rewritten to CO2e.
Original refs, document identity, packet hashes and local rule hash are preserved.

The original first audit expectation wrongly treated `35%` as standalone; reading
the full p26 paragraph showed `약 20~35%`, so its diagnostic expectation was
corrected to unresolved. The implementation already rejected it. This was a
correction to a newly authored audit expectation, not a weakened regression.

No new model calls occurred. The cumulative model ledger remains 98 calls and
$2.039563535 committed/reserved of $10, including two earlier unsettled calls.
No API/DB, dependency, canonical metric policy, source approval or grade changed.

## Verification

Actual-source runner: `.local/metric-audit/replay.py`; scan and execution logs are
in the same directory. Source references are checked against the pinned graph;
the original PDF layout was not visually re-adjudicated in this turn.
The completed replay produced 9 local split candidates and rejected 2 truncated
range endpoints. All 11 retained undetermined bindings and unknown reported values.
Ruff lint/format passed (234 files), mypy passed (146 source files), four-package
build, architecture and supply-chain checks passed. Production E2E/AWS not_run.

`PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`:
1,452 passed in 116.65s, two existing Starlette/AnyIO deprecation warnings.
`uv run --no-sync python scripts/validate_package.py`: 722/722 documentation and
contract checks passed, separately from application tests.
