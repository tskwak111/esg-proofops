# Table context recovery — 2026-09-13

Baseline dcd0508. Orca run run_ce66cb6b7654.

## Task outcomes

Coordinator implementation succeeded: the shared evaluation table helper now
retains trailing year footnotes (`2024 1)`), parses star-marked numeric literals
as candidates while preserving their exact original text and markers, retains
multirow column qualifiers such as region/market, and supplies preceding metric
row labels without inventing parent edges. Multirow header labels are excluded
from data values. Preceding context stops at explicit company/outer metric bounds.
The review HTML displays company sections, column basis and preceding row context.
No production source quality, semantic parent, fact, grade or label is approved.

Independent review task task_44dc8f8f4b23 succeeded on ctx_ef0167db5073 using
OpenCode Muse Spark 1.3 Free (confirmed in terminal output). It recommended
preserving context only, withholding SF6 share attribution and leaving the KEPCO
sum discrepancy unresolved. Its arithmetic typo of 21 was rejected: Python and
manual recomputation give 639296+234537-873712 = 121. This was a read-only code and
artifact review, not an independent visual annotation or accuracy benchmark.

The initial default OpenCode attempt ctx_40593a3b5b76 selected MiniMax-M3 and ended
with `Payment Required: Insufficient balance`; it did no review and was stopped
with its exact terminal closed. The retry explicitly launched the requested Muse
free model. After accepted worker_done, release reported external_terminal;
the exact coordinator-created terminal was then closed, delivery acknowledged,
and the Run's reclaimable enumeration was empty. Kiro's known exhausted credit
and Antigravity's unchanged readiness failure were not retried. No Codex child.

## Actual five-report replay

The same archived HTML receipts were processed before (git dcd0508 helper) and
after this change. `table-context-replay.json` pins receipt and HTML hashes.

| Report | Numeric candidates before | After | Interpretation |
|---|---:|---:|---|
| Samsung Life | 87 | 139 | 52 cells recovered under the footnoted 2024 header |
| KEPCO | 114 | 133 | 19 star-marked literals recovered, markers retained |
| Kia | 8 | 8 | Existing target/actual handling retained |
| KB | 0 | 0 | Two unsupported layouts remain deferred |
| Naver | 0 | 0 | Narrative KPI layout remains deferred |

This is literal recovery, not accuracy or approved evidence. Missing values stay
non-numeric; all results are verified=false and eligible_for_scoring=false.
The core strict parse_numeric_literal still rejects marked values when called
alone. Only the table candidate path preserves and separates explicit markers.
Marker semantics, reporting boundaries and parent relationships still need
source-bound semantic review. In particular, previous rows can contain several
Scope/Category labels: none is silently selected as a parent.

## Artifacts and compatibility

New real archive replays: `.local/report-demo/table-context-base/{company}`.
Reviewed exports: `.local/report-demo/table-context-v2/{samsung-life,kepco}`.
Adjacent `*-table-context-v2.json` files pin new artifact hashes and superseded
review hashes. Before copying annotations, exact original claim payloads, table
cells, parser response hashes and source hashes were compared to the prior export.
Old review files, original PDFs, parser receipts and old demos are unchanged.
Optional new context fields are confined to evaluation output; no API/DB migration,
new dependency, paid API call, cloud operation or ledger change. Rollback uses the
previous helper and its pinned review files, not new annotations against old hashes.

## Verification

- Two failing-first unit cases reproduced missing footnote/header and preceding-row
  context; focused table/demo suite then passed 28 tests.
- Ruff check apps/packages/tests/evaluation passed; changed-file format check passed.
- Mypy application/evaluation/load/staging paths: 158 files passed, existing notes.
- `uv run pytest -q`: 1,751 passed, two existing dependency warnings, 134.65s.
- `uv build --all-packages --out-dir .local/visual-review/table-context-dist`:
  all four Python packages built.
- Both real report_demo CLI replays passed. Five-report before/after comparison
  above executed with raw receipts, not synthetic model responses.
- Expanded HTML screenshot verification could not be completed: Chromium emitted
  SharedImageManager mailbox errors and blank/incomplete captures. This is recorded
  as inconclusive for expanded-table visual QA; no successful screenshot claim is made.
  Original source visual checks from the preceding wave remain available.
- Actual semantic model/production-rule/AWS execution: not_run. SF6 46% and the
  121 tCO2eq discrepancy remain unresolved, not converted into evidence absence.
