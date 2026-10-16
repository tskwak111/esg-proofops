# SPP parser execution candidate

`analysis_profile.SPP_POLICY` composes v29b with
`parser_execution_policy=spp-parse-v1`. It is opt-in; `V2_POLICY` and hosted
defaults remain v29b. The new field reaches `ParserProfile.execution_policy`
through `apply_pilot_profile` and `local_upstage_pilot`. It is absent from old
invocation/config snapshots, preserving all historical hashes and replay.

The candidate preserves selected pages, parser versions, raw candidate text,
coordinates, original-byte verification, three tagging replicas and decisions.
It changes only these execution steps:

- Resolve v21's table reader directly, recomputing its complete policy hash at
  every parser/replay boundary. A different reader hash is rejected. There is
  no policy/verification-result cache or source-admission shortcut.
- Decode the same pdfplumber pages once per isolated child for header repair,
  auxiliary tables and ink location; close the document on exit. Reuse the
  same immutable page-label array during geometry preparation.
- Prepare at most four single-page claim subsets serially, then overlap their
  existing guarded provider calls with the isolated local parser. Only the
  leading selected claim pages are eligible: no evidence-only page is speculated
  before native readability is known. Drain the wave before native grounding.
  Preserve per-page exceptions, ordered assembly, bounded retries and terminal
  stop handling in the unchanged HX6/S3 recovery implementation.

The original per-tenant, source/model/page/subset-keyed provider cache is reused.
OCR's existing image/source/policy cache and original receipt verification are
unchanged. No provider concurrency increase is authorized by this policy.
Published rate limits are account-tier dependent, and the task's saved evidence
does not establish a current higher account allowance.

ODL already batches ordinary selected pages in one JVM. A persistent JVM is not
introduced: it cannot remove additional page-level starts from this workload
and would change the existing per-batch memory/timeout/process-tree boundary.
The provider simulator's separate Java invocations are simulator costs, not
production ODL startup costs.

If local parsing fails after dispatch begins, at most the first four authorized
requests may have incurred cost. They are drained and their completed receipts
stay in the existing page cache; no checkpoint is published. Each dispatch still
uses the original budget/authorization/lease broker. Subset/cache failures reach
the original per-page recovery boundary. Rollback stops assigning the new hash;
stored candidate runs keep the new reader, and prior revisions are not rewritten.

Integration registration points: append SPP_POLICY to `policy_for` and
`publication_policy_for`, the hosted argument allowlist in `hosted_r108`, and
the two PB1 presentation allowlists in `hosted_results`. A future finals candidate
may compose the parser execution selector onto its own new hash; it must retain
S3 routing, H6 v2 batching and the v21 native/table source policy. EV2's
`tag_runner`, `live_tagging` and relations implementations are untouched.

The optional fresh timing harness records upload/scope, local ODL/Java,
pdfplumber, provider/OCR, merging, verification and checkpoint durations without
arguments or source text. Inclusive times overlap and must not be added as wall
time. Java initialization and execution remain a combined interval. Fresh
simulation uses generated replies and no network; it is not live model-quality
or server-latency evidence.
