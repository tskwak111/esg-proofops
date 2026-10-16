# CF2: LG p36 bounded C3 diagnosis and new-run repair

Authority: `cf-CF2.md`, DEC-48/68/85/92/93; base `c3a3042` (v27).
This change remains restricted to the already approved LG original, tenant,
exact claim/evidence fingerprint and rulepack. No additional report is admitted.

E17's three schema-valid responses all set `governance_claim=true`, which the
existing C2 conditional gate correctly sends to review. Replica 3 also selected
the short activity quote `환경경영시스템`. Its unique occurrence in the supplied
claim is at offset 175, but the old whole-block lookup first finds an earlier
occurrence outside that span and rejects it. M3 becomes unknown, the replicas
disagree, and the approved source fingerprint cannot be established. Failed
assemblies used to return before any detailed receipt was saved.

Select `CF2_C3_POLICY` by its explicit analysis-policy hash. It adds only the
`cf2_c3_response_binding` selector to the existing v27 behavior. The binding
policy pins the new prompt, scoped lookup, and receipt persistence. Existing
publication-policy identity is retained; CF2 derived matcher hashes additionally
bind the CF2 policy, and the full analysis policy is stored and checked on replay.

- Resolve a quote only when exactly one occurrence maps inside the supplied
  verified source span using the existing native offset map. Repeated matches
  inside that span, missing quotes and unverified sources remain unresolved.
- Define M5 governance and M6 compensation triggers in the new tagging prompt.
  EMS/ISO/internal audit alone does not infer an organization or governance
  assertion. Explicit responsibility/oversight and compensation claims still
  require review. True/null replies are never rewritten or treated as absence.
- Persist the complete assembly at `bounded-c3/cf2-receipts/<receipt_sha256>.json`
  before either returning a hold or starting publication. Use an atomic create-only
  write; conflicting existing content or symlinks fail closed. A diagnostic file
  does not create a publication manifest or confirmed revision.
- The hosted outcome adds `cf2_receipt_path` (relative to `bounded-c3`) and
  `cf2_unresolved`. Existing fields keep their meanings. Grade computation,
  broker authentication, three independent origins and source fingerprint guards
  remain unchanged. Stored responses and CLI simulation cannot publish.

No DB migration, dependency, default-policy change, deployment or API call is
required. Rollback stops assigning the CF2 pin to new runs and retains this reader
for immutable CF2 records. Older policy/request bytes and replay behavior remain
unchanged. I28 should compose the selector into its own new policy and retain
`CF2_C3_POLICY` in the registry; do not replace the default or historical entries
with this branch's v27 policy.

Validation covers scoped-quote regressions, true/null conditional holds, failed
receipt persistence, current-response tampering/replay, source visibility and
historical readers. Fresh Codex CLI tags are simulation candidates only; the
local generated broker fixture tests publication/reopen/export/If-Match mechanics,
not actual provider accuracy or production publication.
