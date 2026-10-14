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
