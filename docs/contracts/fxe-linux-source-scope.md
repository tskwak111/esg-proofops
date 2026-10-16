# FXE Linux source recovery and ranked scope selection

`fxe_finals-20261015-v1` is an additive, explicitly pinned analysis policy over
v23. It selects `fxe_upstage-ocr-page-v21`; existing v23 and earlier analysis and
reader pins remain unchanged. The integration coordinator can assign this hash
to new runs. This change does not change deployed configuration or old results.

The reader first recomputes the complete v23 claim receipt. Unresolved prose
then uses the existing FXA exact parser-offset, PDFium glyph, render-mode,
clipping, transparency, overlay, annotation, source-hash and tenant guards.
Tolerant original metadata comes from the existing H7 pypdf/PDFium reader.
When pixels are required, PDFium renders the original quote region at 216 dpi
without allocating or shrinking the whole page. Both the tight glyph region
and original block region can be tried, each with the existing 0/6-pixel white
padding. Every bitmap including padding remains bounded by 16 million pixels.
An oversized region remains unresolved. The pinned CPU OCR runtime on Linux
(or historical Apple reader on macOS) reads pixels; exact literal quote matching
is required. There are no OCR character repairs, relaxed number/unit spacing,
new dependencies, network requests or model calls in this recovery path.

Native/table/evidence policies and existing table ownership proofs are retained.
The new whole receipt contains the unchanged v23 receipt and separately hashed
recovery proof. Cold replay recomputes both and requires complete equality.
Source/graph/tenant/version/offset identity remains mandatory. Unknown, conflict,
unreadable, rules, replicas, grades and publication requirements are unchanged.

E14's Kakao automatic proposal already used `E06-W5-scope-v1` and selected p51.
Its executed selection explicitly set `manual_selection=true` and replaced that
proposal with an earlier nine-page list excluding p51. This was not a server W5
routing failure. `evaluation.ranked_scope_selection.ranked_subset(plan,
claim_limit=9)` validates a fresh proposal, selects its ranked claim pages and
keeps its evidence union and immutable proposal hash. It never overrides an
explicit human manual selection. Evaluation drivers should use that returned
selection instead of reusing stale page numbers. The corrected selection is
saved in the FXE evidence directory; production runs were not resubmitted.

No API/DB migration is needed. Rollback stops assigning the FXE analysis hash
while retaining its reader for saved FXE receipts; do not reinterpret them as
v23. Linux replay evidence, source census, focused/full tests and limitations
are recorded in `outputs/agent-results/R108-redesign/lab/fix/FXE/FXE-REPORT.md`.
