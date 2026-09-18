# Native cell location proposals — 2026-09-14 KST

Unlocated parser cells prevented precise source tracing even when note ownership
was reviewable. Reused the existing source-replayed native table fragments rather
than invoking another parser/model. `cell_source_matches` matches complete
fragment text with whitespace collapsed only for lookup; native text, word IDs
and bounding boxes are copied unchanged. It requires one parser cell and one
native fragment with that text. Partial strings, multiline split fragments,
missing text and duplicate cells/occurrences are not promoted to unique.

A fail-first regression covers unique values, native duplicates, duplicate parser
cells, partial `Scope` versus `Scope1`, clipped fragments and mutable-return
aliasing. An additional negative reproduced a false unique when a second exact
native fragment was clipped. Uniqueness now counts that clipped occurrence too,
while excluding it from usable location proposals. Duplicate positions reject.

Only report_demo's already original-PDF/packet/cell-replayed path attaches these
results. The low-level matcher is not a source-validation boundary. No canonical
cell, source_ref, parse manifest, source quality or numeric result is rewritten.
All matches remain verified=false; note coverage unknown, numeric not_run and
admission blocked persist. The UI explicitly says 원문 위치(미검증), distinguishing
one location proposal from unresolved duplicate text. Packet provenance retains
reader version and original page coordinate system. No API/DB change or dependency.

## Actual source replay

Final artifacts are `.local/note-review-integration/{company}/review-native-final`.
Original archive CLI arguments are reused with only fresh output folders. Results:

| Report | Cell location proposals | Ambiguous cells | No whole-fragment match | Value-candidate proposals |
|---|---:|---:|---:|---:|
| Kia | 19 | 2 | 3 | 6/8 |
| Kakao | 151 | 33 | 25 | 99/114 |
| Samsung Life | 110 | 132 | 54 | 78/190 |

These are selected-table counts, not accuracy or full-report coverage. Numeric
candidate denominators can include missing/non-numeric cells. Kia's repeated95.0
remains ambiguous while39,884 and2.5 have unique location proposals. The final Kia
HTML was opened in Orca; `.local/note-review-integration/kia/native.png` shows the
new column, duplicate withholding and retained note conditions. The original-page
visual evidence is recorded in kia-cross-report.md. No paid API call occurred.

The next needed work remains accepting full-cell source alignment and condition
meaning in the actual numeric service flow. This adds native coordinate evidence
for review; it does not prove row/column semantic ownership or service readiness.

Final full suite:1842 passed,2 existing deprecation warnings,127.69s;
`.local/note-review-integration/pytest-native-final.log`. Ruff, mypy162 files and
4 Python package builds pass; documentation/contracts validator758 passes
separately. Diff check passes.

Orca Muse Spark1.3 Free independently reviewed task_af5e07a683c1 /
ctx_51ccac00d030, settled via msg_a85d036755aa. Its runnable negatives confirmed
clipped duplicate withholding, whole-fragment matching, adjacent-word refusal
and deep-copy isolation; all9 layout unit tests passed. It found no remaining
concrete bug in this scope and noted that text equality is not spatial row/column
validation. Source/PDF validation belongs to the caller and is replayed before
matching. Worker released, exact external terminal closed, delivery acknowledged.
