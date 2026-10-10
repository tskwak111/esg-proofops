PB2 connects attested table cells to model-selected P1/P2; domain ladders and rule-pack bytes stay unchanged.

The new finals-v2 analysis policy pins `table-selected-evidence-pb2-v1`, `citation-table-separators-pb2-v1`, `preliminary-fact-fields-pb2-v1`, and the local native reader `upstage-ocr-page-v8`.
PB1 and the initial PB2 policy hashes remain readable; v7 verifier bytes are unchanged. Rollback selects the old policy for future runs and preserves existing artifacts.

A P1 candidate requires a model `present` vote and a normalized selection covering the explicit focal value. The row, value, unit and current-year cell must be source verified in one parser table. Narrowing a selected row to its already selected value produces exact cell refs and retains the raw model selection in its receipt. Unknown, null values, unit-only or older-year-only selections cannot become present.
A P2 candidate requires the model's own `present` vote and selected comparison value with that column's verified year header in the same table. No cross-row/document numeric evidence or inferred year is admitted.
Every appended cell remains subject to packet provenance, allowed element/source scope, tenant, raw offset, normalized-value, replica and budget checks. P4/P6 remain dedicated deterministic service outputs. These candidate sources do not compute a grade. Exact native P1/P2 cells appended to a packet need no additional relation model; other elements/sources keep their ordinary semantic attribution path and all element votes/guards remain required.

Citation restoration maps whitespace runs and explicit spaced pipe separators only to existing raw table tabs, with unique raw offsets. It does not replace digits, merge numeric tokens or admit new source quality.
V8 reconstructs multiline cells and retained duplicate parser origins. Missing generic cell boxes can be recovered only for uniquely matched quoted native fragments inside the table region, with native order/appearance guards. The containing table span alone is attested; the unlocated whole cell is not promoted. Missing numeric observation cells and repeated/ambiguous literals remain unresolved.
Verified older-year headers are optional P2 candidates; unreadable headers do not fabricate P2 or erase an intact P1 proof.

The preliminary fact-field repair applies only to table claims. Prose retains its existing wire and validator. The table wire enumerates the eight existing attribution axes and omits unrelated optional axes. Previously returned `unit`, `value`, `quantity` selections are preserved as auxiliary diagnostics under the new policy and never become dimensions, P1 votes or grading facts. Unsupported dimensions, grade fields, invalid selections and attribution failures retain the existing guards.

The existing optional `table_observation` result object gains `verification_state` and `cell_source_refs` (value/unit/year) on PB2 results. Old result receipts, report snapshots and revision records are not rewritten. There is no endpoint, DTO requirement, database migration or new dependency; clients may ignore these optional fields.
This is a local evaluation policy, with no hosted reader release approval, push, deployment or AWS change.
