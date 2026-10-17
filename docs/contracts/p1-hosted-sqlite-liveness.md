# P1 hosted SQLite and worker liveness

The hosted control plane and independent deletion/cost ledger retain schema v1,
their existing API fields, and their joint rollback-journal transactions. No SQL
migration or evidence-policy change is required. Archived readers, policy hashes,
run revisions, provider reservations and lease fences remain unchanged.

Connections use a 250ms SQLite busy timeout and at most 10 seconds of backoff per
acquisition or commit. Only SQLITE_BUSY is retried. Connection setup (including
ATTACH) may be repeated before the caller's body runs. A busy commit retries the
same open transaction; the body, files and provider transports are never replayed.
Read snapshots acquire both database read locks before yielding and reject writes.

WAL was evaluated and deliberately excluded for these two databases: SQLite
documents that [WAL transactions spanning attached databases are not atomic as a
set](https://www.sqlite.org/wal.html). Switching just one file would weaken the
run/admission/money/tombstone crash boundary. The server observation confirmed
DELETE journals. This fix keeps that boundary and shortens lock scope instead.

Source preparation/rendering use document file leases, release DB snapshots before
hash/copy/render work, and recheck current fences/authority before publication or
return. Publication stages receipt copies privately, then checks the fence and
renames on the same filesystem before writing the immutable result anchor.
Maintenance commits tombstones before purging; filesystem removal does not hold
the DB writer. Orphan directories are atomically detached under the writer and
removed outside it. Pending accounting is never erased to recover a slot or budget.

Continuous workers wait through busy initialization and catch maintenance/future
exceptions. They retain the run's existing lease and reservations; no uncertain
run or provider call is automatically redelivered. A transient busy lease heartbeat
keeps the same analysis process alive while its known lease remains valid. Lease
loss, memory and total runtime limits still terminate/reap that private process.

`python -m proofops_api.hosted_worker_health` reads the atomic heartbeat file and
one short read-only SQLite query without constructing HostedStore. It distinguishes
running, degraded, stale, stopped/missing, and unavailable observations; passing
the previous observation to `worker_health(..., previous=...)` detects a changed
worker instance. A loop older than 30s or active lease heartbeat older than 90s is
unhealthy. EC2 Compose checks this independently of API health; it does not restart,
cancel, resend, or settle a run. No server deployment was performed for P1.

Rollback stops/drains workers and selects the previous image with its matching
Compose healthcheck (the old image has no worker-health module); schema and saved
evidence remain compatible. The heartbeat/trash directories contain no evidence
policy or money state; do not delete pending trash as a substitute for retention
cleanup. New deployments must keep the existing source/receipt readers available.

HF4 keeps the schema, attached rollback journals and policy pins unchanged.
Hosted renewal alone now has a 30s BUSY budget (ordinary operations retain 10s);
it rechecks the persisted document/status/fence/expiry after acquiring the writer,
using monotonic elapsed time, and never shortens an already newer lease. Dispatch
reservation also rechecks expiry after waiting, before any charge or transport.
Response-cache authorization takes a read snapshot; broker reservation still
performs the authoritative write fence before every transport.

Hosted claim callbacks coalesce their unique counters to at most one write per
second, with an immediate first processed claim and an explicit final flush after
tagging, including partial results. These are advisory counters only: no budget,
reservation, receipt, authority or inner-job fence is batched. Abrupt process loss
can leave the latest unflushed counters absent; it cannot publish a result.
Initial result bytes and their fsync/hash are staged outside the writer, then the
same final fenced transaction installs the directory and immutable snapshot
anchor. Later review revisions keep their existing serialization. No migration is
needed; rollback restores the previous code without rewriting saved artifacts.

BUSY/slow-writer logs identify the control operation. Failed tag renewals also
retain the first exception type and numeric SQLite code in the existing immutable
usage record (`lease_heartbeat_failure`), distinguishing point and background
renewals even when the hosted child stderr is discarded. SQL, messages, paths,
provider content and credentials are excluded. These diagnostics do not change
failure handling, retries, job status, publication permission or accounting.

HF6 queues sibling heartbeats behind one process-local lock per job-store instance
so only one heartbeat waits on SQLite at a time. Queue time counts toward the
same 30s busy budget and persisted lease expiry. Identical heartbeat UPDATEs within
the same timestamp are suppressed. Every call still acquires the SQLite writer
and rechecks cancellation, owner,
attempt, fence and expiry; advancing time or requesting a longer lease writes the
renewal normally. Busy budgets and lease durations are unchanged.

`HOSTED_RETAIN_FAILED_ANALYSIS=true` is the production default. After reaping a
failed analysis child, while still owning the document file lease, the parent
keeps bounded diagnostic projections under the private document directory at
`analysis-failures/<run_id>-<fence>/`. Partial outcomes are retained too; completed
workspaces are cleaned normally. Each capture is limited to 128 MiB and 2,048
receipt files. A cross-process lock enforces a store-wide byte cap, configured by
`HOSTED_FAILURE_DIAGNOSTICS_MAX_BYTES` (default and maximum 512 MiB). Full capacity
or contention skips capture; diagnostics never authorize a retry or hide failure.

Only job/snapshot/usage and provider accounting tables plus internal receipts are
copied, not entire SQLite files or deleted pages. These projections are diagnostic
evidence, not resumable databases. Environment, live configuration, credentials,
identity/cursor tables, uploads and stderr are excluded. Dispatch failures record
role, request byte count/hash, phase, exception category, numeric SQLite code and
code location without exception messages. Point-heartbeat failures preserve the
same sanitized cause already recorded for background renewals. Directories are
0700, files 0600, and document purge removes the capture under existing ownership.
No public endpoint exposes these files. Disable retention with the flag above;
rollback requires no schema migration or policy rewrite.
