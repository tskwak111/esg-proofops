# Untagged Extracted-Claim Detail Review — Compatibility / Rollback Contract

Status: contract-first (defined before code; implementation must conform to this file).
Scope: `GET /v1/runs/{run_id}/claims/{claim_id}` extraction-only read, its UI rendering,
and `ClaimDetail` shape changes only. No model calls, no tag writes, no transport changes.

## 1. Preserved tagged behavior (must not change)

- When a current tag exists for `(tenant, run, claim)`, the response body is byte-shape
  compatible with the previous tagged `ClaimDetail`: `claim` (track/decision from tag),
  `source_refs` from extraction, `elements` from the tag, `assurance`, non-empty
  `replicate_request_ids`, hex `packet_sha256`, `suggestion: null`, `basis_refs: []`.
- Tagged responses keep `Cache-Control: no-store` and `ETag: "<tag_revision>"`.
- Tag edits still require an existing tag: review resolution, `If-Match`, and
  `base_tag_revision` flows are untouched. Nothing in this change invents a tag,
  decision, grade, label, packet hash, or replicate id.

## 2. Extraction-only (untagged) detail

Returned when the claim exists in the committed extraction snapshot but
`current_tag(...)` is `None` (tagging not yet published). Previously this case
returned `409 TAGGING_NOT_PUBLISHED`; it now returns `200` with:

- `claim.track = null`, `claim.decision = null`, `claim.revision` = extraction
  revision (1 until a tag exists).
- `source_refs` = the claim's original extraction source refs, unchanged shape
  (page/quote/bbox/verification state preserved so the existing `SourceViewer`
  works without modification).
- `elements = []`, `replicate_request_ids = []` (empty, never invented).
- `packet_sha256 = null` (no tag packet exists; a null is returned instead of a
  fabricated hash).
- `assurance.status = "undetermined"` with empty `evidence_refs` (absence preserved,
  never upgraded to covered/not_covered).
- `suggestion = null`, `basis_refs = []`.
- `tag_status = "untagged"` (new optional extraction metadata; tagged responses
  carry `"tagged"`). Clients must also accept its absence (pre-change payloads)
  and may treat `packet_sha256 === null` as untagged.
- Headers: `Cache-Control: no-store`, and **no `ETag`** (there is no tag revision
  to condition edits on; no tag edits allowed until an actual tag exists).

## 3. Unchanged guards

- Authorization: viewer role minimum, session cookie, rate limit `120/min/user`.
- Tenant isolation: foreign-tenant `run_id`/`claim_id` access returns `404`
  (via snapshot/tenant validation), identical for tagged and untagged detail.
- Snapshot validation: uncommitted/failed-integrity runs still return `409`
  (`ARTIFACT_UNAVAILABLE`); unknown claims still return `404`.
- `tags is None` composition with an existing tag still returns `409`
  (`TAGGING_NOT_PUBLISHED`) because tag inputs cannot be loaded; only the
  `current is None` (truly untagged) case takes the new branch.

## 4. Schema compatibility (`contracts/jsonschema/api_models.schema.json`, ClaimDetail only)

- `packet_sha256`: `string(pattern ^[0-9a-f]{64}$)` → `anyOf[string(pattern), null]`.
- Add optional `tag_status`: `enum ["tagged", "untagged"]`, **not** in `required`,
  so old tagged payloads without it still validate and old clients ignoring
  unknown fields keep working.
- No other `$defs` touched. `openapi.yaml` is intentionally not edited in this slice.

## 5. UI contract (`ClaimWorkspace.tsx` only, `SourceViewer` untouched)

- `ClaimDetail` TS type: `packet_sha256: string | null`,
  `tag_status?: "tagged" | "untagged" | null`.
- `ClaimDetailView` renders the original `SourceViewer` with `detail.source_refs`
  unchanged; for untagged claims it shows a "태깅 대기" notice, an empty-elements
  notice, and `Evidence packet: 태깅 전 (없음)` instead of a hash. No edit/replicate
  affordances are enabled for untagged claims.
- `ReviewQueueWorkspace.latest()` keeps throwing when `claim.track` is null, so the
  review editor cannot open until an actual tag exists.

## 6. Rollback

1. Revert the `current is None` branch in `routers/claims.py` to
   `raise RunRejected("TAGGING_NOT_PUBLISHED")`; untagged detail returns to 409.
2. Revert the `ClaimDetail` schema hunk (`packet_sha256` required string, remove
   `tag_status`); revert the TS type + rendering hunks.
3. Newer clients must handle both `200` untagged detail and legacy `409`
   `TAGGING_NOT_PUBLISHED` as "pending tagging". No migration or data change is
   involved (read-only projection of immutable extraction snapshots).
