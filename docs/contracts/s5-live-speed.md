# S5 live execution profile

`S5_LIVE_POLICY` is an explicit hash selection on `finals-unattended-v2`, based
on `FINALS_I26_POLICY`. V26 remains the default. Existing registry entries,
source readers, SC1 assembly, three-vote consensus and grade rules are retained.

The S5 source reader ports S4 (`dda6075`) policy-DAG evaluation and bounded raw
ROI caching. Its private policy snapshots are checked against live identities at
both read boundaries. Raw cache entries remain scoped to tenant, run, policy,
source and crop; cached text is still subject to source verification and receipt
replay. The extraction dispatch batch increases from 100 to 256 without changing
model requests or verification.

The result reader explicitly includes the S5 pin in V26's occurrence-group and
table-source annotation lists. Opting in must preserve these presentation fields
as well as evidence, tags and grades.

SC1 parallelism is across independent chunks, bounded by the existing runner
worker limit and provider scheduler. Each chunk still obtains replicas 1, 2 and
3 serially, preserving `max_replica_workers=1`. Every request retains its own
authorization, budget reservation, lease checks and durable settlement. A fatal
stop suppresses subsequent invocations; already admitted calls can finish. Thus
failure-time call ordering/counts can differ from serial execution. Missing or
invalid responses remain unknown/uninspected; they never become absent evidence.

S5 accumulates reporting request IDs and reads their settled ledger projection
once at tag exit, including exceptional exit. Money reservations, dispatch
fences and per-call durable settlement are unchanged. The final projection still
rejects corrupt records and reports unsettled costs as unknown. Abrupt process
death retains the same durable per-call ledger for recovery.

S5 C3 sends its existing required vote JSON schema in the system prompt and binds
that prompt to a new policy hash. Previously `schema_json` was only a local
validator input; the transmitted prompt omitted the required object shape.
Invalid S5 schemas are classified as `C3_CURRENT_RESPONSE_INVALID` before
transport authentication. Valid responses still require the unchanged current
request, raw sidecar, ledger, source and three independent vote checks. Legacy
C3 wire/prompt hashes and replay remain unchanged. This corrects the contract;
offline tests cannot establish real-provider compliance or model accuracy.

The fresh LG13 harness supports bounded batch selection and optional timing. It
keeps fixed thresholds, network isolation and fresh generated responses, records
failed-run audit evidence and keeps its local session alive during long runs.
Inclusive function timings overlap and must not be summed as stage wall time.

Rollback consists of selecting the existing V26 hash for new runs. S5 artifacts
retain their original policy; they must not be relabeled as historical results.
The live E16 HTTP 503 remains an uncertain provider failure: this change neither
releases its reservation nor invents recovery or a successful result.
