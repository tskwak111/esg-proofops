# PB4 Linux table reader

New source reader `upstage-ocr-page-v9` wraps the exact v6 prose reader, without
rewriting or privately rebinding its module globals. Native paragraph and parser
table attestations retain the v6 policy. The claim extension keeps the complete
v6 receipt as `baseline_receipt`, with unchanged non-table records, and adds
native table-cell ownership proofs. Compact policy hashes pin the full v6/v8
policies and verifier bytes without exceeding the existing 64KB runtime-config guard.

Every selected cell of a quoted parser row, located or recovered, must occur in
declared column order with nonoverlapping native x ranges and a shared native y
band. Explicitly attested year headers remain separate contextual sources.
The original NAVER p88 PUE/title cross-row/cross-column combinations are rejected.
No failed row proof can inherit a whole-table flag or previously verified span.
Unlocated recovered selections still cannot promote their whole cell.

V1-v8 verifier bytes, all prior analysis policy hashes, source receipts, tags,
rule packs and decision revisions remain immutable. V9 is an additional exact
policy dispatch entry. It adds no API/DB column or dependency. The new analysis
policy retains the previous PB2+PA2 integration policy for historical replay.

The Linux gate uses fresh Linux PNG-bound Upstage OCR collections, then denies
network access during source replay. Failed OCR reservations remain accounted
for. No Mac receipt or PNG identity is reinterpreted. Original crops cover every
newly verified claim in the saved 131-claim scope; this is source admission,
not model accuracy or a new tagging/grade evaluation.

After the gate passes, only v9 is added to the hosted allowlist and new v2 Linux
default. Rollback restores both the prior analysis assignment and v6 default;
retain v9 for runs already pinned to its policy. Historical v6 replay remains.
