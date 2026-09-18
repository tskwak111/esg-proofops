# Separate native footnote markers — 2026-09-14 KST

The previous dense-page extraction retained12 Samsung Life121 notes but could
not propose owners because native `1)` markers were separate PDF words.
Original source inspection showed smaller, raised markers immediately beside
labels, year headers and a numeric value. Layout now preserves each unique
nearby base/marker pair with native word indices, text, character sizes and boxes.
Both words must be upright and fully inside the table. Lower-row, normal-size,
far-away, clipped, empty-character and ambiguous-neighbor cases are rejected.
Near-equal base endpoints within0.1pt remain ambiguous rather than guessed.

The separate-marker path requires one horizontally aligned external-note table.
It can match the explicit same marker before/after the native terminal word,
including parser-reordered prefix/infix markers. Digit and word boundaries block
`1)` matching `11)` or `Metric` matching `SubMetric`. Multiple matching cells
remain unknown. Existing joined-suffix handling remains available. This is a
proposal constraint, not full-cell text/geometry or condition-meaning approval.

## Actual evidence and compatibility

Final live archive:
`.local/table-note-wave/recovered/samsung-life/notes-separate-final`.
Solar Pro4 made2 discovery calls and1 binding call. All12 notes have a single
proposed owner, consistent with the coordinator's original-page visual check:
8 right-column categories/family labels and4 left-column year/basis/revenue/value
anchors. Both long4-line notes remain intact. All target cells remain unlocated,
all outputs ineligible for scoring, and no numeric result/grade is produced.
The initial live variant proposed11 links; the merged-label infix case prompted
one additional regression and the final run. No old receipt was overwritten.
Original-image plus proposed-link review: `.local/table-note-wave/marker-review.html`.

After review hardening, exact archived requests/responses replayed through the
current runner with the same12 notes/links and no paid call:
`.local/table-note-wave/recovered/samsung-life/notes-marker-runtime-replay`.
Kakao6/Kia3/KB0/Naver0 source replay also preserves the exact prior proposals:
`.local/table-note-wave/marker-controls-stable`. Removing only the new
`separate_markers` layout field reproduces each old packet hash. New packets keep
new hashes; old packets/results are not rewritten. This local packet extension
changes no production API/DB contract and adds no dependency.

This turn made6 settled text calls, USD0.0133359600. Final3-call run:
USD0.0067801800. Shared committed/reserved totalUSD7.8063598300 across1333 calls,
including the same6 old unsettled reservations. No parser/AWS/deployment calls.

## Review and verification

Orca Muse Spark1.3 Free reviewed task `task_65881bffada0`, dispatch
`ctx_0aad4c4350f2`, run `run_bd4f467aede6`. Digit/word substring risks were
reproduced fail-first and fixed; column gating and near-tie handling were tightened.
The claimed lower-row pairing did not reproduce with coherent native character
coordinates; a regression explicitly confirms rejection. Empty marker characters
are rejected. Prefix matching still proves only a terminal native word/marker,
not the whole unlocated cell. Mixed subscript bases and unaligned/ambiguous notes
can remain unresolved. These limits prevent a claim of complete semantic ownership.
The worker settled, was released, its exact external terminal closed, and delivery
acknowledged. No source approval or grade was delegated.

Focused29 tests pass, including the new native pairing and three marker-order
paths, cross-column/duplicate-cell ambiguity and substring negatives. Ruff and
mypy162 files pass. Final full suite:1837 passed,2 existing deprecation warnings,
119.85s; `.local/table-note-wave/pytest-markers-stable.log`. The earlier1835-test
run preceded review hardening and is superseded. All4 Python packages build.
Document/contracts validator758 passes, separately from app tests. Diff check passes.
The original service-readiness goal remains active: full-cell source validation,
condition interpretation, application wiring and broader service E2E are still open.
