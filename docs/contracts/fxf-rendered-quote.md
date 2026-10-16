# FXF portable rendered quote confirmation

`fxf_finals-20261015-v1` / `fxf_upstage-ocr-page-v21` is opt-in above FXE.
The public default, hosted allocation, domain rules, parser/evidence/table readers,
FXA implementation and historical receipt bytes are unchanged. Rollback stops
allocating the new analysis hash; existing executions keep their pinned reader.

FXE is recomputed in full first. Only its unresolved, non-table paragraphs may
enter this fallback. FXA independently checks original source SHA, tenant, graph,
version, manifest, native quote, reversible offsets, glyphs, page geometry and
annotations. Its `pixel_required` result is never treated as native approval.

PDFium renders the unchanged original page, including annotations, at an isotropic
scale of at most 3 and at most 16,000,000 pixels. The manifest binds source/page,
media/crop box, scale, actual dimensions and PNG hash. Rotated/cropped/interactive
pages remain unsupported. At most ten eligible pages are read per attestation.
Each page is acquired once through the existing authorized `PageOCRStore`; its
shared ledger, tenant cache, reservations, hosted scope and money limits apply.
No credential, transport, new budget allowance or default provider is introduced.

The OCR collection must be authenticated against trusted SQLite storage and the
newly rendered PNG. Response dimensions must equal uploaded dimensions. The
existing v2 polygon ownership, competing-block, overlap and reading-order guards
are reused with the exact rounded PDFium viewport transform. Every character must match the native
canonical quote literally after the existing whitespace collapse. Every native
glyph center must lie in its corresponding OCR word polygon; matched words must
have confidence >= 0.98. No OCR character correction, Unicode folding, numeric
spacing relaxation or fuzzy matching is allowed. Uncertain text stays unresolved.

Cold replay re-renders original pixels and revalidates retained collections; it
never acquires new FXF OCR. Missing or changed collections/manifests fail closed.
Acquisition failures retain page-local holds. Complete parent and child receipts,
ordered refs, policy, run, tenant and graph are recomputed and compared. A forged
hash is not a substitute for the trusted collection ledger. Only verified spans
are projected; this does not rerun models or change existing grade revisions.

Verification: run `evaluation.fxf_source_replay` in the pinned Linux ARM64 server
image against E14 fixtures and their trusted ledger snapshots. Use focused FXF,
FXE, FXA and v3 tests; full pytest is deferred to I24 by COORDINATION.md.
