# Finals v27 local integration

`finals-20261016-v27` composes the immutable v26 policy with S5's source reader,
256-call extraction batches, concurrent SC1 chunks, final usage reporting and C3
wire-schema binding; RB3 deadline admission; RB1 source/claim input isolation;
and RB2 parser-output compaction and native reporting-period detection.
The public default selects v27. All earlier explicit analysis and publication pins,
including v26, remain admitted. API and database schemas require no migration.

V27 instantiates the S5 source reader once. RB3 contributes only its deadline
policy; its separate reader and byte-identical DAG evaluator remain historical
compatibility modules for standalone RB3 receipts. No new combined reader or
second source-proof pass is added. DAG evaluation matches uncached FXH evaluation.
The RB1 and RB3 hold helpers have distinct names so one cannot intercept the other.

`i27_sc1_optional_transient` is a separate exact-match opt-in field. In an SC1
request only, an HTTP 5xx may retry once after a bounded exponential backoff
(base 1 second, multiplier 2; one retry means the only delay is 1 second). The
identical logical payload/replica is retained; each physical attempt has a new
broker call ID, rechecks authorization/expiry and money, and retains uncertain
reservations. A timeout degrades without retry. The inventory's conservative
reservation estimate includes its one potential retry per planned request.

A failed optional request is saved as a failed vote with a sanitized reason,
request/chunk/replica identity and attempt IDs. Other chunks continue; the existing
inventory assembler leaves incomplete coverage uninspected. No failure becomes
absent, present or confirmation. Inventory and wire receipts preserve the reason
on cold replay. Request-local context prevents ordinary tagging or extraction
failures from receiving this exception. Billing, 403/429, authorization, lease,
source integrity and budget stops keep their existing rules. An SC1 timeout does
not trigger run-wide OPS2 fallback; nonoptional network failures still do.

The hosted outcome reports optional failed physical calls separately and removes
only those calls from the run-blocking provider total. Its raw failure count and
money ledger are unchanged. Completed means ordinary processing finished; it is
not evidence that SC1 scope was confirmed or that uncertain spend was settled.
RB3 time holds and other unresolved provider failures still make runs partial.

The RB2 addendum selects `parser_output_policy=rb2-output-v1` and
`reporting_period_policy=rb2-native-period-v1`. The original v27 hash remains
selectable for existing receipts. Oversized combined parser output first compacts
candidates, then the graph when necessary, without dropping nodes or changing
the 20 MB limit. Offline readers and W18 resolve the manifest's stored filename,
verify its SHA-256 and use RB2's bounded decompressor with the original-byte hash.
Source, tenant and manifest anchors remain required at their existing boundaries.
The new period heading remains inspection-only; exceptions cannot confirm scope.

Rollback new work to commit `919ea82`/the v26 pin. Preserve new v27 artifacts and
serve them with a compatible reader; never reinterpret them using v26 or erase
pending money. Server deployment is outside this local task. The separate API
1536 MiB override in `/srv/proofops/compose.ops2.yaml` must be reapplied by the
operator when a later deployment is authorized.
