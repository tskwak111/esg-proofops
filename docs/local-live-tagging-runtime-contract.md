# Local live tagging contract — 2026-09-19

Implement the already-authorized local Upstage test pipeline. This does not
authorize deployment or resolve domain gaps. USD20 remains cumulative in the
original shared probe ledger. Old synthetic and extraction-only runs retain
their immutable meanings and replay contracts.

## Configuration and snapshots

New explicit `LOCAL_TAGGING_MODE=upstage_local` requires
`LOCAL_EXTRACTION_MODE=upstage_probe`, declared page subsets, independently
pinned `preliminary_settings` and `tagging_settings` (existing TaggingSettings).
The existing `runtime` is the extractor binding. Resolve the other two runtime
artifacts from their settings binding IDs under the same authenticated tenant;
never accept a raw client-provided approval. Freeze `preliminary_runtime` and
`tagging_runtime` plus their artifact hashes and each settings hash. Validate
each against the exact document source hash, rights and current consent using
the existing tagger preflight. Pin distinct binding IDs for all three uses.

Missing, wrong-role, mismatched, expired, cross-tenant or revoked artifacts stop
new paid dispatch. Worker source replay must reproduce the original graph/claim
and every model request must carry the pinned settings and source packet. Persist
raw provider receipts, replica identities and validation results before reuse.
Only exact completed requests may recover; unknown dispatched calls never retry.

## Rule authority

Structurally valid draft/validated rule content can guide extraction and tagging
as `rulepack_use=candidate_tagging_reference_only`. This marker is distinct from
legacy `extraction_reference_only`. Such runs never evaluate or publish a grade;
they retain candidate tags and review inputs with real-provider provenance.
Human resolution requiring grading is explicitly blocked until rule authority
is supplied, rather than returning a server error or fake synthetic decision.
An approved active pack selected through the existing grading gate may use the
normal deterministic evaluation path. No invented approval or domain criteria.

## Worker and evidence

For a verified claim, obtain three independently validated preliminary replies.
Only a matching non-null track and source-bound dimensions allow element tagging;
disagreement remains needs-review. Use same-document LocalEvidenceSearch over
available declared pages, preserving missing-page coverage. Search hits do not
prove semantic binding; unprovided relationship tags remain undetermined.
Freeze one complete track packet for the three element calls. Publish via the
existing job lease, immutable tag checkpoint and review transaction. Record real
calls as real, including interrupted attempts; never set local_synthetic for them.

## Token reservations

No fabricated chat tokenizer or UTF-8-plus-constant estimate. A provider-context
capacity may be used only as an explicitly documented conservative reservation,
not as an actual token count: record its model, source, capture/expiry and hash in
the runtime artifacts/receipts. Reserve the full proven input upper bound plus
the output cap using the existing budget store; actual usage is always provider
usage. Configure operational role/context reservation limits to accommodate that
upper bound, without representing them as the provider's exact context window.
The overrun fence stops subsequent dispatch if actual usage exceeds reservation.
The probe's fixed USD reservation and original shared ledger remain independent.
Until a valid policy is present the real path stays closed.

## Compatibility, migration and rollback

No new HTTP request fields or SQLite tables: optional internal config/snapshot
keys only. Absent new mode/keys preserves existing wire hashes and replay. New
checkpoints pin the new settings and execution mode. Disable upstage_local to
stop creation/dispatch; keep snapshots, raw receipts, ledger and read access.
Do not rewrite old runs to adopt the new mode or reuse their execution authority.

Acceptance includes failure-before-spend for bad authorization/source/policy;
old snapshot replay; live-provider provenance; no grade from draft rules; complete
and interrupted raw recovery; cancellation/lease fencing; tenant isolation; actual
bounded PDF→preliminary→search→tag→review verification. Until those checks pass,
this document is an implementation contract, not evidence of completion.

## Explicit local pilot invocation

`evaluation/local_upstage_pilot.py --live-tagging` prepares the independent
Solar Pro4 preliminary/element settings and runtime grants using the existing
user-authorized local-test registration path. It does not approve a rulepack.
`--tagging-max-calls` (default 12, range 6..60) limits combined preliminary and
element calls through the existing role budget. Extraction still has its separate
`--max-calls` limit. Only `--invoke` enables provider calls; the original shared
USD20 ledger remains authoritative even when configured token/call limits are
larger. Start a new `--state` directory to change tagging mode or call limits;
old extraction-only runs are never reinterpreted as tagged runs.

Example (supply an existing authorized PDF and its actual reporting period):

```sh
uv run python evaluation/local_upstage_pilot.py \
  --pdf /absolute/path/to/report.pdf --state .local/live-pilot \
  --key-file /absolute/path/to/.env.upstage.local \
  --pages 30 --report-year 2025 \
  --period-start 2025-01-01 --period-end 2025-12-31 \
  --model solar-pro3 --max-calls 8 --verify-paragraphs \
  --live-tagging --tagging-max-calls 12 --invoke
```

The example dates/pages are placeholders, not an inferred report scope. A selected
body page alone cannot establish appendix coverage. Results retain this partial
scope. Reusing the same state reads/replays existing work; it must not create new
provider attempts for completed receipts. Incomplete dispatched receipts stop.

## Atomic-source role reuse

After all three preliminary replies agree, their verified literal dimension
spans supply relation tags keyed by `source_id:char_start:char_end`. The range
is the original atomic claim source span (Unicode code points, end exclusive).
Roles outside that source/span stay null. No additional model call is needed.
This retains partial-atom roles without granting them to the whole paragraph.

`relation_tags_for` is shared by automatic tagging and human review. A citation
must be wholly contained by exactly one scoped entry, and every supplied role
must itself be inside that entry. Overlapping matching entries, malformed ranges
and role spans escaping the entry remain unresolved. Any scoped entry for a
source shadows its legacy whole-source entry, including when no scope matches;
legacy data cannot supply a fallback that bypasses the new boundary. Entries
from another source cannot match. The resolver returns None for a known unresolved scope, distinct from an empty
map when no relation roles were supplied. The binding engine never treats that
unresolved marker as permission for local attribution. It validates supplied
roles, periods, explicit unresolved additional axes and allowed scope. Verified
exact local containment does not require separate entity/metric/period join
keys; other-source/table attribution still requires them. Missing values remain
null and no applicability or semantic element decision is inferred. See the
technical distinction in docs/28_RULE_ENGINE_CONTRACT.md.

Existing immutable snapshots with source_id-only maps retain their previous
lookup behavior. Before scoped maps, partial atoms supplied no relation roles;
those historical snapshots are not rewritten. New maps use the existing string
map field and need no public API or DB migration. Guarded cache signatures now
pin `tagging-010-v3-local-identity`; raw provider requests/receipts are reusable
only under their unchanged identity. Rolling back to old code cannot resolve
new scoped entries (it stays unknown/rejected); use the updated reader for those
reviews and preserve all prior revisions. No other paragraph, table or appendix
candidate gains role tags from local reuse. Cross-source extraction and the
management applicable-axis contract remain separate unresolved work.

## Native glyph paragraph verification

The explicit --verify-paragraphs worker path uses a pinned native glyph
policy. Map every page word by Unicode and character origin with the existing
native_word_ink_geometry adapter, then select words using their tight glyph boxes.
Require a complete mapping of words intersecting the paragraph (unmapped words
elsewhere remain recorded), containment of every intersecting mapped word,
exact normalized source text, and independently rendered crop OCR agreement.
No bbox expansion, fuzzy text matching, table approval or semantic attribution.
Retain existing interactive/optional-layer and rendering guards. Unsupported,
ambiguous, oversized or clipped inputs remain unresolved. Record the glyph proof,
reader/code hashes and geometry mode in a v2 attestation; old standalone font-box
attestations retain v1 semantics. New worker policies require new run state;
old artifacts remain immutable and require their pinned original verifier for
exact replay. Rollback disables the new worker policy and preserves all receipts.
No API or database migration is required.

## Opt-in cross-source role extraction

The new internal `application/tagging/relations.py` boundary operates on verified
whole canonical source refs selected from the frozen retrieval packet. It does
not create Claims for evidence. Its indexed source catalog retains a graph hash,
source-list hash, prompt hash, tenant and schema version. The model returns only
one dimensions map per source index; entity/metric/reporting_period are required
keys, unresolved values remain null, and supported extra axes are preserved.
Literal selections use a catalog source index plus a unique exact quotation.
Server code restores offsets and provenance. Grades, invented IDs, duplicate or
missing source entries, unknown axes, unverified sources and partial-source
catalog entries are rejected. Whole-source validation is required because the
returned source_id maps otherwise risk widening partial evidence scope.

This boundary verifies literal source existence, not semantic ownership. A table
cell may reference an indexed header, but the existing accept_binding must still
check table identity, row/column coverage, same-document identity, periods and
all relevant axes. Model-proposed roles never certify those relationships. The
current local scoped-role resolver continues to shadow whole-source maps for
atomic claims; this extension must not overwrite those local entries.

Optional `relation_settings` and a distinct `relation_runtime` grant enable a
receipt stage after retrieval and before element tagging. Each of three replicas
reads the same ordered source catalog. Three validated replies with distinct
provider request IDs are required. Agreement is checked per whole source role
map: a unanimous map proceeds to the existing binding guard; a disputed map
retains the union of supplied axes with every value null. No majority vote or
role-by-role synthesis can manufacture a relationship. Local scoped claim roles
retain precedence, so a disputed external source does not block independent
local review. Every cross-source present vote still needs the existing binding
guard, which treats the null required roles as undetermined. Raw
responses, request/packet/graph/prompt hashes and disagreements are retained;
calls use the existing ledger, lease, capacity and reservation fences. Incomplete
paid attempts stop without retry. A request belongs to the real claim and its
frozen packet, never a fabricated evidence Claim. Relation failure leaves the
claim with `RELATION_TAGS_UNRESOLVED`, without dispatching its element calls,
when authorization, packet validation, receipt recovery, schema validation or
provider independence fails. A validated semantic disagreement alone is retained
in the three replica records and represented by unresolved external roles; it
does not take that failure path. Preliminary track/dimension unanimity remains
required. Existing published checkpoints are not recomputed or modified.
No eligible external source means no relation call and no inferred absence.

Compatibility: no new HTTP DTO or DB table. The optional frozen group contains
`relation_settings`, `relation_settings_hash`, `relation_runtime` and
`relation_runtime_artifact_hash`; partial groups are rejected. Snapshots without
these keys keep existing behavior and pins. Both live configuration and the
store enforce the opt-in mode; the grant is distinct from extractor, preliminary
and element grants. Old reviews remain immutable. Rollback disables the stage
for new runs and retains the updated reader and original receipts for new-format
snapshots. It must not drop relation pins and reinterpret them as legacy inputs.
Use `--live-tagging --live-relations --tagging-max-calls N` for a fresh pilot state;
the total tagger call cap includes preliminary, relation and element calls.
Schema: `contracts/jsonschema/source_relations.schema.json`. Transport profile:
`upstage-relation-source-quotes-v1`. A model-bound result remains candidate
semantic tagging, not independent gold or rule approval.

Integration acceptance must cover: revoked grant before reservation; frozen
catalog/schema/settings mismatch; three genuinely distinct replica request IDs;
malformed/partial/duplicate relation reply without invented defaults; disagreement
without a silently accepted cross-source map while local review continues; original budget accounting after
provider failure; immutable replay with no provider call; and existing local
scope precedence. Select only original whole-source refs already represented in
the frozen retrieval packet, never fetch omitted report pages implicitly. Sources
that cannot be represented without widening scope remain unresolved. Merge maps
without replacing atomic scoped entries. Request envelopes keep the actual claim
identity while the document data remains an evidence-source catalog. The helper
alone must not cause a new paid call in an old run or unlock any grade.


#### Native glyph spacing correction

The native glyph matcher uses an isolated pdfminer layout aggregator that applies
horizontal character spacing after each glyph, including the final glyph of a
text-show operator. This corrects the pinned reader's missing advance across
consecutive Tj operators. Original parser text, source boxes and native word
indices remain unchanged. The corrected character inventory must match the
original inventory exactly; each glyph still needs unique Unicode+origin
agreement with PDFium at0.001pt. Duplicate origins and unsupported geometry stay
unresolved, and rendered OCR verification remains mandatory. No process-global
pdfminer monkeypatch or new dependency is used.

The implementation is included in the existing glyph verifier hash and native
paragraph policy pin. Existing attestations require their original code revision;
create a new run/attestation for this correction, never rewrite old receipts.
Rollback is the original pinned verifier. The independent diagnostic can be run
with `uv run python evaluation/native_spacing_probe.py`.


#### Bounded rendered OCR retry

Keep the initial216dpi crop read. Only a nonempty readable mismatch triggers one
second read with6px of blank white border; the original crop pixels and PDF
coordinates remain unchanged. Do not supply the expected text, language
correction, custom words or replacement punctuation to the OCR reader. Exact
existing normalization is still required. No retry on an unavailable reader or
empty reading. Store both responses in rendered_attempts and retain the selected
reading under rendered; the full receipt hash covers padding, images and reads.
Hidden text, clipping, uncertain native geometry and table relationships retain
the existing gates. The verifier hash pins this behavior, so use a fresh run and
retain the old code for old-receipt replay. No dependency or database migration.


Apple Vision OCR is macOS-only. On other platforms, return the stable unresolved
rendered_reader_unavailable / UnsupportedPlatform result before rendering or
launching Swift. Do not attempt an unsupported compiler/framework and serialize
its variable timeout/compile error into an immutable receipt. This does not add
Linux OCR support or promote any source; native/text and receipt equality gates
remain in force. The policy hash pins this change; historical runs keep their
original verifier revision.


#### Process-local native replay reuse

Committed checkpoint/source/manifest/policy checks still run for every read.
The first read of a native receipt independently recomputes it through the
existing verifier. After success only, retain a frozenset of verified source IDs
in a64-entry process-local LRU. Its key binds tenant, actual source bytes, entire
graph, entire receipt, native policy code hashes, platform and reader versions.
Changed inputs/runtime or eviction require another complete replay; failed
replays are never cached. Returned graphs are reconstructed, and the caller
still checks the published graph hash. No PDF/graph/receipt object is retained
in the cache; no schema, database or receipt format changes. Rollback removes
reader cache routing and restores unconditional replay. Historical receipts
still require their original native verifier policy.

Cold simultaneous requests may repeat OCR. This intentionally avoids a new
coordination service.64 entries is an entry bound, not a weighted byte budget;
parser limits remain applicable. The measured warm replay gain is not a claim
about first-request latency, full HTTP latency or multi-user throughput.

#### Independent raster OCR correspondence experiment

`evaluation/raster_ocr.py` prepares bounded lossless image-only PDF crops and
replays an immutable provider receipt without network calls. It accepts 1..10
whole canonical paragraph IDs, the original source bytes and tenant. Each crop
uses216dpi, six white margin pixels, original top-left point coordinates and no
expected-text prompt or text layer. Renderer/writer/image versions and the full
graph/source/document/manifest identities are included in the request artifact.

The caller must supply request/receipt SHA256 pins from trusted immutable storage;
computing fresh pins from untrusted uploaded artifacts would not establish trust.
Replay rebuilds the exact request from original pixels, checks the complete
request, provider model, submitted PDF digest/length, page/billing identities and
unique element IDs, and compares per-page text with existing exact normalization.
A changed number remains a mismatch. Hashes establish artifact correspondence,
not provider authenticity outside the trusted receipt boundary.

This helper returns OCR correspondence only. It does not alter source quality,
create a SourceRef, relax the native visibility/geometry gate or authorize present.
It is not wired to the production parser or run DTO; there is no migration or
change to existing native receipts. Production integration must first bind its
receipt into the frozen parser policy and immutable checkpoint, restrict fallback
to native-validated OCR failures, and preserve offline replay and old policies.

The provider supplies page numbers, not per-image cryptographic attestations.
`exact_normalized_match` therefore reports literal agreement with text returned
for that page; it must never be interpreted as independent source approval or
proof that a provider cannot hallucinate. Replay enforces200000total OCR characters,
the transport's1MiB response ceiling and strict finite/nonboolean PDF geometry.
