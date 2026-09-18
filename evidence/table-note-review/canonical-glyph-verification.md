# Canonical source glyph fallback — 2026-09-14

## Outcome and limits

Original POSCO Future M physical p139 total-strip label, value, row and table fragment
can now be displayed and replayed without changing candidate text or geometry.
The previous font-box validator rejected the label despite its actual glyphs lying
inside the parsed cell. The earlier explicit table tolerance profile supplies the
correct `합계2)` transcription; this change verifies that transcription against
original PDFium characters, including original whitespace, and tight glyph bounds.
No automatic superscript reordering, note ownership, table completeness or grading.

Whole-page exact mapping was tried read-only and found 411/428 matched native words;
17 unrelated header/ligature words remain unresolved. The implemented candidate test
requires every intersecting non-whitespace PDFium glyph to have a selected exact
Unicode+origin mapping and rejects intersecting unresolved native words. Independent
reader word order disagreement remains rejected. This is text/geometry verification,
not evidence of rendered visibility or page-wide coverage.

## Actual service exercise

Source SHA256: `65070d88297d4faf631a9545e6aa49b56ccae71531dda0248f69a3887ab779a8`.
Private new worker state:
`.local/note-review-integration/canonical-glyph-worker-v1/poscofuturem`.
An isolated pilot harness reused the existing preparation workflow with explicit
`table_text_y_tolerance=4`; no --invoke, model client or external API call. Actual
OpenDataLoader/pdfplumber parsing and v3 note artifact publication completed.

Actual authenticated local HTTP source-view + PNG routes returned all four fragments:
`p139-t2`, `p139-t2-r0`, `p139-t2-r0-c0`, `p139-t2-r0-c1`.
The coordinator visually inspected original full-page rendering: total `합계2)` and
`1,009,623` match; neither the source strip nor this check establishes the whole table.
Four transcription citations were explicitly confirmed through the existing revision
API under synthetic local reviewer auth, with If-Match and exact idempotent replay.
Saved revision 2 SHA256:
`7e3a335681403b84e4fdb47e3c656d631effed60ee85fc30926d9e8e6deff170`.
Original graph unchanged; ownership/conditions empty, coverage unknown, numeric receipts
empty. This is agent review authorized by the user, not independent human gold labeling.

The first write attempt returned HTTP413 because full-page glyph inventories repeated
in each receipt. No revision was written. Compact selected-glyph mappings plus the
full-page mapping hash reduced four JSON source views to 12,337 bytes; full original
replay remains required. The subsequent write and exact retry both passed.
Private result: `.local/note-review-integration/canonical-glyph-api-v1/result.json`.

LG Chem p97 and Samsung Electronics p72 source-view HTTP rechecks retain revision5:
LG 0 matched/23 unresolved, Samsung 22 matched/2 unresolved, both coverage unknown.
No old source review was rewritten. 21 installed-wheel report checkpoints reopened
with identical graph hashes, including the newly committed POSCO worker checkpoint.

## Checks and review

Failed-first synthetic source view demonstrated font-box rejection. Final focused
source-view + glyph suite: 47 passed, 2 dependency warnings, 4.52s; rerun after receipt
compaction: 47 passed, 2 warnings, 4.26s. Tests cover actual glyph containment, wrong
text/order, true clipping, incomplete independent glyph coverage, unresolved words
inside/outside the candidate, adjacent original marker text, and replay tampering.
A draft raised-marker fixture exposed a real native-order disagreement; the final
parameterized test preserves it as a required rejection and separately checks the
original-order positive case. No production order guard was relaxed.

Orca read-only review tasks `task_d8f063598d4c`, `task_581e7182885c`, and
`task_5c184e092f8b` reviewed proposed scope, implemented candidate coverage, and final
original-character reconstruction respectively. Review found the fixture/order mismatch
and confirmed conservative rejection. All three workers released and deliveries acked.
Last receipt compaction changes representation only; independently reviewed containment,
identity and order checks remain unchanged and replay re-executes them.

An intermediate full-suite invocation was interrupted after the HTTP413 prompted the
receipt compaction; its partial output is not counted as passing validation. Final
suite uses `.local/note-review-integration/canonical-glyph-release-full.log`.
No paid models, AWS, deployment or browser-driven UI exercise; these are not_run.

Final release checks: full suite 2125 passed, 2 dependency warnings, 150.46s;
Ruff lint/format passed (294 files), mypy passed (173 source files), architecture
checker passed and all four workspace distributions built. Documentation/contracts
validator passed 790 checks/50 API operations, not a product accuracy benchmark.
The confirmed-citation application path was also exercised against the new actual
POSCO checkpoint: exactly four selected sources become verified in the transient
reviewed graph, while those original base sources remain unverified. No coverage or
ownership state is inferred from this transcription review.
