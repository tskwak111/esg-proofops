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
