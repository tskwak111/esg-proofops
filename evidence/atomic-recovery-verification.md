# Missing-target recovery and table context — 2026-09-09

## Outcome

The previously omitted LG Chem p24 K-taxonomy sentence was recovered as one
source-exact candidate in a separate target-only trial. It remains a compound,
unverified statement, not an approved claim or a grade. Previous discoveries,
revisions and packet folders were preserved, not merged or overwritten.

Two real Upstage calls used the same stored [287,406] target and system prompt:
- Paragraph context retained: model returned other paragraph sentences, including
  a rewritten clause. Exact quote/range guards rejected the response; target stayed
  unknown. `.local/atomic-pilot/missing-retry/` retains the failed reply.
- `--target-only`: paragraph context omitted from the wire input; only the exact
  selected target was extractable. One complete original quote returned and passed
  guards. `.local/atomic-pilot/missing-target-only/` retains this separate result.

This is a one-case input ablation with stochastic calls, not proof that context
caused the failure or that target-only is generally more accurate. Default paragraph
mode is unchanged. No forced quote repair, subject insertion, or automatic retry
loop was added. Target-only mode has its own extraction-rule hash; exact archival
replay must use the matching mode. Full original text remains recoverable through
the application packet identity and pinned original graph.

Calls this turn: 2, settled estimate $0.000461010. Shared ledger: 81 calls,
$2.035189880 committed/reserved of $10, including two earlier unsettled calls.
No Bedrock or cloud operation; no secret in artifacts or logs.

## Table context

Inspection found all five short p24 fragments were OD paragraph blocks with no
native table/row/column or table_parent edges. The pdfplumber candidates separately
contain p24-t2 with the original rows. This explains the missing structural context;
it does not justify silently adding edges to the immutable graph.

`evaluation.section_pipeline.table_row_contexts` now proposes same-page rows whose
whitespace-normalized literal cell sequence contains the source text. It retains
parser/table/row IDs, all row cell refs, quality, and the first available row as
context. The first available row supports zero- and one-based parser indices;
it is not automatically typed as a semantic header. It never fills merged blanks,
assigns company/metric roles, approves bindings, or performs numeric checks.
Text matching is only a bounded context-search heuristic: ambiguous matches all
remain candidates and geometric/semantic validation is still required.

Actual five fragments each found one row in table `cd503c03-cfb2-5029-8c2b-c30213c4f7a0`
(p24-t2), raw parser rows 2/3/4. Context includes 구분 / 주요 활동 / 기대 효과 and
three original cells per row. All binding_status values remain undetermined.
Results: `atomic-recovery-results.json`; full refs and hashes are retained in
`.local/atomic-pilot/table-contexts-v2.json`. The earlier context prototype file
remains unchanged; it omitted the one-based first row, which the new regression
and v2 output fix. No graph lineage or source-quality changes were applied.

## Checks and next step

Failing-first regressions cover target-only input without rewriting, row/first-row
context, tenant rejection and one-based indices. All eight targeted integration
tests pass. Lint/format, 144-source mypy, four-package build, architecture and
supply-chain checks pass. Final full suite: `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q` — 1,430 passed in 107.18s, two existing Starlette/AnyIO warnings. `uv run --no-sync python scripts/validate_package.py` — 709/709 documentation/contract checks passed.
Production E2E/AWS not_run. No precision/recall claim.

Next: feed these table-row candidates to a separately source-bound semantic tagging
trial (activity versus expected effect, unresolved entity/period), then connect
reviewed metric/year/Scope/unit dimensions to existing binding guards. The current
context search itself cannot authorize evidence or grade a claim.
