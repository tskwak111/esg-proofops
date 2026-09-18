# Dense-page note discovery — 2026-09-14 KST

This is progress toward the original service-readiness goal, not completion.
Samsung Life physical121 previously failed the16KB preflight before extraction.
The note runner now subdivides only that preflight failure, never a transport,
budget or provider error. It keeps complete native fragments and four-coordinate
boxes, first using gaps between table columns and otherwise up to four neighboring fragments on each side.
Depth2 permits at most4 successful discovery calls plus one binding call
(and up to3 unbilled preflight-rejected parent receipts). The
shared USD10 ledger,16KB body limit and USD1 reservation policy are unchanged.
Each subrequest has an immutable request/response receipt. A model cannot cite
fragments it was not sent. Exact overlap duplicates collapse; differing overlap
extents fail unresolved. No partial phrase, coordinate or word is truncated.

A source-layout normalization joins only unique, closely spaced hanging-indent
continuations of a numbered note. Other columns, subsequent numbered notes and
unindented prose remain separate. Numeric/marker-only selections remain in the
unassigned source fragments; coverage stays unknown. This is a bounded proposal
heuristic, not semantic acceptance or evidence approval.

## Actual source evidence

The coordinator re-viewed `.local/table-note-wave/samsung-life-source.png` and
compared its4 left and8 right notes against the outputs. Final live archive:
`.local/table-note-wave/recovered/samsung-life/notes-column-joined-final`.
Two real Solar Pro4 discovery calls yielded12 note groups, including both4-line
conditions; all393 native fragment IDs occur in the subrequest union. No false
marker-only note remains in the normalized final output. Every note still has
unknown ownership and is ineligible for scoring; standalone/prefix markers are
not solved by this change. Source packet replay matched the original PDF/graph.
Local original-image plus extracted-note review:
`.local/table-note-wave/partition-review.html`.

Five-source cached-response replay is in `.local/table-note-wave/joined-replay`:
Samsung19→12, Kakao6→6, Kia3→3, KB0→0, Naver0→0. It revalidates the native PDF,
packet hash and output spans; it is not five new model calls. The control pages
are the already-inspected selected pages, not a representative accuracy benchmark.

Rejected sequential/column-only outputs and an ineffective prompt variant are
preserved in separate local folders. They retained all actual condition text but
also selected table markers and split a four-line note; unrestricted binding then
hit16KB. The prompt variant was reverted. The final layout normalization removed
these observed errors without assigning ownership or calculating a grade.

This turn made8 settled text calls, USD0.0219304800 total. Final two-call run:
USD0.0053397300. Shared committed/reserved total:USD7.7930238700 across1327 calls,
including the same6 old unsettled reservations. No parser/AWS/deployment calls.

## Checks and limits

Fail-first oversized input and missing hanging-line grouping were reproduced.
Focused16 tests pass: bounded4-call fallback,2-column path, full fragment coverage,
overlap dedup/conflict, unseen-ID rejection, transport halt, small-count oversized packets, binding after recursion and line grouping.
Ruff passed, mypy162 files passed, all4 Python packages built; diff check passed.
Final full suite:1831 passed,2 existing deprecation warnings,116.13s;
`.local/table-note-wave/pytest-partition-stable.log`. The earlier1829-pass run
preceded the review adjustment and is superseded. Document/contracts validator:
758 passed, separately from app tests.

Orca Muse Spark1.3 Free reviewed the diff in run `run_bd4f467aede6`, task
`task_4b1dbd768db1`, dispatch `ctx_4ff7a8031524`. It verified preflight/budget
ordering, request-scoped IDs and the call bound. Its small-count splitting
concern was fixed with adaptive overlap and explicit depth; binding-after-split
and small-count regressions now pass. The worker settled, was released and its
external terminal closed, then the delivery was acknowledged.

The review also identified a remaining ceiling: a note longer than the overlap
can be returned as disjoint pieces without triggering the overlap-conflict check.
Hanging-indent normalization addresses the observed four-line case, not every
possible layout. Oversized leaves at depth2 remain unresolved. No completeness
or semantic acceptance is inferred from a successful discovery run.

After the review adjustment, exact archived real request/response replay through
the current full runner reproduced the same12 notes without another paid call:
`.local/table-note-wave/recovered/samsung-life/notes-final-runtime-replay`.

The extraction result is still an evaluation artifact. Accepted condition
interpretation, standalone/title/prefix ownership, numeric service integration
and broader report-level E2E remain incomplete. Unknown conditions are never
converted into missing evidence, present tags or a numeric consistency result.
