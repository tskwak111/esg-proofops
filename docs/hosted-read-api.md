# PA6 hosted inventory and source-page API

These additive endpoints use the Secure session cookie and current active-tenant
membership. Minimum capability is `viewer`; editor/reviewer/admin include it.
They share the existing individual GET visibility: members can read the tenant's
documents/runs. Personal ownership is required for neither old nor new GETs.
Tenant IDs, user IDs, filenames, credentials and arbitrary boxes cannot grant access.
All GETs use the existing60/min/user read limit. They never invoke paid providers,
generate scope, reserve cost or change tags/grades/result revisions.

## Collections

`GET /v1/documents?limit=20&cursor=...`
`GET /v1/runs?limit=20&cursor=...&document_id=<UUID>`

`limit` is1–100. Both return `{"items":[...],"next_cursor":null|"opaque"}`.
Results are newest-first by immutable `(created,id)` with keyset continuation.
The signed cursor is bound to tenant, user, collection and document filter. It is
not a snapshot: newly created entries appear on a fresh first page; deleted or
expired entries disappear. Reusing/tampering with another scope returns400
`CURSOR_INVALID`. Invalid UUID/limit returns422. An inaccessible document filter
returns404, rather than an empty successful page. Filenames were never collected;
`display_name` is `보고서 N`, numbered chronologically among currently retained
tenant documents (may renumber after deletion). `uploaded_at`/`created_at` are UTC
RFC3339; `expires` retains the existing Unix-seconds document field.

Document item example (illustrative IDs/hashes):

```json
{"document_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","display_name":"보고서 1","uploaded_at":"2026-10-11T00:00:00Z","page_count":139,"size_bytes":22649241,"sha256":"<original sha256>","expires":1792281600}
```

Run items contain run_id, document_id, created_at, status, stage, progress(0–1),
selected_pages, claim_pages, status_url, result_url, error_code, error_message,
claims_extracted, claims_processed and existing FIFO queue_position. No inline
claim results, user hashes, per-user totals or prepared hashes appear in a list.
A published result URL requires the same immutable result/source hash checks as
individual GET; corruption returns409 `RESULT_INTEGRITY_UNAVAILABLE`.

## Manifest and PNG

`GET /v1/runs/{run_id}/source-pages/{physical_page}/manifest`
`GET /v1/runs/{run_id}/source-pages/{physical_page}/image`

Physical pages are1-based original PDF pages, never printed page labels. Manifest
filters `source_id`, `claim_id` and expected `document_version_id` are optional
UUIDs. Image accepts expected `document_version_id` and `image_sha256`. Obtain
the manifest first, then fetch `image_url` with credentials and compare the PNG
SHA256 to `image_sha256`. No pre-signed public URL or PDF download is created.
Manifest ETag hashes its JSON; PNG ETag hashes its bytes. Both are private/no-store;
an ETag does not bypass auth or produce a304. Content type is image/png with nosniff.

The adapter verifies tenant/run/document binding, retained original SHA, verified
plaintext derivative (only for accepted password-free encrypted PDFs), prepared
SHA, immutable local run input hash, checkpoint hash and pinned parse manifest/
geometry hashes. The document_version_id is the run's immutable local prepared
document version, not the hosted document_id. `source_sha256` identifies the upload;
`render_source_sha256` identifies the actual original/plaintext render bytes;
`prepared_sha256` identifies analysis input. No newer document version is substituted.
The result's page_map maps a source_ref page_num to original physical_page. Only
pages with stored claim/evidence refs in that run's result are available.

Manifest shape (abbreviated):

```json
{"run_id":"<UUID>","document_id":"<UUID>","document_version_id":"<UUID>","source_sha256":"<64 hex>","render_source_sha256":"<64 hex>","prepared_sha256":"<64 hex>","parse_manifest_id":"<UUID>","parse_manifest_sha256":"<64 hex>","physical_page":25,"prepared_page":1,"image_sha256":"<64 hex>","image_url":"/v1/runs/<UUID>/source-pages/25/image?image_sha256=<64 hex>","expires_at":"2026-10-18T00:00:00Z","image":{"width_px":1200,"height_px":800,"dpi":144,"width_pt":600,"height_pt":400,"rotation":0,"crop_box":[0,0,600,400]},"coordinates":{"units":"pdf_points","origin":"top_left","space":"rotated_cropbox_display","bbox_format":"x0,y0,x1,y1","source_to_image":[2,0,0,2,0,0]},"highlights":[{"ref_id":"claims/<claim UUID>/source_refs/0","source_id":"<UUID>","verification_state":"verified","bbox_normalized":[0.1,0.2,0.3,0.4]}],"unresolved_refs":[],"message":null}
```

Stored canonical bboxes already apply rotation and CropBox. Divide x by displayed
width_pt and y by height_pt to get normalized rectangles; apply them directly over
the PNG. Do not apply PDF bottom-left transforms or rotate a second time. The
source_to_image affine uses `[a,b,c,d,e,f]`, x'=a*x+c*y+e, y'=b*x+d*y+f.
The image reports native crop box and clockwise page rotation for inspection.
Images render page content with annotations/forms disabled, like the pinned source
renderer. Missing/candidate/rejected/unreadable, non-finite, inverted or out-of-page
boxes produce no highlight for that ref and `원문 미검증` in unresolved_refs/message.
Verified geometry proves location only, not evidence linkage, present, or a grade.
New publications use the existing exact citation/span verifier on the already
replayed graph to project candidate claim refs. Old revisions are never rewritten;
an old candidate remains unhighlighted even if whole-claim source_quality=verified.

## Bounds, retention and errors

Fixed144DPI; pages exceeding2000px/axis or4M pixels are rejected (no adaptive DPI).
PDFium runs in the existing watchdog/isolation:15s wall/CPU,512MiB child memory,
16MiB output. One source request per volume across API processes, with thread-safe
nonblocking admission before source copying, returns429 `SOURCE_RENDER_BUSY` and
Retry-After. Disconnect does not release admission while its sync worker runs.
Memory LRU has32MiB accounting including4KiB per-entry overhead and at most32
entries; key includes private root, tenant/doc, source/prepared/manifest hashes and
page. Every cache hit rechecks all source integrity, membership and retention.
Deletion clears process-local cache; every response rechecks live run/auth after
rendering so an intervening deletion/revocation/expiry returns no image.

Missing login401 `AUTH_REQUIRED`; missing/revoked membership or foreign/missing
run404 `RESOURCE_NOT_FOUND`; denied capability403 `FORBIDDEN`; unknown ref/page404
`SOURCE_REFERENCE_NOT_FOUND`; wrong version/manifest409 `SOURCE_REFERENCE_MISMATCH`;
tampered/missing source artifacts409 `SOURCE_INTEGRITY_UNAVAILABLE`; wrong expected
PNG hash409 `SOURCE_IMAGE_MISMATCH`; renderer/geometry/size/timeout failure422
`SOURCE_RENDER_UNAVAILABLE`, without PDF internals.
At original creation+7days (or configured shorter retention), source reads return
410 `SOURCE_EXPIRED` even if a PNG was cached or expiry maintenance already purged
files. Minimal tenant/run/doc/expiry identities remain only until the existing
30-day audit cutoff; foreign tenants see404. Pre-PA6 already-purged unknown IDs
remain404. Explicit deletion before expiry returns404. A restored backup excludes
original/prepared PDFs, so source reads fail closed until reupload.

Schema1 migration, backfill, rollback and deployment boundary are in
[CONTRACT.md](../deploy/public/CONTRACT.md). Web connection is a subsequent task.
