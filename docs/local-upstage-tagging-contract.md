# Local Upstage element tagging transport — 2026-09-13

This is an opt-in local transport plus evaluation checkpoint, not activation of
production tagging. `UpstageTaggingTransport` accepts caller-owned UpstageProbe,
TaggingSettings and tenant scope; it reads no credential/environment and chooses
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

Real evaluations use only `.local/upstage/budget.sqlite3`, cumulative USD10.
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
