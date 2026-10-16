# RC1 published result reuse

DEC-136 / `tasks/ops-RC1.md`; based on v28 `e6b1a8fb`. No analysis-policy registry or default assignment changes.

Enable new admissions with `RC1_RESULT_REUSE_ENABLED=true` (default false under COORDINATION.md). The independent `rc1_published_result_v1` reuse policy is hashed. Disabling the flag stops new reuse while existing copies remain readable. Integrate the separate web commit before enabling it.

`POST /v1/runs` adds optional strict boolean `force_fresh=false`. Only an admin may set it true; it participates in idempotency and follows all normal admission/budget/provider checks. The existing editor, document owner, expiry, maintenance, PDF validation, CSRF and session gates remain in effect.

The key hashes original uploaded PDF bytes, the policy actually assigned to this request, every effective scope option (ordered evidence and claim pages, exclusions, scope policy, manual flags, completeness and assembly metadata), and validated report year/start/end. Account-bound proposal/selection/detection hashes are not portable: their scope validation remains mandatory, while their effective outputs are hashed. Provider concurrency is execution metadata, not a scope change. Missing policy/period pins cannot hit.

Candidates must be completed or positive-claim partial_blocked, result-ready, unexpired, undeleted and anchored in `result_snapshots`. Only sealed publication revision 1 is transferable: subsequent human revisions are tenant-specific. Both the options file and the sealed publication's policy/scope/period must match. Original PDF and all snapshot source hashes are rechecked. Corrupt, unpublished, failed, running, zero-claim and unknown-policy candidates miss. Existing v28 publications with these pins are discovered without a rebuild or server-side backfill.

Reuse creates a new run under the requester's separately uploaded document and ownership record. It copies the result and verified W16/W18 display coordinates, rebinds resource IDs, retains domain IDs/grades/unknowns, excludes account and operational metadata, and points original viewing at the requester's PDF. It copies no foreign runtime database, live review store or original file. Removing the originating document cannot break the new copy. The copied snapshot and its own PDF are checked on every result read.

Reused reports are immutable, read-only publications (`reuse.review_supported=false`; review writes return `REUSED_RESULT_READ_ONLY`). Human edits require an admin's fresh analysis. W16 original PDF and W18/W19 display coordinates are supported; the older parser-workspace source-page image endpoint is not materialized for copied reports. The current web PDF viewer uses the original PDF route.

The additive result object is `reuse: {reused:true, analyzed_at:<ISO UTC>, source_policy_sha256:<hash>, policy_sha256:<RC1 hash>, cost_usd:"0.000000", provider_calls:0, review_supported:false}`. No source tenant/user/run ID is public. `analyzed_at` preserves the original first-publication file timestamp across copy chains. Private `rc1_reuse_audit` records original run ID, original snapshot hash, analysis time, policy hash, key and copy time.

The existing SQLite writer transaction serializes reuse publication and idempotency. Each simultaneous distinct upload gets a distinct run; identical idempotency keys return one run. In-progress runs never seed reuse; simultaneous cold misses follow normal queue/budget rules. Reuse inserts no spend reservation/provider-cost record, consumes no daily execution count, and cannot be claimed by a worker. Copy provenance is retained for the configured audit period (at most 30 days).

Migration is additive/idempotent: `rc1_reuse_audit`, an immutable-update trigger, and `rc1_document_sha` index; no existing rows or snapshot bytes are rewritten. Backups include the new control table and owned snapshots. Roll back by disabling the flag while retaining RC1's reader for copies; a pre-RC1 binary lacks copied-PDF integrity and coordinate support and must not serve those runs. No dependency, cloud resource or provider binding is added.

Latency evidence is an offline synthetic PDF HTTP upload → new run → result check, including original-source hash checks. It is not a production-size throughput or model-accuracy claim. Large originals and cold W18 projection still require local I/O; the writer is held during a first copy, so source size and coordinate reconstruction determine admission latency.

Temporary W18 lock/timeout/reader failures return `429 REUSE_COORDINATES_BUSY` with `Retry-After: 2` before creating a run. They never freeze missing coordinates into the detached copy or fall through to a paid analysis. Retry with the same idempotency key; no count or budget is consumed.
