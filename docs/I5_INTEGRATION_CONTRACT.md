# I5 integration contract

New runs use `finals-20261012-v5` under `finals-unattended-v2`. The immutable
I1/I2/I3/I4, H1, S1 and S2 policies remain explicitly hash-selectable. Rollback
assigns new runs to the I4 hash; it keeps v5 readers and stored artifacts.

V5 composes I4 identity-safe selection/prompts and the S1 parse replay scope,
H1 selected-page Java input, original-cell context and boundary recovery, and
S2 scheduling/call allowance. The new exact-verified-read-v7 cache additionally
pins the unchanged v12 reader bytes. Whole receipts, source/tenant/run/graph,
references, reader and runtime hashes must match; cold replay recomputes the
whole proof offline before projecting its unchanged owned-cell tail. H1's
heading proof still executes; only its inherited raw OCR reads are scoped.
A failed source/grid/visibility check remains unresolved/candidate.
The v5 grid failure policy converts only J8 missing/invalid/overlapping table
grids into a source-local extraction failure with an unknown exclusion; all
other identity/integrity errors still propagate. Old pins keep their old behavior.

The deployment recommendation uses extract_batch_calls=100 (within the existing
256 ceiling) to avoid repeating whole source checks every 20 inputs. Explicit
operator values remain authoritative; the run freezes its actual batch limit.
The hosted default is 16 HTTP workers for v5/S2. An explicit operator setting
wins. Tagging reserves at most min(2000, claim_count*27) calls, dispatches verified
quantitative/target claims first, and publishes in original source order.
Existing per-call USD reservations and the production USD1 run ceiling remain
in force. This is a bounded call allowance, not unlimited document completion.

There is no public API/DB schema or dependency migration. Old frozen verifiers,
rule packs, source decisions, revisions and reports are never rewritten. LLMs
extract/tag; pure Python grades. Unknown/conflict/unreadable are not absence.
Numbers/years still require directly verified claim or same-table evidence.

I5 evaluation uses disposable copied streams. Historical UUID selections are
replayed as literal source selections; they are never admitted as fresh cN
provider votes or model-quality proof. LG/NAVER/Kia may reuse exact retained
parser outputs on complete selected PDFs, with explicit original-page mapping.
The Hyundai product canary executes the bounded Java path and retains its
original physical pages 22/41. Linux full pipelines are limited to 2CPU/4GiB,
use an ext4-backed disk volume and record cgroup/Docker exit state. The scope
is these selected canary pages, not every page in the companies' reports.

Acceptance and measurements are in the requested I5 artifact directory:
DL4 precision >=97.54% with nondecreasing recall, H1 holdout precision preserved,
false_verified=0, zero I4 live regression, LG including cold publication <=480s,
no budget exhaustion/OOM/exit137, and the final repository checks.
Server deployment/runtime.env changes require the coordinator; I5 writes only
local commits, evidence and non-secret recommendations.
