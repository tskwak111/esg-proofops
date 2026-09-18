# Orphan note checks on retrieval and tagging input — 2026-09-14

## Reproduced runtime gaps

The real retrieval function returned `status=candidate` for a verified synthetic
table claim whose original graph contained an unassigned same-page footnote.
The real tagging function also accepted a rehashed packet which omitted that
footnote. A second probe removed all table evidence candidates while retaining
the table-based claim and again reached tagging. These regressions failed before
the corresponding guards were added.

The pure `domain.numeric.unassigned_note_ids` helper is shared by numeric checks,
retrieval and tagging. It resolves known table ownership through table-row/cell
parent edges, terminates cycles using visited sets, and retains uncertainty for
unassigned notes. Explicit ancestor table pages are included; unrelated document
pages are not inferred as evidence. A standalone unassigned footnote is not a
usable global evidence candidate. Edge lookups are indexed locally for linear
traversal per call; no persistent cache or new dependency.

Retrieval now excludes an affected table source or standalone orphan note while
preserving its ID in `unprocessed_source_ids`. An affected direct claim/same-table
candidate makes the packet `blocked_evidence`. The existing worker already
records this as `EVIDENCE_PACKET_BLOCKED` before tagging. Tagging independently
rechecks both original claim source IDs and every submitted evidence reference
before budget reservation or provider invocation, so modifying the packet cannot
remove that guard. A malformed/omitted-note packet raises
`DomainValidationError("unassigned footnote requires review")`; it is not an
absence classification or a new grade.

Three packet variants (omitted note, omitted parent references, removed table
candidates) now all reject with zero synthetic provider calls and zero budget
attempts. The other-page orphan control preserves a usable table packet while
excluding the standalone orphan. Focused numeric/retrieval/tagging checks: 179
passed. No paid model calls were made.

## Scope and compatibility

No API/DB schema, migration, input signature, grading mapping or model policy
change. Existing coverage identifiers and blocked states are reused. The
previous numeric guard now also follows explicit ancestor pages; it still does
not approve cross-page ownership or semantic bindings. Source-verified text alone
cannot resolve an orphan. A paragraph/caption link is not table ownership, so
some non-table footnote contexts remain conservatively blocked pending a suitable
ownership contract. This is a documented coverage limit, not absence.

This protects footnotes actually present in the original canonical graph. The
separately validated model-proposed note archives still need immutable runtime
registration/integration; the 21 previously checked report notes are not claimed
as newly accepted canonical graph nodes. That remains required work before the
full goal can be called complete. The tests here use explicitly synthetic verified
sources and a synthetic provider; they are runtime regression evidence, not a
cross-report accuracy claim.

Rollback must preserve existing receipts/revisions and must not silently approve
cases newly identified as unresolved. No prior packet or report was rewritten.

## Validation

Ruff passed, mypy passed 165 source files with existing untyped-body notes, and
`uv build --all-packages` passed. Documentation/contract validation is not an
application test (758/758 checks). Full regression: `uv run pytest -q` — 1866
passed, 2 existing deprecation warnings, 135.63 s. Log:
`.local/note-review-integration/pytest-tag-note-gate-final.log`. `git diff --check`
passed.

Orca Muse Spark 1.3 Free bounded read-only review: task `task_84a870cfdd22`,
dispatch `ctx_8b735778f410`, accepted completion `msg_a35b1874d45c`. Reviewer
confirmed cycle termination, dangling-owner conservatism, page scoping,
standalone exclusion and both pre-budget tagger guards with local probes; no
concrete blocker in that scope. Full suite was root-run, not reviewer-run.
Worker released, exact terminal closed and delivery acknowledged.
