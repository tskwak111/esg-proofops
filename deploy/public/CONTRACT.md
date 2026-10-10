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
remote URLs are not accepted. Stream body capped at HOSTED_MAX_UPLOAD_BYTES=157286400,
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

## P8 amendment — direct OpenAI hosted provider (2026-10-09)

Hosted LLM provider defaults to `openai`; the operator may set `llm_provider` to
`openrouter` for rollback. `openai_key_file` and `openrouter_key_file` point to
private one-line key files; only the selected provider's key is required by the
runtime. The OpenAI request uses the pinned `gpt-6-luna` endpoint and passes each
attempt through `HostedStore.dispatch` with the existing per-call bound and receipt
settlement. HTTP401, HTTP429, and the provider error code `insufficient_quota` are
terminal operator-blocked failures with the same fixed Korean message as the
OpenRouter limit failures. They are not retried or redelivered; unknown spend stays
`accounting_pending`. Runtime status reads stored failures only and never probes a
provider. The default remains live-disabled and makes no request without operator
opt-in, configured key files, and the existing admission gates.

## HS1 / DEC-22 bounded unattended intake (2026-10-10)

This section supersedes the previous default scope and DEC-19 budget numbers.
New public HTTP runs default to `unattended-v1`; local launcher defaults and old
runs without an options sidecar retain their strict profile. Explicit
`X-Pipeline-Profile: strict-v1` is supported for rollback on new runs.
`HOSTED_RUN_USD=1.0`, `HOSTED_DAY_USD=7`, `HOSTED_EVENT_USD=7` are defaults and hard
ceilings. Reservations, accounting-pending holds, fencing, and Seoul day boundaries
are unchanged. Existing lower operator environment values remain lower until
explicitly changed; ledger totals are never reset by deployment or rollback.

After upload, POST `/v1/documents/{id}/scope-plan` generates free AS1 bounded-v1
inspection; repeated POST and GET return the current plan. It includes physical
pages, classification, reasons, snippets, original SHA, policy/proposal hashes,
unknown/conflict/unreadable pages, and a `declared_subset` selection. Claims <=10,
evidence union <=30; evidence-only pages cannot become claims. Inspection runs in
a 512MiB/60 CPU-second/90 wall-second child, sharing the cross-process upload slot.
No model calls or spending reservations occur during planning. A plan with no
readable environment narrative has status `failed` and cannot enqueue analysis.

POST `/v1/documents/{id}/scope-plan/selection` accepts only
`selected_claim_pages` and `selected_evidence_pages` with `If-Match: "<revision>"`.
ETag is exposed on reads/writes. Missing revision gives 428; stale gives 412.
Auth, tenant isolation, editor capability and Origin/CSRF apply to every write.
Each edit appends `scope-<revision>.json`; previous proposals/edits stay unchanged.
POST `/v1/runs` without `selected_pages` uses that plan; optional
`scope_selection_sha256` rejects stale submissions. Explicit `selected_pages`
continues to accept <=2 pages for legacy clients. Scope and pipeline profile are
pinned in a new immutable-by-application `<run>.options.json` sidecar. It carries
its canonical hash; selection/page-map agreement is checked on reads. Sidecars
live inside document payloads, follow existing backup/purge policy, and contain no
credentials. No DB schema migration or dependency change is required.

Prepared PDFs contain the evidence union; original physical claim pages are mapped
to prepared PDF indices for `--claim-pages`. Before MP1 integration, all selected
pages still use brokered Upstage synchronous <=2-page batches with distinct receipts
and validated page remapping. This is not mixed parsing. MP1 can use the same
options/claim-pages interface; no active MP1 files were imported.

Result snapshots preserve `source_status`, `provisional_grade`, `pipeline_stage`,
`pipeline_status`, and scope hashes/maps. Provisional grades remain read-only and
separate from `decision`/`confirmed_grade`. Unknown/conflict/unreadable stay unresolved;
no unverified `present` is admitted. The UI shows 원문 확인 필요, 잠정·미확정,
phase/progress, hold/error codes, and budget_unanalyzed reasons. A terminal completed
run means selected-scope processing ended, not full-report certification.

The initial HS1 intake measured only <=50 MiB reports. FX3 replaces that ceiling
with disk-streamed **150 MiB /300 pages** originals and page-backed hosted scope
inspection; see the FX3 contract and measured memory evidence below. Offline AS1
research inspection retains its separate 100 MiB limit.

Rollback: stop admission and drain new jobs before using an older worker; it does
not understand options sidecars and would treat evidence-only pages as claim pages.
Retain new result readers and scope files. Web rollback uses explicit
`VITE_ANALYSIS_BACKEND=static`; a new strict run uses the header above. Do not rewrite
stored provisional results into confirmed revisions.

HS1 adapter detail: typed internal `BudgetExceeded` now survives OpenAI/OpenRouter
and synchronous Upstage error sanitization; other errors remain sanitized. This
allows PT1 to stop further claim calls and preserve budget_unanalyzed results.
Stage failures distinguish page preparation from analysis-worker failure and retain
safe provider/hosted reason codes. Scope writes enforce editor capability both at
HTTP authorization and storage entry points.

### HS2 unattended recovery (2026-10-10)

The provisional result key is `provisional_grade.evidence_grade` (E0–E3 or null),
with `grade_range.open_elements`, reason and provisional track kept separate from
confirmed decision fields. A completed zero-claim selection means no environmental
claim was found in that selection; blocked extraction is a separate outcome.
Failed automatic scope proposals remain immutable, failed and unverified. An editor
may save a new If-Match revision with a bounded manual selection (claims≤10,
evidence union≤30); `selection.manual_override=true` is hashed and pinned in run
options. Physical bounds, strict integers, subset membership, original identity and
proposal hash remain mandatory. Original unknown/conflict/unreadable classifications
are preserved; manual selection never grants evidence admission or absence rights.
Disabled live runs publish a genuine partial_blocked snapshot with zero claims and
LIVE_BINDING_UNAVAILABLE. Parser budget denial is budget_unanalyzed/BUDGET_EXHAUSTED,
not ANALYSIS_WORKER_FAILED; no missing source is fabricated as absent.
Pipeline timeout is1800s (measured30-page runs605s/406s); lease1900s renews every30s
while the parent waits, and on stage updates. Expired workers lose their fence.
An intact independent spend ledger and zero cost rows prove zero provider dispatch;
only those expired runs automatically settle zero and release the queue. Every
recorded dispatch retains the reconciliation guard, including uncertain charges.
Operator reconciliation is dry-run by default, requires an exact call identity and
actual cost per recorded call (settled costs must match exactly), an operator reason,
and the SHA256-matched provider export. `--apply` settles only unresolved rows,
preserves a private immutable receipt,
and closes the old run; it never replays requests or changes provider availability.
No new API route, DB column migration or dependency. Optional DTO additions leave
previous results unchanged. Rollback: close admissions, drain workers, retain all
snapshots/receipts and independent ledger; failed manual scope requires the HS2
reader, and must not be sent to an earlier reader for new execution.

### HS3 · integrated finals profiles (temporary default)

New public requests select `finals-unattended-v1` or `finals-unattended-v2` using
`X-Pipeline-Profile` and the web profile selector. Omitted header uses the operator
`analysis_profile`, otherwise one setting `HOSTED_ANALYSIS_PROFILE` (temporarily
v2; coordinator decides after QI2). Legacy strict/unattended and explicit R108
operator profiles remain readable. New immutable options pin the chosen profile
and analysis-policy SHA; old run options/results are not rewritten. Profile hash
mismatch blocks preparation. The selected original-to-prepared page map is retained.
Linux claim verification uses the independently approved OCR v3 policy, pinned in
the run snapshot. EV1 native render checks require Apple Vision; on Linux those
spans stay unresolved rather than being promoted. ODL itself runs offline on
Linux/amd64 with Java 21 and the locked bundled 2.5.7 jar; no new dependency.
The existing hosted broker is the only run/day/event money authority. INT1's local
SpendGuard is not installed around hosted workers; v1 overlapped tag composition
inherits the same hosted factories and private ledgers. A single envelope reserves the
run at intake; each parser/model/OCR dispatch is a subreservation, not extra day
spend. Async parse reserves pages × pinned standard .011 / enhanced .033 (VAT),
polls scheduled jobs without reposting, and retains uncertainty/fencing guards.
At 10 claim pages, standard+all enhanced costs at most .440; mixed evidence OCR
fallback defaults to zero. Linux rendered OCR for 30 selected pages costs at most
.04950 (one cached request/page), leaving .51050 of the USD1 run envelope for models.
The 30-page OCR allowance replaces the obsolete two-page allowance only for larger
frozen scopes. Failed receipts retain reservations; totals cannot exceed DEC-22.
No SQL column or route migration. Optional DTO presentation adds hold reasons and
needed evidence. Old readers must not execute new profiles. Rollback: select v1 or
`r108-default` for new runs, drain workers and retain all options, checkpoints,
receipts, revisions, immutable reports and cost rows. Never downgrade a pinned run.


## FX3 — streamed originals and isolated accounting uncertainty (2026-10-10)

This section supersedes the earlier 50 MiB intake ceiling and global pending-accounting
queue stop. POST /v1/documents streams to a private disk file, defaults to / is capped
at 150 MiB and 300 pages, and retains strict object/action/password checks. The strict
validator caps cumulative decoded bytes at 512 MiB, clears decoded stream caches, and
retains its 512 MiB address-space, 20 CPU-second and 30 wall-second guards. The API
container stays at 512 MiB; the one upload/scope slot and worker's 2560 MiB cap remain.
Selected preparation uses disk source/target files; only <=30 selected pages (claims<=10)
enter later analysis, with an independent prepared-file limit of 50 MiB.

Free scope inspection uses file-backed PDFium page/text handles, closes them per page,
records method/parser version and skipped/unreadable pages, and retains AS1 selection
hashes and If-Match. Scope proposals remain unverified; no evidence readers are changed.
A killed/failed scope child publishes an immutable failed plan with front-three suggestions;
manual selection requires a new CAS revision and preserves unknown/conflict/unreadable.

OpenAI/OpenRouter network errors retain call and full run-envelope reservations. They
return PROCESSING_UNCERTAIN, keep the owning run's fence valid for partial publication,
and hold only its affected claim with no grade. There is no network redispatch. Reuse of
the same call/request ID is refused; schema retries after a received response remain
separately reserved. OpenAI's broker request UUID is also sent as X-Client-Request-Id
for operator tracing, not as a billing-idempotency guarantee. Unknown receipts, parser/OCR
failures and quota failures retain their terminal behavior. Pending accounting occupies
only its budget and per-user outstanding-run limit, not the global worker/admission slot.
Day/event caps count the full pending envelope; HS2's dispatch-zero expiry release is unchanged.

Operator reconcile accepts published completed/partial_blocked runs as well as
previous terminal accounting states; export hash, exact call identities/set, amount
bounds, settled-cost equality and immutable audit are unchanged. Settlement does
not change the published run status or result snapshot.

API fields, SQLite schema and immutable snapshot formats are unchanged; no DB migration.
Existing snapshots/receipts are not rewritten. Rollback restores the earlier code and
50 MiB proxy/env cap; preserves all pending reservations and snapshots; old code may
again stop queues on pending accounting and refuse >50 MiB uploads. Existing large
originals stay stored until authorized deletion/expiry. Stop assigning new scope work
to the old inspector when rolling back. Real provider/AWS/production TLS checks are not_run.

## FX4 amendment — evaluator quota, money isolation and running progress (2026-10-10)
This amendment supersedes user2/day: `HOSTED_USER_DAILY_RUNS` is a positive integer,
default6; global10/day, active1, queued8 and user outstanding1 remain unchanged.
The run/day/event ceilings remain USD1.0/7/7. Parse, chat and page OCR use private
per-run ledgers and every actual transport uses HostedStore.dispatch. Hosted profiles
do not authorize Decisions; a hosted composition with decision_settings fails closed
with HOSTED_DECISION_BINDING_UNAVAILABLE before research keys/ledgers are composed.
Research adapters, historical ledgers and R108 guards remain unchanged.
RB2 Hyundai's R108_BUDGET_EXHAUSTED was a misleading prefix on the extractor100-call
stop, not evidence of a research cumulative-budget check: its private chat ledger
contains100 settled calls. New hosted snapshots allow at most2000 extraction calls
(the existing finite preparation ceiling); no new monetary allowance is granted.
An extraction stop retains partial coverage and still attempts tagging of extracted
claims through the broker; outcome remains partial_blocked with the actual stop code.
Existing snapshots and stored R108 codes are not rewritten. Replica3, evidence/source
admission, tenant and revision contracts are unchanged.
GET /v1/runs/{id} adds optional-compatible `claims_extracted` and `claims_processed`
(nonnegative counts; processed includes terminal blocked claims, not decided grades).
Publication reports stage=result/progress=.95 before source validation; result_url
stays null until the immutable snapshot commits. No claim text or early grade is exposed.
Migration: startup creates additive run_claim_progress in hosted schema1; existing
rows read as0. Updates require the live run fence; cancellation/deletion still fences
writes and deletion removes count rows. Older readers ignore the table/extra fields.
Rollback: stop acceptance and worker, revert FX4 code/images and explicitly set
HOSTED_USER_DAILY_RUNS=2 for a compatible quota-aware release if desired. An older
release ignores that env and uses2. Preserve2000-call frozen snapshots; rollback
does not rewrite run budgets, evidence, reports, reservations or deletion records.
New code reads old100-call snapshots unchanged. Public deployment/live evaluation is
outside FX4; no provider/AWS calls are required for stored-result replay.

FX5 adds `upstage-ocr-page-v5` for new Linux runs; v1–v4 implementations and
policy hashes remain intact. v5 retries only a v4 `rendered_quote_unresolved`
claim using the approved v3 Upstage mapping with identical SV1 literal, quantity,
visibility and EV1 layout guards. It records the successful reader per claim;
failed/pending/missing OCR stays unresolved. The document-scoped page cache
retains failed reservations and prevents repeat POSTs. Hosted fallback admits
only prepared claim pages (original-page mapping), at most ten per run, and
reserves standard USD0.011/page inside the existing run/day/event envelope.
Settlement uses the existing OCR USD0.00165/page price snapshot; a cached page
has no additional provider call. Evidence-only fallback is off.

Luna element tagging reserves two per-response outputs before a logical dispatch
(max_tokens4096 → reservation8192); wire requests still cap each response at4096.
New role/context and aggregate output limits accommodate this bound. Actual
usage is settled unchanged and provider-overrun fencing remains mandatory.
Existing snapshots, token limits, ledgers, revisions and publications are never
rewritten; an old insufficient budget cannot silently expand on resume. Create a
new authorized bounded run instead. No API/DB column migration or dependency is
required. Roll back new reader assignment to v4 while retaining v5 replay code
and the corrected retry reservation; reverting that reservation restores RB3's
known overrun defect. Paid pipeline and hosted deployment remain not_run.

## PA1 amendment — bounded worker concurrency and provider causes (2026-10-11)

`HOSTED_MAX_ACTIVE_RUNS` admits only 1 (default) or 2. The existing single worker
CLI drives that many isolated analysis subprocesses; claims use the same atomic
writer transaction. Two runs of one tenant/document cannot hold active slots
together. Document locks, renewable fenced leases, user outstanding limits and
USD1.0/run, USD7/day/event reservations and settlement remain mandatory.
With two slots, each analysis/parser/OCR process tree is sampled every two seconds
and stopped above 1100 MiB RSS (`ANALYSIS_MEMORY_LIMIT`). Timeout, lease failure and
exit reap its private process group so inherited document locks do not survive.
The existing 2560 MiB worker cgroup remains the aggregate hard ceiling. Sampling
is a guard, not a proof of Linux peak memory; a target-host canary is required
before the coordinator enables two slots. No deployment is performed by PA1.

New v2 snapshots pin `exact-verified-read-v1`: successful cold recomputation may
be reused only for identical tenant, source bytes, graph, discovery, receipt,
reader policy, runtime/toolchain and read profile. Concurrent identical cold
reads coalesce. Process-only serialized results are bounded to four entries /
32 MiB; failed or unavailable reads are not retained. No provider responses,
replicas, admissions, unknown states, grade rules or published revisions change.
The pre-PA1 HF1 profile hash remains an accepted historical policy. Older snapshots
keep caching disabled; original OCR/verifier files and receipt policies are intact.

Provider failures retain uncertain costs and envelopes as accounting_pending.
Upstage 403 with bounded JSON code api_key_is_not_allowed records
PROVIDER_CREDIT_EXHAUSTED; 401, other403, 429 and 5xx record PROVIDER_AUTH_FAILED,
PROVIDER_ACCESS_DENIED, PROVIDER_RATE_LIMITED and PROVIDER_UNAVAILABLE. Raw bodies
and keys are never exposed. Existing OpenAI/OpenRouter limit codes stay stored
unchanged; compatible optional provider_error_code/provider_error_message fields
give the specific cause. Accounting-pending runs stop polling and show the cause;
a later LEASE_LOST cannot overwrite it. The parent logs the retained cause once.

No SQLite column migration or new application dependency is required. Rollback:
stop new acceptance, drain/stop both slots, set HOSTED_MAX_ACTIVE_RUNS=1 and stop
assigning new PA1 profiles. Retain the new policy reader for saved PA1 snapshots;
an eae1599 reader rejects their new hash. Preserve all costs, receipts and revisions.

## PA2 amendment — extraction execution and checkpoint settings (2026-10-11)

New v2 analysis policies pin `exact-verified-read-v2`. A whole v6 claim attestation
just produced by the trusted source reader may satisfy immediate replay only when
its canonical bytes, ordered refs, run, tenant, source bytes, graph, current reader
policy, runtime/toolchain and read profile match. The projection uses the existing
byte-pinned replay tail. Fresh receipts share PA1's four-entry / 32-MiB process-only
bound with replay results; transient/unavailable reads retry normally. Historical
PA1 and earlier policy hashes remain readable with their original execution path.

Under this new policy, the first prepared page's LLM calls overlap preparation of
the remaining pages in the existing isolated CPU pool. Discovery consumes source
order; tagging still waits for the complete source-attested extract snapshot.
The pre-call owner/cancellation/fencing check and lease renewal use one existing
heartbeat transaction. Reservations, response fsync and settlement remain atomic
per provider attempt; 429 handling and uncertain-cost stops are unchanged.

Operator JSON may set `llm_max_workers` (1–16, default 8) and `extract_batch_calls`
(1–256, default 20). A larger batch groups checkpoint publications, not money
reservations. The existing `extraction_limits.max_calls` contract freezes that
window when preparing a NEW run; resuming a stored run cannot enlarge its limit.
No public request field, DB migration or dependency is added. Rollback: prepare
future runs with the PA1 builder/defaults while retaining PA2 readers for existing
PA2 snapshots; the PA1 binary rejects their new policy hash. No deployment or
server setting change is performed by PA2.

## PA3 amendment — whole parse proofs and tagging fences (2026-10-11)

New v2 analysis snapshots pin `exact-verified-read-v3`; the previous PA2 hash
remains an accepted frozen policy with its original execution path. V3 extends
the same four-entry / 32-MiB process-only bound to whole native-v6 and EV1 OCR
attestations produced by the trusted parser. Reuse requires identical canonical
receipt bytes, tenant/run provenance, original PDF, complete graph, current
reader/runtime/toolchain and read profile. Unavailable/error reads retry normally.
Source verifier files, source receipt schemas and stored snapshots stay intact.

Cold EV1 OCR replay performs one complete source attestation and compares every
receipt field before projecting the byte-pinned original replay tail. It retains
the BASE receipt's span identity, table membership and unresolved binding state.
Transient reads and unknown reader builds retain the original replay path.

V3 combines the tagging call's owner/cancellation/fencing check and lease renewal
in the existing atomic heartbeat transaction. Provider reservations, dispatch
markers, response fsync and per-attempt settlement remain separate and mandatory.
Each tagging ensemble still has three distinct replica IDs and responses; packet
freezing, consensus, citation restoration and pure Python grades are unchanged.

No public API field, DB migration, dependency or server configuration is added.
Rollback stops assigning V3 to future preparations while retaining its reader for
saved V3 snapshots; a PA2 binary rejects the new hash. PA3's two-slot experiment is
offline: actual admission, locks, leases and 1100-MiB per-process-tree guard apply,
but imported original-provenance fixtures are never published as new analyses.
Container memory is requested as 16 GiB; actual VM memory and sampled RSS must be
reported separately. No deployment or real provider call is performed by PA3.

## PI1 amendment — multiple reports from one invitation (2026-10-11)

One redeemed invitation/session may upload and enqueue multiple documents.
`HOSTED_USER_ACTIVE_RUNS` is a positive integer (default 1; finals setting 5).
It limits a user's running slots across tenants, within `HOSTED_MAX_ACTIVE_RUNS`.
Excess work stays queued, rather than returning USER_RUN_LIMIT. The active count
includes queued, running and accounting_pending; pending accounting is retained
but occupies no processing slot. Dispatch selects the oldest eligible queued run
by created/run_id, preserving the same tenant/document exclusion and fenced lease.
The eight-entry global queue is still a hard admission limit. Admission reserves
the full run envelope even for work beyond the user's running-slot limit.

`HOSTED_DAILY_RUNS` is a positive integer (default 10), replacing the global daily
count literal. HOSTED_USER_DAILY_RUNS (default 6), USD1/run and USD7/day/event,
provider reservation/settlement and archived spending remain independent gates.
Idempotent retries replay before admission gates and never reserve twice.
Runtime limits add user_active_runs/daily_runs; user_outstanding remains as a
compatibility alias for the configured soft window. Run projections add
user_active_count (including accounting_pending) and user_processing_count.
No database schema migration, request change or dependency is required. Old run
records and immutable results remain readable. The web keeps document-local
scope, status, result and error state, and polls each accepted run independently.

Rollback: close new acceptance, drain queued/running jobs, retain unresolved
costs and all saved profiles/results, set HOSTED_USER_ACTIVE_RUNS=1 and
HOSTED_DAILY_RUNS=10. These values restore processing/count defaults; queueing
remains supported. A binary rollback to b523dd2 restores USER_RUN_LIMIT, so first
drain multi-document work and use its matching frontend. Never reset accounting
or budgets to unblock a user. PI1 performs no deployment or paid provider calls.
