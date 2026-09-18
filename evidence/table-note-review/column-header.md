# First-row column note retention — 2026-09-14

A fail-first synthetic regression placed `해외 사업장 제외` on the long-form
value-column header r0c8. The original normalizer dropped the note and the real
numeric checker returned consistent. The same gap affects field-column titles
such as organizational boundary and unit; a correctly verified note is not a
verified interpretation of its exclusion condition.

The shared pure `column_note_targets` helper derives first-row column context
from immutable same-table parent edges and candidate column intervals. Both
normalizer entry points and the numeric checker use it. Only value and bound-field
columns contribute; adjacent year columns do not. Span overlap is interval-based
and does not allocate a cell grid. Existing observation projections/contracts
are unchanged; newly retained note blocks change the observation content hash.
No old revision or report is rewritten and no dependency/API/DB change is needed.

This is conservative first-row context, not semantic header approval. Arbitrary
multi-tier headers still need explicit source-bound associations; the helper does
not claim complete note coverage. Raw conditions remain withheld, while the
existing exact unit-note grammar is unchanged. The service-readiness goal stays
active; full-cell verification, interpreted conditions and production routing
remain open.

Focused numeric/table tests:122 passed. The three new cases cover value,
organizational-boundary and unit column titles plus stripped observation note
text. A local runtime check separately confirmed all three through explicit
normalize_table_bindings, preserving unverified quality. Existing adjacent-year
isolation tests pass. Ruff, mypy162 files and four Python package builds pass.
No paid API or cloud calls in this turn.

Orca Muse Spark1.3 Free reviewed task task_985a50fb0cac / dispatch
ctx_553baba23f38, accepted worker_done msg_0b4697cd91b3. Its independent checks
confirmed merged-column retention, no adjacent-year leakage and explicit-binding
parity; no fail-open was found in this scope. All candidate coordinates are kept
conservatively because conflicting layouts must not silently lose note context.
This may withhold more observations on disputed layouts and is not a source
approval. Second-tier non-basis headers remain the stated coverage ceiling.
The worker was released, its exact external terminal closed and delivery acked.

Final full suite:1841 passed,2 existing deprecation warnings,127.88s.
Log: `.local/note-review-integration/pytest-column-final.log`.
Documentation/contracts validator758 passes separately; diff check passes.
