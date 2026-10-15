# S3: bounded page parsing on the v23 policy

`s3_finals-20261015-speed-v1` is an explicit opt-in derived from v23. The default
remains v23. The analysis-policy differences are the integration name,
`parser_failure_policy=s3_partial-v7` and `verified_read_cache=s3_exact-verified-read-v13`;
these produce a new analysis and parser hash.
Historical policies, source-reader files, source receipts, request replicas and
rule-engine decisions are unchanged. No API/DB migration or dependency is added.

E9 issued one eight-page Upstage job (12.18 seconds). E13 and E14 use the P2
single-page layout recovery path, issuing eight serial jobs (74.16 and 70.96
seconds). The 16-worker/8-RPS setting governs the LLM scheduler, not these parse
requests. All three parse runs were cold. E14's one local JVM batch and two
configured OCR processes do not indicate a reduced process cap. Historical
parse receipts do not separately time native/table/evidence proof; the remaining
128.36 seconds cannot be assigned precisely to those functions from these logs.
File timestamps narrow that remainder: graph-to-manifest grew from 3.48s to
19.25s (table attestation/replay plus manifest work); manifest-to-extract enqueue
grew from 39.84s to 73.28s (verified reload and native/evidence proof plus commit).
These are boundary estimates, not profiler measurements. E13/E14 worker cgroup
logs show zero CPU throttling and zero OOM kills; E14 peak memory was 1.69GB.
Increasing the existing 6CPU/12GiB limits therefore has no supporting evidence.

The server snapshots expose a second concrete cause: E14's native/table mode is
v21, while I21's local parse benchmark uses v20. The v12 parser reader-scope,
table adapter and single-whole-replay branches admit v19/v20 only. Consequently,
E14 falls through to legacy nested proof despite selecting v12 execution. The
claim path already admits v21 and is not the same missing branch. New v13 admits
the registered v21 native reader to the existing instance-private execution and
whole-receipt recomputation. `s3_table_replay.py` has a new byte pin; I21/S2/frozen
reader bytes are untouched. Fresh results can seed the existing process-only
bounded cache only after real attestation. Cold reads still recompute every
record and match the complete receipt hash. Rehashed forgeries fail. D2 table
acquisition holds go through D2's original reader on every read without caching;
historical table-policy preimages retain their original replay path. Claim
execution, terminal-batch stop and private publication handoff retain their v12
behavior under the additive v13 registration.

`s3_partial-v7` keeps the same single-page requests, provider-first claim layout,
readable native fallback, original-source verification and failure records.
It dispatches at most four requests per wave with copied caller context. Each
request independently reserves its cost through the existing SQLite transaction.
PDFium subsets are serialized under a per-parser lock. The entire wave finishes
before candidate grounding starts; no PDFium handles cross threads. Results and
receipts are consumed in physical-page order. Already reserved responses are
retained after a terminal stop; a later wave and subsequent retries are stopped.
Explicit transient failures retain the existing two-attempt ceiling; ambiguous
paid failures are not retried. Cache integrity, tenant scoping and source checks
continue to apply. The prior partial-v5/v6 replay paths remain available.

Tagging already parallelizes claims while serializing each claim's replicas to
stay inside the shared provider cap. E14 reached 16 active transports, without
429s or failed calls. Its mean preliminary/element latency rose from E9's
1.78/3.12s to 2.83/3.86s, and relation calls rose from 36 to 75. This change does
not reduce replicas, omit relation work, or raise the provider/RPS ceiling.
Queue time is a sum across overlapping requests, not elapsed stage wait.
The first-to-last tag transport span grew from 158.99s to 190.46s (+31.47s);
the remaining stage time outside that span grew from 10.94s to 37.91s (+26.97s).
Historical events cannot attribute that remainder to individual proof/prework/
postwork functions, so the model timing increase alone is not the full explanation.

The offline E14 replay uses saved response bytes and their recorded delays with
real native candidate grounding. After excluding generated parser-run IDs,
candidates, routing, response receipts and failures must match. This establishes
candidate equivalence for this input, not a new model-quality or live latency claim.
The fresh v21 native-proof replay fell from 124.70s to 72.60s (-41.8%) with
identical output on the E14 graph. Table cold replay was 16.64s to 17.57s, so this
sample does not demonstrate a table cold-speed gain. Those native proof timings
are local macOS results under shared load, not additive server stage estimates.
The observed 52.24s page replay saving suggests about 51–52s of parse reduction if
server service times remain stable; it does not imply the full run is under 7min.

For a separately authorized server validation, pin v23 and the new policy to the
same LG13 original SHA and selected/claim pages. Start with offline saved-response
runs in isolated workspaces on the same 6CPU/12GiB image. Record cold and warm
runs separately, and phase times for JVM/subset, provider submit/poll/download,
native/table/evidence attestation, extraction verification, tag prework/transport/
postwork, and publication cold replay/FD handoff. Preserve request queued,
admitted, transport-start and completion times with claim/replica IDs. Check
peak parse requests <=4, LLM <=16, RPS <=8, and actual OCR process/OMP counts.
Compare claims, all three replica receipts, evidence refs, unresolved states,
source-verification results and decision artifacts; model nondeterminism must
not be mistaken for a scheduling regression. Live calls require separate budget
and deployment authorization. Stop rollout on a cost/lease/source mismatch or
quality regression. Rollback stops new S3 admissions and routes new work to v23;
retain s3_partial-v7 readers and immutable artifacts for existing S3 runs.

Coordination: all new policy identifiers carry the S3 prefix. Registry additions
leave historical entries and default selection unchanged. The API module change
only admits the S3 execution policy to the existing private publication handoff;
no API or snapshot field is added or changed. Per the final coordinator update,
full pytest deferred to I24 integration; S3 stopped its serial-lock wait and uses
focused/related tests plus changed-file lint, format and type checks. Integration should merge additive policy registrations and
execution-policy guards with other branches, retaining their task-prefixed entries.
Recorded offline timings precede the identifier-only coordination rename; the
execution behavior is unchanged, and the namespaced focused tests cover dispatch.
