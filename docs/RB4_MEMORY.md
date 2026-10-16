# RB4 receipt buffer lifetimes

Select `analysis_profile.RB4_STREAM_POLICY` by its explicit canonical hash for new runs.
The final opt-in hash is
`d9599dbe30aa9fd53852b938b0055a1ac3b79932d7f498b045c820b301dfe013`.
It composes RB1 input isolation and RB3 deadline admission/source execution with
`rb4_memory.POLICY` and `rb4_memory.PUBLICATION_POLICY`. The earlier
`RB4_POLICY` remains registered for replay. The public default, historical policies, source reader bytes,
receipt schemas and persisted checkpoint bytes remain unchanged.

Large source attestations contain nested page proofs. A Samsung fresh simulation's
first 207-claim extraction checkpoint was 132,334,376 bytes; decoding it allocated
398,868,031 bytes in the JSON decoder. Keeping the previous decoded attestation
through construction, serialization and replay of the next revision multiplies
the live memory requirement. Source verification itself must still run in full.

The opt-in changes only ownership/lifetimes:

- After checkpoint digest verification and decoding, release its serialized bytes.
  After parse/discovery verification, release the serialized parse checkpoint.
- After continuation replay and head/cancellation/lease checks, retain the prior
  per-source response receipts and RB1 holds, and release the prior proof envelope
  before dispatching the next batch. The immutable stored revision remains intact.
- After complete source replay and construction of tag pins, retain the metadata,
  discovery and coverage used by tagging and release the decoded source proof.
  Use the already-verified checkpoint digest without eagerly evaluating a fallback
  full-envelope hash. Missing pins retain the original fallback behavior.
- At publication, compare the already-admitted envelope's canonical digest with
  the verified stored checkpoint digest before decoding another copy. Retain the
  original semantic comparison as a fallback for noncanonical JSON formatting.
  Release the admitted proof after outcome projection; keep discovery and the
  verified graph for the unchanged per-claim projection and evidence checks.
- The private handoff's authoritative-state check sorts only row keys, then hashes
  each complete value under the same SQLite read transaction. It retains every
  authoritative row, the original cache exclusions, before/after checks and all
  source/runtime/tenant/fence pins. Old policies retain the original query.

No receipt field is omitted from storage, no cache is trusted without the existing
source checks, and no claim, tag, rule input or decision is changed. There is no
new dependency, persistent cache or schema migration. RB3's TIME_BUDGET holds and
hard deadline remain in force. A helper alias also preserves RB1 error reasons
when both branches are merged.

The fresh gate requests the same 12 GiB/6 CPU worker caps as the inspected server.
The local Docker VM, however, has only 8,321,515,520 bytes of total RAM shared by
all containers; the server has 16,425,922,560 bytes. A requested cgroup limit above
the local VM's physical memory does not provide a dedicated 12 GiB budget.
Validation must record process-tree RSS and cgroup peaks and distinguish host
contention from a worker's own cap. The task does not change either environment.
The first candidate reached publication with a 2.75 GiB sampled cgroup peak but
was OOM-killed while other workers used almost 4 GiB. Its trace also exposed the
publication outcome's second full checkpoint decode, addressed by the final
opt-in. That failed run remains recorded separately from acceptance evidence.
An isolated comparison on the actual 132,334,376-byte checkpoint measured peak
RSS of 1,390,936,064 bytes before and 745,783,296 bytes after this publication
change (Darwin, fresh processes), with identical outcome-projection hashes.
This isolates the duplicate decode; it is not an end-to-end latency measurement.
The next fresh Samsung run published 307 TIME_BUDGET holds in 1,596 seconds
without OOM, but its child handoff exposed a second resource failure: sorting
553,843,861 bytes of job-record values into a 536,870,912-byte tmpfs raised
SQLITE_FULL. Sorting only keys fixes that failure without increasing the cap.
A bounded regression using 64 MiB of records and 16 MiB of tmpfs reproduces the
old failure and proves that streaming returns the identical authoritative digest.

The final matched LG13 fresh pair retained 184 claims and identical compared
domain results. Candidate/baseline stage-time ratios were 0.9948 parse, 0.9977
extract, 0.9892 tag and 0.9477 publish, all within the 5% regression limit.
Sampled worker process peak RSS fell from 1,001,410,560 to 776,466,432 bytes;
cgroup peak fell from 1,868,615,680 to 1,412,452,352 bytes. The pair shared a
global two-call simulation limit. An earlier serial pair was 7.67% slower in
parse; its failure remains recorded alongside the matched runs.

Final original-PDF fresh runs used the same automatic scope as RB1. All passed
the 1,800-second publication bound, anonymous-FD child handoff, cold-restart
byte equality, source preservation and cost-settlement checks without OOM.

| Case | Published claims | TIME_BUDGET holds | Seconds | Process RSS peak (GiB) | Cgroup peak (GiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Samsung | 307 | 307 | 1424.77 | 2.154 | 2.940 |
| Hyundai | 405 | 349 | 1386.20 | 2.208 | 3.039 |
| Kakao | 415 | 326 | 1372.89 | 1.558 | 2.925 |

RSS is sampled every two seconds; cgroup peaks include file cache. Function
entry/exit samples and phase summaries are retained with the raw traces.
These are partial deadline publications: Samsung stops extraction early,
and Hyundai proceeds beyond the 390-claim checkpoint where RB1 had failed.
No confirmed grade or scope confirmation is introduced. Memory-path byte
equivalence is separately tested with identical inputs and completed caches.
Detailed acceptance, timing protocols and failed diagnostic runs are recorded
under `outputs/agent-results/R108-redesign/lab/robust/RB4/` in the parent checkout.

Rollback stops assigning RB4 to new runs while retaining its registered policy
for existing artifacts. Integrate by adding the memory policy fields under a new
v26 pin and preserving its chosen source reader; do not replace existing hashes.
Fresh simulations validate plumbing and resource behavior, not model accuracy.
