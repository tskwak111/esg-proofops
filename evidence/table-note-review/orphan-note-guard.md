# Unassigned footnotes cannot disappear from numeric checks — 2026-09-14

## Reproduced defect and change

A synthetic, source-verified numeric case with an original same-page footnote
`해외 사업장 제외` returned `consistent` after its `footnote_of` edge was removed.
The checker read only assigned notes, incorrectly treating uncertain ownership as
no condition. The new regression failed with `consistent` before the fix.

`domain.numeric._unresolved_footnotes` now holds a number when an original
same-page footnote has no resolvable table owner. Table ownership starts from
table blocks and traverses only table-row/cell `table_parent` edges. Missing,
self-referencing and paragraph targets are not owners; a fabricated paragraph
`table_parent` edge also reproduced `consistent` and is now blocked. Traversal
terminates on cycles. Any candidate page of an unresolved note may trigger the
hold; this does not select or approve a winning interpretation.

The result is `not_computable / footnote_conditions_unresolved`. Notes explicitly
owned by another table and orphan notes on a different page are not imported as
global evidence. An orphan unit note also remains unresolved: its text cannot
establish its owner. Same-page unrelated orphan notes may conservatively hold
more numbers until ownership is established. No grade, label, domain mapping,
organizational-boundary meaning or unit equivalence was added.

## Candidate serialization and actual reports

`report_demo.attach_table_notes` additionally retains the replay-validated
same-page `unassigned_notes` in each numeric candidate's `note_context`, separate
from linked `notes`. A candidate with any unassigned note has
`reason=footnote_ownership_unresolved`, `admission_status=blocked`,
`numeric_status=not_run`, and unknown coverage. The UI explicitly shows the count
for separate review. A failing regression originally raised `KeyError` because
the candidate silently lost this context.

Archived source-bound note results and original PDFs were replayed through the
actual report-demo CLI to new `review-orphan-notes-v1` directories under
`.local/note-review-integration/{kia,kakao,samsung-life}`. No paid API calls.

| Selected report | Numeric candidates with context | Unassigned notes retained per candidate | Hold reasons |
|---|---:|---:|---|
| Kia | 8 | 0 | 8 conditions unresolved |
| Kakao | 114 | 2 | 114 ownership unresolved |
| Samsung Life | 190 | 0 | 116 conditions unresolved, 74 coverage unconfirmed |

Counts include unsupported/non-numeric candidates, not just computable values.
All three CLI invocations succeeded and all reports still have `complete=false`
and zero decisions. Original archives and prior rendered artifacts were retained.
Kakao's rendered candidate table was inspected in the Orca browser; screenshot:
`.local/note-review-integration/kakao/orphan-screen.png`. Linked note text and
`귀속 미확정 각주 2개 별도 검토` are visible together without presenting the latter
as an accepted association.

This is not a claim that archived model-proposed notes have been inserted into
an accepted production numeric snapshot: that integration remains incomplete.
The domain guard protects original graph footnotes; the report path preserves
uncertain proposals for review. Complete note detection and cross-page ownership
are not proven by these selected-page checks.

## Compatibility, rollback and validation

No API/DB wire contract or migration changes. `NumericBlock`'s internal structural
protocol now names its existing `kind` property. Numeric inputs with an orphan
note become stricter; old call signatures remain. The demo artifact addition is
optional for old render inputs (`get` fallback); freshly built artifacts include
it before hashing. Do not rewrite existing immutable revisions/receipts. A code
rollback must not represent newly unresolved cases as approved evidence.

Focused validation: 104 numeric acceptance checks and 4 report-demo integration
checks passed. Eight new numeric cases include independent-parser, same-page vs
other-page and explicit other-table cases. Ruff and mypy (163 files) passed;
`uv build --all-packages` passed. Package validation is documentation/contracts
only, not application accuracy. Full suite: `uv run pytest -q` — **1860 passed**,
2 existing deprecation warnings, 127.48 s; log
`.local/note-review-integration/pytest-orphan-notes-final.log`. Documentation/contract
validation: 758/758. `git diff --check` passed.

Orca Muse Spark 1.3 Free reviewed the domain guard read-only: task
`task_6f81a9cae76b`, dispatch `ctx_3e01e459c240`, accepted completion
`msg_4604c589ece7`. Reviewer independently ran 104 numeric checks and mutation
probes, found no false approvals in that scope, and noted conservative overblocking.
The later candidate serialization change was verified by root's integration
regression and actual three-report CLI/browser replay, not claimed as independently
reviewed. Worker settlement was released, exact terminal closed and delivery acked.
