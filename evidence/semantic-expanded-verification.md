# Expanded real-sentence trial and metric-role guard — 2026-09-10

Selected four original LG Chem sentences using the existing `sentence_spans`:
p25 cumulative emissions reduction; p25 renewable energy procurement plus carbon
reduction; p46 industrial-complex water supply; p46 company-facility water usage.
These are coordinator-selected diagnostic inputs, not accepted company claims or
human-adjudicated gold. In particular, industrial-complex supply is not evidence
of the reporting company's consumption. One compound sentence names two metrics.

## Actual model trial: rejected

One Upstage call reused the exact two-example system prompt from the earlier
few-shot trial, with solar-pro3, JSON mode, temperature 0 and 2,048 output tokens.
The model returned valid JSON but used string `"null"` instead of JSON null in
five fields. These quotes do not exist in their own source sentences. The entire
response was rejected and all four inputs remain unresolved; no partial repair,
salvage, numeric comparison, source approval or grade was performed.

Manual role review also found metric `4만 톤` and `약 93GWh` (amount/unit rather
than metric names), and boundary `2023년부터 2025년까지` (a period). Returned
phrases `일평균 약 54만 톤` and `연간 약 4,000만 m³` also do not identify the
water metric precisely. The earlier one-case few-shot recovery did not establish
reliable extraction across these different sentences. No report accuracy claim.

Original packet, request/model/prompt/example/rule hashes, replica, response and
ledger are in `evidence/semantic-expanded-results.json`; diagnostic failures are
in `evidence/semantic-expanded-diagnostics.json`. Original request/response and
runners remain under `.local/semantic-expanded/`. The call's rule hash predates
the added guard below and is preserved as executed, not rewritten after repair.

## Additional shared validation guard

Added a minimal guard to `validate_dimensions`, reused by semantic extraction
and the local splitter: reject a proposed metric consisting solely of one
supported amount+unit or unit candidate, even if that quote exists in the source.
The guard reuses `quantity_candidates`, so all existing validation callers share
it. Genuine metric text and wider metric-containing phrases still require review.
It is not a complete semantic classifier and does not claim to reject arbitrary
time qualifiers, unsupported units or every incorrect boundary tag.

A failing-first regression reproduced source-exact quantity/unit acceptance as
a metric; both are now rejected, while `온실가스` remains a source-bound proposal
with undetermined binding. No domain grading rule, canonical metric ID, API/DB,
dependency, source-quality revision or previous result was changed.

## Verification and cost

All 22 focused dimension tests passed. Offline diagnostic replay verified the
packet/wire hashes and five invalid quoted-null fields, with all four inputs
remaining unresolved. Ruff lint/format passed (234 files), mypy passed (146 source
files), four-package build, architecture and supply-chain checks passed.
Production E2E/AWS not_run.

One call added $0.000259710. Shared ledger: 99 calls, $2.039823245
committed/reserved of $10, including two earlier unsettled calls. No retry,
Bedrock/AWS action or credential output. Validation fixes do not themselves
improve model recall; semantic extraction remains unsuitable for automatic
evidence acceptance without further capability evaluation.

Final full suite:
`PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`
— 1,453 passed in 124.57s, two existing Starlette/AnyIO deprecation warnings.
`uv run --no-sync python scripts/validate_package.py` — 724/724 documentation and
contract checks passed, separately from application tests. A useful next check
is atomic decomposition before dimensions for the multi-metric sentence; that
follow-up was not run here and no causal explanation is established by this trial.
