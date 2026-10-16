# CF1 inventory wire and DEC-125 scope absence (opt-in, c3a3042 / v27)

`CF1_POLICY` (`cf1_finals_inventory_dec125_v1`) adds `cf1_inventory` to the
analysis policy and inventory selection. `CF1_3OF3_POLICY` retains the exact
quote wire with the old unanimity behavior for comparison. Both require an
explicit hash; the v27 default and every existing registered pin are unchanged.
The hosted child allowlist accepts both pins. No deployment is included.

Saved E17 LG receipts have 39 invalid replies: 31 invalid period spans,
4 attributes without a structural binding, 3 out-of-chunk spans, and one
duplicate candidate. E16 additionally has truncated JSON and a transport
failure that stopped subsequent dispatch. These are distinct from the page
source-coverage failures present on every selected page.

The model receives local span IDs, exact text, and existing lexical/table cue
IDs. Evidence selects a full supplied span by ID; subject/metric/site/period
select unique literal quotes within that span. Python restores absolute Unicode
offsets. Ambiguous, missing, or rewritten quotes are rejected; attributes are
never repaired or borrowed. This restricts attributes more than the old
structured-edge wire. The original per-response source, period, structure,
duplicate, request identity, and freshness guards still run. The model only
extracts/tags; Python rules determine grades.

DEC-125 accepts scope absence when the **same two replicas** completed every
chunk, covered every cue, and resolved each relevant candidate as not applicable
or demonstrably belonging to other claim attributes. Missing, unknown,
unreadable, or invalid records never become absence votes. A third such vote
can be outvoted; an unreadable or unverified **source page** cannot. All selected
pages must still pass the original source-coverage checks. All three independent
requests are attempted and invalid replies remain invalid in the call counts.
Present and track agreement thresholds are unchanged by this absence policy.

Verified contrary present/conflict evidence vetoes competing absence votes.
The veto includes individually verified records from a retained, schema-valid,
authenticated reply whose sibling record fails a span or attribute guard. These records are retained under
`cf1_contrary_records`, for veto only; they cannot establish present or count as
a completed vote. Unresolved attribution on contrary evidence is conservative.
`cf1_inspected_replicas` records complete, cue-covered replica IDs. The receipt's
`cf1_absence_agreement` identifies the rule used. Old inventory and scope replay
outputs do not acquire these fields. Existing uncovered-cue and invalid-replica
diagnostics remain intact, including the dissenting replica's failures.

Request identity includes selection/policy and prompt hashes. I24 continues to
bound dispatch/output/cost. Receipts retain original requests and compact raw
responses; `cf1_validation_error` records new-wire rejection reasons. No
schema/database migration is needed. Roll back by stopping assignment of the
new pin, retaining readers and artifacts for existing runs.

The six-chunk Codex CLI experiment is synthetic and failure-enriched: 14/18
replies pass transport/span/period/duplicate checks versus 5/18 saved server
replies. Different execution environments prevent a live-quality/latency claim.
Rechecking those saved simulation outputs gives 2/6 chunks with three valid,
cue-covered replies and 4/6 with two. This is a counterfactual comparison, not
fresh DEC-125 calls or full-graph replay. Both thresholds yield zero inspected
selected pages and zero scope confirmations because source coverage is blocked.

Thirteen controlled comparisons exercise actual source guards and Python rules.
Among four permitted cases, scope confirmations rise from 1 to 4. Among nine
false-confirm counterexamples, the old 3/3 behavior confirms one case with
unresolved contrary attribution; DEC-125 confirms none. Additional source-quality
and rotating-quorum checks retain their holds. These fixtures do not establish
production semantic accuracy; old behavior is preserved rather than rewritten.

CF1 does **not** establish the requested positive production confirmation count.
All E16/E17 selected pages have unverified/unlocated/unreadable or missing source
content. Even perfect response validity cannot overcome that independent gate.
The R20 174 reviewed claims have zero new absent_in_scope/confirmations at both
thresholds; PDF hashes and native claim quotes were rechecked, while earlier
semantic adjudications were reused. R17's 114 claims have no paired fresh CF1
whole-scope rerun. Zero promotions is not positive accuracy evidence. Source
coverage must be repaired by its owning workstream and measured with fresh
complete-scope receipts before enabling the new pin.

Validation, LG13 timing results, known baseline test failures, the exact pins,
and the Korean report are retained in the parent repository at
`outputs/agent-results/R108-redesign/lab/confirm/CF1/`. This is self-review, not an
independent audit. Integration conflicts include I28's profile registry/hosted
allowlist and SC1/QT2 consumers of inventory/scope receipts.
