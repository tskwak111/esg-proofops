# Original glyph geometry in source displays

The POSCO Future M p139 investigation found a font-box/ink-box discrepancy rather
than evidence that the total-label glyph itself lay outside the parsed strip. The
pdfplumber word box for 합계 ends at y451.0769, while independently mapped PDFium tight
glyph bounds end at y443.7794; the parsed strip ends at y449.75994. Original Unicode
characters and text-matrix origins agree to the declared 0.001pt per-axis reader
serialization tolerance. This does not repair the fragmented table or its text order.
A separate read-only probe of pdfplumber table.extract(use_text_flow=True) still returned
`2)\n합계`, so that option alone is not a demonstrated transcription fix.

`native_word_ink_geometry` maps every selected native word character to exactly one
PDFium Unicode/origin pair. It preserves word indices and original font boxes, records
PDFium character indices and tight boxes, and hashes the source/page/reader/matcher
inputs and result. Duplicate matches or reused glyph indices, missing characters,
unsupported transforms and invalid glyph bounds remain unresolved. The overall ink
box is null on partial mapping. Invented coordinates, text-only matching and approximate
word proximity are not used. Tight glyph boxes do not prove rendered visibility: the
invisible-text regression explicitly renders a blank page while geometry is matched.

Native source-view receipts now include this optional diagnostic. Original highlight
boxes, quote, image, canonical graph, source quality and review facts are unchanged;
the field is part of the display receipt hash and recomputed on replay. Unsupported
optional matching returns null without hiding the original display. Tampering with a
glyph box and recomputing both client hashes is rejected by original-source replay.
There is no new route or DB migration; display remains an extensible object under the
existing API contract. Old stored revisions/receipts and exact saved retries remain
immutable; pending receipts from unsupported verifier builds require fresh display.

Orca implementation `task_312cded10ce8` / `ctx_2d3345588fce` supplied the mapper and
32 generated-PDF/boundary tests. It settled, was released and acknowledged. The source
view integration first failed on missing glyph_geometry, then 37 focused tests passed
with two dependency warnings in 9.04s. Independent review `task_081a435f7f3d` /
`ctx_a102b8106b45` ran 36 focused tests and three additional probes, found no actionable
correctness defect, and settled/released/acknowledged. The three probes were preserved
as tests for equal origins on separate pages, a PDFium glyph-reader error and invisible
3-Tr text. Final mapper test run: 35 passed in 0.88s; no production code changed after
the full run below began.

Actual full local API checks used synthetic local reviewer sessions over committed
original reports, not independent expert or production validation:

| Report/page | Selected native words | Matching result | Review |
|---|---:|---|---|
| POSCO Future M/139 | 344 (합계), 345 (2)) | Both matched; tight boxes inside parsed total strip | Initial revision 1; views leave it unchanged |
| LG Chem/97 | Biomass note group, 23 words | 0 matched, 23 unresolved | Revision 5 unchanged |
| Samsung Electronics/72 | Existing NF₃-related group, 24 words | 22 matched, 2 unresolved | Revision 5 unchanged |

All responses retain unknown coverage. LG/Samsung unresolved mappings were not widened
or guessed. POSCO's font-box/ink-box distinction was asserted through HTTP, along with
source hashes, native word identity, repeat receipt equality, unchanged highlights and
committed graph hash. Private responses: `.local/note-review-integration/native-glyph-display-api-v1/`.
POSCO proof hashes: `20011d72cc59f71118513ff638002209771edb1ba5ce8ece97381283d2fd1f87`
(label), `76138b284e333856502a996028d2e7dd70e2b5ec3deb88455a1727f0321e8006` (marker).

Full application suite: **2103 passed, 2 warnings in 152.59s**;
`.local/note-review-integration/native-glyph-display-full.log`. The three added tests
were executed in the subsequent 35-test mapper run, with application code unchanged.
Ruff lint/format (293 files), CI mypy (173 files), architecture and all four package
builds passed. All 20 installed-wheel checkpoint replays (18 previous cases plus both
POSCO packet versions) retained their original published graph hashes. No dependencies,
model calls or budget-ledger mutations were added. Model/AWS/deployment/browser UI
execution was not_run; source-page rendering and HTTP were actually exercised.

Remaining: use this diagnostic within a separately validated native ownership/source
repair path, preserve note remainder/sibling coverage, bind original claims and publish
immutable numeric-check receipts. Glyph agreement alone grants none of those facts and
is not a service-completion claim.
