# P1 hosted control plane v1

Baseline 12ed952; task deploy-P1, DESIGN §§4–8 and A-08 hosting override: one
Lightsail Linux VM, one API and one durable worker, active=1, queued=8.
No push, cloud changes, provider keys or paid requests are authorized here.

## Composition and compatibility
`APP_ENV=hosted` selects a separate explicit composition in `main.create_app`,
never a local environment rewrite or an in-memory auth store. `MODEL_ADAPTER=disabled`
is mandatory. Existing local API, research receipts, frozen readers and schemas are
untouched. The hosted control-plane schema is additive v1 in its own data directory;
unknown schema versions fail startup. No automatic import of research/customer DBs.
This API offers invitation/session, PDF upload, run acceptance/poll/cancel and deletion;
it does not yet implement the existing R108 claim/review/export DTOs. Result profile
is `r108-hosted-control-v1`; missing analysis is `partial_blocked`, never fabricated.
Linux Apple Vision equivalence and approved OCR/live worker wiring are release gates.

## Configuration and auth
Required: HOSTED_DATA_DIR (absolute private volume), APP_ORIGIN (one exact HTTPS
origin, no path/wildcards), HOSTED_SESSION_SECRET (at least 32 random bytes),
HOSTED_EVENT_ID. SQLite stores hashed single-use invitation and session identifiers,
HMAC-derived CSRF hashes and server-owned memberships. Invitations expire in 24h,
sessions in 8h with a 30min idle deadline, rotated on tenant switch, revoked on logout.
Invitation CLI reads tenant/user/role, returns a CSPRNG code once; no login seed/default.
Login requires exact Origin and JSON; subsequent writes require Origin+X-CSRF-Token.
Cookie: __Host-proofops_session; Secure, HttpOnly, Path=/, SameSite=Lax, no Domain.
Web/API require same-site owned domains; arbitrary vercel.app cross-site cookies are
unsupported. CORS exact APP_ORIGIN, credentials=true, explicit methods/headers.
Strong membership reads and server session tenant scope; inaccessible UUIDs return404.
Login/source/auth bodies are not logged. Limits use durable hashed subject counters;
no trusted forwarded IP or tenant/client cost fields. Keys must never enter VITE env.

## Upload and retention
POST /v1/documents accepts application/pdf bytes with Idempotency-Key; filenames and
remote URLs are not accepted. Stream body capped at HOSTED_MAX_UPLOAD_BYTES=52428800,
One cross-process upload slot rejects excess requests with429/Retry-After1 before
receiving their bodies; disconnect cannot release the slot during validation.
PDF quarantined subprocess checks reuse SEC-002 (max300 pages, password/active-content,
object/expansion/CPU/memory bounds). Run pages default first min(2,page_count), unique
1-based pages, at most2. Original SHA, selected page map and prepared SHA bind input.
User approved original retention 7 days (coordinator update); runtime upload_notice
is Korean and states automatic deletion. DEC-19 event cap is USD5, target host4GB.
Config defaults HOSTED_ACTIVE_DAYS=7, HOSTED_BACKUP_DAYS=14 (absolute age from creation),
HOSTED_AUDIT_DAYS=30; backup/audit remain proposals; original7days is approved.
HOSTED_CONSENT_VERSION must be
set plus HOSTED_ACCEPT_UPLOADS=true before upload; defaults are closed.
All payload files are contained per tenant/document; metadata DB has IDs/hashes/status,
no PDF, filename, quote, provider content, prompt or response. SQLite backup copies only
allowlisted control rows, excludes auth and raw/prepared source bytes; only receipt/graph/
export artifacts may enter backup. Backups expire by creation+14d, and purge removes
matching backup payload early. Tombstone commits before unlink, fences jobs/writes and
survives data restore in a separate deletion/money ledger (`deletions.sqlite3`).
Backup manifests bind its identity; a foreign/lost ledger fails restore closed.
Startup replays tombstones before
serving. Purge deletes entire document payload directory (original, prepared, crops,
provider cache, receipt/export) and document/run/idempotency DB rows. Failures remain
`failed` and blocked for retry. No trigger removal, no forensic-erasure promise.
Maintenance runs periodically and explicitly by CLI; expired active documents purge,
backups expire, sessions/invites and minimal audit expire. Settled run audit expires
after30days; only a subject-free event amount remains so TTL cannot reset the cap.
Unknown money requires reconciliation. Completed deletion fences expire after30days,
after all possible source/backup lifetimes; ordinary writers still cannot remove them.
Online backup and restore are
operator CLI operations while API/worker are stopped; ledger is never rolled back.

## Queue and money
POST /v1/runs returns202 and status_url; GET only reads persisted state. Active1,
queued8, one active/queued per user across tenants, user2/day and global10/day;429 has
Retry-After. FIFO claim uses one SQLite immediate transaction and a monotonic fence;
expired active lease becomes accounting_pending, never automatic paid redelivery.
Cancel/delete fences commit immediately; previous workers cannot publish afterwards.
Pre-dispatch broker uses integer micro-USD and SQLite BEGIN IMMEDIATE. Defaults:
HOSTED_RUN_USD=.50, HOSTED_DAY_USD=5, HOSTED_EVENT_USD=5, Asia/Seoul day boundaries.
Run envelopes are charged once globally, nested call bounds against that envelope;
parser/LLM/OCR/retries/legacy must all use the broker. Reservation commits request ID,
input SHA and upper cost before transport; receipt must match ID/hash/provider and actual
cost <=bound to settle. Exceptions retain reservation/accounting_pending; repeated call
IDs never redispatch. No automatic fallback/retry. Unknown costs are not released.
A stopped/finished un-dispatched run releases only its unused envelope. Existing research
ledgers are never reset, imported or mistaken for approval of this deployment budget.
No live provider binding is wired in P1; worker processes an offline blocked checkpoint
for smoke and never calls models. Live dispatch cannot be enabled by an env string.

## Flags, migration, rollback and operation
ANALYSIS_BACKEND=r108|legacy|static (default static), R108_ACCEPT_NEW_RUNS=false,
LIVE_DISABLED=true; browser flag is advisory. Legacy paid adapter is unwired, so legacy
mode fails new acceptance; static fallback remains safe. GET /v1/runtime discloses flags,
consent version, source verifier/live capability and caps. Operator stops acceptance,
preserves outstanding reservations/tombstones, switches web to static, rolls back image
only to a release that understands hosted schema1. Do not restore an old ledger/schema
or route through APP_ENV=local. HTTPS terminates at a trusted proxy; Uvicorn trusts no
forwarded headers. Container non-root/read-only, volume private, network-none smoke,
no provider keys, memory/CPU limits (3GiB container on4GiB host). Selected PDF work
runs in a bounded subprocess outside the DB lock, with a fresh publication fence.
Run one worker per volume (DB enforces active1).
Health/live reports process liveness; health/ready reports control-plane readiness and
explicit live-analysis=false. It is not OCR/model quality or public-launch certification.

## P2 amendment — authoritative hosted result contract (2026-10-09)
P2 supersedes the P1 statements that no analysis/result/review binding exists. Hosted
API remains its own durable auth/control composition; an isolated private worker
prepares the unchanged R108 run snapshot and drives its parse/extract/tag workers.
The private local stores contain no public auth seed or local HTTP routes. Public
sessions always supply tenant scope; the worker pins that same tenant. Existing
claim-source verification, consensus, rules, review source admission and CAS remain
unchanged. This is a locally verified integration, not a cloud/public launch.

Default profile `r108-hosted-sprint5-v1`: Upstage document-parse-260128 with native
glyph/region boxes; OpenRouter openai/gpt-6-luna; occurrence-v3;
glyph-joined-display-v1; glyph-alignment-v1; Apple Vision on macOS. Gemini fallback
is off: this hosted binding has no approved budgeted Gemini transport. Any remaining
parse/source gaps stay unresolved. Linux defaults to `upstage-ocr-page-v3` after
coordinator approval of O1d (62/64 holdout retention, false-verified0, numeric
promotions0); macOS retains Apple. Failed v1/v2 requests remain
`partial_blocked/LINUX_SOURCE_READER_UNRESOLVED`, empty claims, null grades and
zero dispatch. All live enable flags remain explicitly off by default.

Live requires **both** `LIVE_DISABLED=false` and absolute `HOSTED_LIVE_CONFIG` JSON:
`enabled:true`, absolute `openrouter_key_file` / `upstage_key_file` paths, and
operator-owned `report_year`, ISO `period_start`, `period_end`. Missing/disabled
configuration or key paths fails startup. No inline key or browser variable is
accepted. Key files are read only by the worker. The reporting scope is disclosed
in the result; operators must configure the correct report period before admission.
Default remains off. Do not reuse research data/ledgers as the hosted data volume.

Every external request passes `HostedStore.dispatch` before transport, including
each Luna schema retry and Upstage standard/enhanced fallback. Selected<=2 permits
synchronous Upstage parse with the same graph conversion DTO. Bounds are standard
USD.011/page, enhanced .033/page (VAT reserve included), Luna .011/attempt under the
existing fixed model/max_price/request-byte/max-token policy. Actual Luna usage.cost
rounds upward to micro-USD. Unknown/malformed receipts retain the full run envelope;
restart never redelivers active/unknown jobs. No paid legacy transport is exposed. Approved PNG-only page OCR uses the same
hosted broker at USD0.00165/page (VAT included), at most2 selected pages, with
model/API/billed-page receipt validation before settlement. Default ceilings remain .50/run,5/day,5/event; lower caps work.
Prices checked against https://www.upstage.ai/pricing/api and
https://openrouter.ai/openai/gpt-6-luna/ on 2026-10-09; inherited Upstage expiry guard
still closes dispatch after 2026-10-14 until its pricing policy is rechecked.

`POST /v1/runs`202 and `GET /v1/runs/{id}` add:
- `stage`: queued/parse/extract/tag/result (terminal status when no stage exists).
- `progress`: **0..1**, stage milestone estimate, not model-quality/completion proof.
- `queue_position`: FIFO 1-based queued position, otherwise null.
- `result_url`: session-protected `/v1/runs/{id}/result` when artifacts exist, else null.
- `result`: the same DTO inline, else null. Cancelled runs never expose a result.

`GET /v1/runs/{id}/result`: `r108-hosted-result-v1` DTO with `claims`, `reviews`,
`hold_reasons`, `pipeline` (actual stages/outcomes/profiles/reporting_scope), `page_map`.
Claims preserve existing claim summary/decision and add `source_refs`, `elements`,
`source_quality`, `hold_reason`, `missing_evidence`, `possible_grade_range` (existing
Decision.grade_range), `confirmed_grade` (existing Decision.evidence_grade).
`page_num` and source refs use the selected PDF's 1-based coordinates; `page_map`
and `original_page_num` map back to uploaded original pages. Send existing source
refs unchanged for review. Unknown/conflict/unverified never become absent; absent
or null decisions stay null and no aggregate/report-wide grade is invented.
Partial work can have a result; incomplete extraction has a reason and no fabricated
successful empty analysis. Pending/no artifact returns409 ANALYSIS_RESULT_UNAVAILABLE;
source/checkpoint mismatch returns409 RESULT_INTEGRITY_UNAVAILABLE. Tenant mismatch,
deleted source or inaccessible UUID returns404. All replies remain no-store.

`POST /v1/runs/{id}/reviews/{review_id}/resolve`: reviewer/admin only, exact Origin,
CSRF, Idempotency-Key and quoted integer If-Match. Body is unchanged ReviewResolve:
base_tag_revision, track, complete element list, reason(5..1000 chars). Reuses the
R108 human review service: verified citations, complete track elements, revision CAS,
idempotency and human provenance. It recomputes the decision; clients cannot supply
a grade. Subsequent result reads include the new immutable review/decision head.

Deletion policy is **uploader or tenant admin**, not admin-only. Existing P1 uploads
without an owner record remain admin-only. Nonowner same-tenant users get403; foreign
tenant gets404. Idempotency-Key and reason remain required. A tombstone immediately
fences API reads/dispatch/publication. While an analysis child owns the source lock,
purge returns failed and maintenance retries after it exits; do not claim erasure
before status completed. All work/receipts/provider caches stay under the document
payload directory and are removed on purge. Analysis originals/working copies never
enter backups. Seven-day expiry still purges the entire document payload. Process
receipt caches are cleared after successful deletion. No source-bearing control rows.

Submission hosted-r108-web(8ae22b7) compatibility: inline result, numeric progress,
queue position, existing errors/headers and uploader deletion now have backend
support. Its current RunOutcomeView still needs claim/review rendering to consume
this DTO; API integration does not certify a deployed browser or Vercel cookie/body
proxy. No frontend checkout, Vercel configuration, cloud resource or push changed.

## P4 operator profiles (additive config; no DB migration)

Private `HOSTED_LIVE_CONFIG` accepts `analysis_profile`: `r108-default` (omitted
value preserves P2 behavior) or `r108-finals-candidate`. The candidate reuses the
frozen I1 bundle including Q3; its preparation uses vision-parse auto and source
context order instead of the default position context order. Budgets and grants
remain operator-owned and every paid transport still requires the hosted broker.
`rendered_reader_profile` is one operator JSON entry selecting v1/v2/v3; omitted
means v3 on Linux and Apple on macOS. Only v3 is release-approved; v1/v2 remain
unresolved and unknown profiles fail validation. Operators cannot approve a reader.
`config/hosted_rendered_readers.json` records the release allowlist/default and
O1d SHA256 `69f0797dbae5420ba1b5deb4ef2f12df3e7a820c0a9a37c5f5d16c37deea741e`.
Its canonical policy hash and O1d hash are disclosed in runtime/results. Existing
source policies and frozen reader bytes remain unchanged; approval provenance is
additive. Linux candidate preparation reuses every I1 feature flag with the
independently pinned v3 claim/native/table source policy; the frozen Apple I1 macro
remains unchanged. Parser jobs accept only exact shipped OCR native policies.
Every OCR page passes the hosted money/fence broker; unknown responses retain the
reservation and are never redelivered. Receipts and raw OCR bytes stay in the
private per-analysis ledger, never the research ledger. API result/review reads
use trusted cached pages only and cannot dispatch providers. Existing results,
receipts and revisions are preserved. Rollback: select a held reader or close
live admission on new runs; retain all readers, saved states and money/deletion
fences for historical replay. Holdout clearance is not Linux capacity/TLS proof.


## P7 amendment — profiles and provider quota failures (2026-10-09)

Hosted defaults remain `r108-default`, workers=8 and live-disabled. Operator choices
are `r108-default` / `r108-finals-candidate-v2`. Existing v1 configs still load for
compatibility, with an E2E5 regression warning; v1 is excluded from advertised choices.
V2 uses the frozen Q9 fallback bundle, excluding table-row extraction and recall.
Q8 `table-claim-spans-v1` remains a separate explicit local source-reader opt-in;
it does not replace the approved hosted Linux OCR v3 policy or change its gates.

OpenRouter HTTP402 (credit/key quota) and HTTP403 are classified conservatively as
operator-blocked provider failures: run `status=failed`, exact
`error_code=OPENROUTER_HTTP_402` / `OPENROUTER_HTTP_403`, `retryable=false`,
`error_message="분석 서비스 한도 초과 — 운영자 확인 필요"`. HTTP403 alone does
not establish the provider's precise cause. No HTTP body/key is exposed. The failure
fences the run, forbids publication/redelivery, and preserves unconfirmed spend in
`accounting_pending`. Timeouts and other unknown failures retain existing behavior.
The hosted frontend shows the Korean message, stops run polling on failed, and
blocks another start while an observed quota failure is displayed.

`GET /v1/runtime` adds `analysis_profile_options`, `analysis_profile_warning` and
`provider_limits.openrouter`: `status=unknown|blocked`, a safe classified error code,
`remaining_usd=null`, `source=not_queried|observed_http_failure`, `retryable=false`,
and a fixed message. It reads stored classified failures only: no provider calls,
keys, run/tenant identities, documents, or account details. `unknown` is not healthy.
Balance lookup is not enabled; remaining is not guessed. This is an observed status,
not a live balance or automatic recovery signal. Purging/restoring control records
may remove its observation; independent pending-spend admission guards still apply.

No DB migration: schema1 and prior immutable result revisions are unchanged. DTO
fields are additive; old readers still see failed and the safe code. Rollback new
work to `r108-default` and a schema1-compatible image/frontend; preserve volume,
budget reservations and deletion ledger. No automatic retry or ledger reset.
