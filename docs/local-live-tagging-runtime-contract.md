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
from another source cannot match. The binding engine still validates source
identity, required/applicable dimensions, periods, table axes and allowed scope.
No metric, period, entity or applicable-axis exemption is inferred.

Existing immutable snapshots with source_id-only maps retain their previous
lookup behavior. Before scoped maps, partial atoms supplied no relation roles;
those historical snapshots are not rewritten. New maps use the existing string
map field and need no public API or DB migration. Guarded cache signatures now
pin `tagging-010-v2-source-spans`; raw provider requests/receipts are reusable
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
