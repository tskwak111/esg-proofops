# Original PDF source view v1 (W16)

The result UI reads original uploaded PDF bytes with the existing authenticated session. It does not require `/source-pages/` PNG rendering. That endpoint remains unchanged for older clients. No rule engine, source admission, receipt verification policy or persisted publication is changed.

## Original bytes

`GET /v1/documents/{document_id}/original?sha256=<expected original SHA-256>` requires the existing viewer capability, tenant membership and organizer document ownership. Anonymous requests return 401; a foreign tenant/document returns 404. Expired sources return 410. A mismatched expected SHA, changed bytes, unsafe path or unavailable original returns 409. The API copies and hashes the original under the analysis lease, rechecks session/membership/ownership after disk IO, then serves only that private verified copy. Derived/decrypted/prepared bytes are never substituted.

The response is `application/pdf`, `Content-Disposition: attachment`, `Cache-Control: private, no-store`, with `X-Source-SHA256` and an ETag containing the original hash. Starlette supplies byte ranges (206), invalid-range responses (416), `Accept-Ranges` and `Content-Range`. Temporary copies are removed after the response. The session is checked on every range request. Hashing/copying is intentionally repeated per request; there is no persistent source cache. Initial PDF.js full requests are aborted once range support is detected.

## Additive result fields

`GET /v1/runs/{run_id}/result` adds `w16_source_document: {document_id, sha256, page_count, url}` and `claims[].w16_source_view: {quote, refs}`. All existing fields and stored snapshot bytes remain unchanged. This projection is not a new evidence decision. Inline historical result payloads remain supported; new clients prefer the result URL.

Each reference contains `ref_id`, `source_id`, `kind` (`claim`/`evidence`), nullable `element_id`, `quote`, nullable physical `physical_page` and nullable `location`. Claim references include separately stored `table_observation.cell_source_refs` (value/unit/year); these are display references and do not become element evidence. Evidence references preserve their element codes and original quotes. Prepared page numbers are mapped using the saved `page_map`; explicitly original references retain physical page numbers anywhere within the original document, including evidence outside the selected claim pages.

Location is published only for existing verified, located, version/manifest-bound references with finite in-bounds coordinates and a valid immutable geometry anchor. `location` has `bbox`, nullable `glyph_rects`/`line_rects`, `page: {width_pt,height_pt,rotation,crop_box}`, `units: pdf_points`, `origin: top_left`, `space: rotated_cropbox_display`, `bbox_format: x0,y0,x1,y1`. Rotation/crop are already applied; the client must not rotate again and must reject a viewport geometry mismatch. C3/C4 display anchors read the hash-bound frozen snapshot/graph without replaying newer semantic policies.

Exact C3/C4 glyph rectangles come only from hash-bound verified receipt records. An evidence subspan uses the stored canonical character offsets only when text, range and glyph mapping match exactly. Line rectangles union sequential stored glyph boxes; no PDF re-parsing, text searching or coordinate estimation is used. A source bbox without glyphs is a stored region, not a claim of exact line precision. Missing or inconsistent coordinates remain null. The UI prefers known table cell boxes over their enclosing table region.

## Browser integration and limits

The viewer uses the already pinned `pdfjs-dist` 5.4.394 (Apache-2.0); no dependency or lockfile version changed. The web build copies its worker, CMaps, WASM codecs, standard fonts and license to same-origin assets. PDF.js uses session credentials, 1 MiB byte ranges, disabled streaming/autofetch, a single current-page canvas, cancelled stale renders and a capped render resolution. Embedded scripting, XFA and annotation interaction are disabled. Native buttons/number inputs, focus styles, status/alert announcements, reduced-motion scrolling and mobile list/PDF switching are provided. Quotes remain available as text beside the canvas.

See the W16 report and artifact logs for real LG p36 multiline/element highlights, p41 table cells, desktop/mobile behavior, injected error-state checks and the separate synthetic 150 MB/300-page transfer benchmark. The saved LG fixtures contain no accepted different-page element association; this limits semantic cross-page validation, not the navigation implementation. Rendering one active page is deliberate: navigation changes the visible page rather than constructing a 300-page canvas stack.
