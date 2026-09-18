# Local Upstage element tagging transport — 2026-09-13

This is an opt-in local transport plus evaluation checkpoint, not activation of
production tagging. `UpstageTaggingTransport` accepts caller-owned UpstageProbe,
TaggingSettings, tenant scope and a trusted per-dispatch authorization callback; it reads no credential/environment and chooses
no deployment region. The existing LocalTagRunner still rejects non-synthetic
transports. No API DTO or database migration is introduced.

## Frozen input and compact wire format

The caller must supply the existing tagging service request: fixed claim/packet,
replica 1/2/3, binding/model/region, prompt, output cap, validated classification
suffix and complete allowed_elements. Unfrozen classification is rejected before
spending. Settings must use MODEL_PROFILE (`upstage-compact-ids-frozen-unicode-v1`),
which pins the wire transformation revision in the existing model/cache identity.
Changing that transformation requires a new profile; effective wire hashes remain
in each receipt. The wire schema pins classification, allowed element IDs and count;
this is a model instruction, not a substitute for downstream validation.

Only source_refs from the caller's evidence_candidates become packet-local IDs
(e0, e1, ...). The model selects IDs rather than reproducing paragraphs, UUIDs,
coordinates and hashes. Local expansion restores the exact original SourceRef,
including candidate/rejected verification state. Selecting a real ID proves
neither semantic relevance nor source quality. Existing source verification,
attribution, complete-element/duplicate checks and Python rules remain required.

User JSON is sent as literal Unicode. Canonical escaped JSON is retained for
hashing/storage; embedding escaped Korean in model-visible JSON was observed to
hurt these diagnostic outputs. Rule names in caller-owned prompts must likewise
be supplied as readable text, not escaped JSON string contents.

Request receipts preserve logical request/model/prompt hashes, effective wire
prompt hash and content, wire user JSON, ID-to-ref mapping and transport version.
Response receipts preserve provider content/usage and expanded application JSON
separately. RawTagResponse.raw_response_json is the expanded representation;
provider_response_json retains the original provider content. A made-up ID
produces no usable expanded response; valid billed usage remains settled.

## Budget, failure and recovery

Real evaluations use only `.local/upstage/budget.sqlite3`, cumulative USD20
(prior USD10 plus the explicit 2026-09-18 USD10 extension, including old expenses
and unsettled reservations; never reset the ledger).
UpstageProbe reserves/settles once per request. Never create another monetary
ledger to extend the budget. The generic tagging service's run usage store may
serve as a token/dispatch gate with pricing=None, but is not a second USD authority.
An approved real tokenizer/run accounting composition is still missing; synthetic
fixture token counts are not promoted to real model estimates.

The generic service now requires `count_input_tokens(request)` for every
non-synthetic binding. Its legacy text counter is a synthetic-only fallback.
`UpstageTaggingTransport.count_input_tokens(request, counter=...)` and invocation
share the same validated compact-wire builder. The supplied counter receives the
separate system/user messages and must account for the bound model's chat framing;
the adapter supplies no guessed token count. Counts are validated before reservation.
Missing composition raises `TAGGING_INPUT_COUNTER_REQUIRED`; invalid counts or
request-validation errors during counting yield `invalid_request` with sanitized
`TAGGING_INPUT_COUNT_INVALID`, not a cache failure. Cached responses skip counting
and dispatch, while still requiring the caller's configured counter contract.

This is a Python-call contract change, with no API DTO/DB migration. Existing
synthetic callers and stored receipts remain unchanged. New real callers must
explicitly bind a validated request counter; no production caller is enabled here.
Wire content/profile and request/cache hashes are unchanged. Rolling back this
hook must keep real worker activation disabled and preserve all existing records.

Exclusive request directories prevent retries. A durable transport-stop marker
blocks subsequent paid calls after unknown usage/transport failure. An incomplete
receipt also blocks new calls after interruption. An OS file lock serializes the
local operation root (macOS/Linux); a busy operation returns an unresolved result
without spending. Recovery of completed tagging requests belongs to the existing
immutable request cache. Neither uncertain reservations nor failed records are
refunded/overwritten automatically.

The shared probe also archives decoded HTTP-200 provider JSON before completion
validation under `<ledger filename>.responses/<hash(request_id)>.json` beside the
ledger. Directory/file permissions are0700/0600; create-only writes are flushed and
fsynced. This includes invalid completion receipts, so future failures can be
diagnosed without repeating a paid call. Headers and credentials are not recorded.
This is decoded JSON, not an exact HTTP byte capture: HTTP errors, invalid JSON and
oversized responses are not archived. Storage failures retain the reservation and
surface the existing sanitized transport error. The files are diagnostics, never
a second budget ledger or permission to refund/retry. Older failures cannot be
reconstructed. No API/DB migration; rollback preserves these private files.

Rollback: stop using the new adapter; existing synthetic composition and stored
revisions are unchanged. Keep all request receipts and the shared ledger. Do not
reuse old receipts as independent replicas or resume an interrupted experiment
under a new ID as an automatic retry.

## Heading routing and limits

The real extraction worker now routes paragraphs plus headings of at least60
Unicode code points through both its stable selection and dispatch gates. This
recovers prose styled as a heading in Samsung Life p23 without changing its source
kind or source quality. The threshold is a bounded routing heuristic, not a
semantic claim criterion. Short headings, captions and other deferred content
remain unknown, not absent; max_calls still bounds selection. The extraction
profile hashes the new routing rule, so new runs have distinct provenance.

Source-quality approval, actual worker/API non-synthetic tagging composition,
semantic gold/holdout thresholds and production deployment remain open. See
`evidence/upstage-tagging-verification.md` for measured diagnostics and failures.


## Separate local tagger approval — 2026-09-18

`check_local_upstage_tagger` is a pure approval check, separate from the existing
extractor-only `check_local_upstage_binding`. It requires a concrete source hash
and exact document-rights ID, an approved/unexpired tenant-scoped Upstage tagger
binding, and schema `local_upstage_tagger_binding_v1`. That binding contains
`tagging_settings_sha256 = canonical_hash(asdict(settings))`, pinning the entire
TaggingSettings value (binding/model/profile/region/prompt/output schema/output
cap/temperature/epoch/response limit). It does not accept an extractor grant.
The provider endpoint and shared USD10/USD20 policy vocabulary are reused, not
the extractor identity or optional-source legacy semantics.

The tagger must be non-synthetic, bound by the same UUID/model ID, use the existing
compact-wire model profile and provider-managed-unverified region, temperature0,
strict integer output cap1..4096 and positive integer extraction epoch. A settings
hash match does not override these limits. Source membership and selected rights
are checked against the consent allowlists. Processing regions and live probe
remain not_run; local approval is not deployment approval.

`UpstageTaggingTransport(..., authorize=callback)` now requires a trusted composition
callback taking `(settings, request)` and returning this preflight.
It must resolve the request packet hash to its trusted source/rights snapshot,
then resolve trusted approval/consent artifacts and the current time on each
invocation, never return a cached `ready=True` or accept model/request-body grants.
The callback is executable composition code, not a serialized snapshot field.
The transport cannot reconstruct source bytes/rights from model-visible text;
passing an unrelated approved source hash is forbidden. This packet-to-source
resolution remains required in the future worker composition.
Full approval artifacts must remain in the caller's frozen audit inputs.

Both input counting and invocation independently call the callback before token
counting/paid reservation. All eight required local tagger checks must pass. An invalid/blocked, incomplete
or extractor-only preflight raises
`UPSTAGE_TAGGING_AUTHORIZATION_REQUIRED`; no model request directory or ledger
reservation is created. A success receipt adds the complete preflight result
(binding SHA256, checked_at and checks) as `authorization`, preserving the exact
model wire content and existing model/profile/cache identities.

This is a deliberate internal Python constructor compatibility change. All tracked
call sites (two integration fixture construction sites) supply the callback. Other
local diagnostic callers must migrate by supplying the actual trusted tagger check;
there is no allow-all fallback. Existing receipts are not rewritten and synthetic
service composition is unchanged. No API DTO or database migration is introduced.
Rollback must disable real tagger callers before restoring the old constructor;
retain all approval and request/response artifacts and the shared ledger.

This does not yet connect a real tagger to LocalTagRunner: separate extractor/tagger
run snapshots, token counter composition and durable preliminary/relationship
suppliers remain required. No synthetic byte count is promoted to a real token
count, no LLM computes a grade, and no rulepack or source guard is relaxed.

## Coverage summary wire profile v2 — 2026-09-19

New opt-in settings may select `upstage-compact-coverage-unicode-v2`. Existing v1
settings retain their original wire contents. The real local pilot defaults to
v2; its different model-profile/settings hash requires a distinct authorized
runtime and new run state. Preliminary settings still use their separate profile.

The observed three-page Doosan request contained about 10KB of unprocessed-source
UUIDs, versus only 512 bytes of evidence catalog. For v2 only, omitted and
unprocessed UUID lists become source counts plus canonical list SHA256 in the
model wire. `not_found_state=unknown`, all actual evidence candidates/catalog
quotes, claim/context and element definitions remain unchanged. The original
logical request, complete identifier lists, packet hash and wire contents are
retained in immutable receipts. Counts/hashes do not establish absence or coverage
completion and cannot be selected as evidence. Invalid identifier arrays fail
before a provider request. No evidence text is truncated.

The shared UpstageProbe request-body validator now runs both during input
reservation preparation and actual invocation, using identical UTF-8 JSON bytes.
Oversized requests fail before token reservation/transport receipts/paid dispatch.
The existing 16384-byte ceiling, cumulative USD20 ledger policy and USD1 per-call
reservation are unchanged; no budget policy migration or new monetary ledger.
Rollback selects v1 for new settings and preserves all v2 receipts. No HTTP or
SQLite schema change is introduced.
