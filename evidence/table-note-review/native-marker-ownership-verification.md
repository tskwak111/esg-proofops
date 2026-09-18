# Native marker ownership — bounded release checkpoint

The source-review service now derives a native-note ownership proof from committed
original PDF artifacts, independent of model target proposals and client acceptance
fields. A smaller, raised Arabic marker next to an alphabetic, nonnumeric base must
have exactly one source-validated leaf owner in the note's original table column.
Competing marked cells, missing marker transcription with overlapping native markers,
competing same-number prose note anchors, ambiguous/unreadable sources and expanded
row/table targets remain unresolved. This supports a bounded typography pattern only.

The pure validator still requires confirmed note transcription/classification and
verified original leaf/table/ancestor evidence. The adapter replays the immutable
base graph/artifact, checks the original graph hash, and supplies the internal proof;
verified references are checked against the transient reviewed graph. Clients cannot
submit the proof through the ownership request. Effective ownership is reevaluated
on each new revision, with native proof and policy digests retained. Old revisions,
exact retries, source candidates, source issues and numeric/grade outputs are unchanged.

## Actual source/API evidence

POSCO Future M original SHA256:
`65070d88297d4faf631a9545e6aa49b56ccae71531dda0248f69a3887ab779a8`, physical p139.
Existing local worker state `canonical-glyph-worker-v1/poscofuturem` was reused after
four canonical source transcriptions had been visually checked and confirmed.
Native note anchor `f97` (first line only) was displayed via the actual authenticated
HTTP source-view/image routes, explicitly classified as a note and transcription
confirmed through reviewer tags. The API accepted its link to the raised `2)` on
`합계` in source `6c71f55c-a9f9-5510-a82f-1eb98ce75c74`.

Original base/marker native word indices: 344/345. Note indices: 393–406.
Proof SHA256: `66f846ef47c9aa50554705340c18331289ddd76e3595076267935c947bb82d90`.
Saved source-review revision: 3. Same-number notes `f65` and `f66` in other columns
returned no proof for that target. A client-injected native_proof field returned
HTTP422. Exact write retry returned the same revision; revision2 and published graph
remained unchanged. Private evidence:
`.local/note-review-integration/native-owner-api-v1/result.json` and
`.local/note-review-integration/native-owner-api.log`.

This acceptance is only the marked leaf/anchor relationship. The rest of the note
(`f100` continuation) is not included in that API ownership record. Full qualification
interpretation, coverage, numeric receipts and grades are NOT approved: coverage remains
unknown and numeric_receipts is empty. The current native condition interpreter remains
unsupported. No completion claim for the overall service objective.

## Worker and checks

Real Orca worker task `task_eee747a24a7e`, dispatch `ctx_c26cb2420448`, implemented only
native_note_ownership.py and its integration tests. Worker released; final delivery
acknowledged. It independently replayed actual POSCO f97/f100 group read-only and found
the same original target/words, without writing source/graph/artifact/SQLite state.
Grouped proof SHA256: `385949279885c1ecb9af890dbfa8bddc9639ea769e9a8768388c869ed9e394d3`.
That grouped proof is adapter verification only, not a published source-review group.

Failed-first root tests: 9 failures for missing internal native_proof capability;
then 42 pure ownership cases passed, including forged proof input and verified-target
holds. Worker added 19 original-PDF marker cases. Final focused ownership/API/condition
suite: 121 passed, 2 existing dependency deprecation warnings, 12.93s.
Mypy caught a local variable naming/type collision; corrected without changing predicate
behavior, then all 174 source files passed. Ruff lint/format: 296 files passed.
Architecture checks and all four workspace builds passed. Documentation validator:
790 checks/50 API operations passed, documentation/contracts only.

No actual model, AWS, deployment or browser-driven UI exercise in this change; not_run.
Zero external model calls or new dependencies. User requested finishing this current
work and stopping; no next improvement task is started after this checkpoint.

Final release validation: `uv run pytest -q` completed with 2154 passed, 2 existing
dependency warnings, 165.93s. Log:
`.local/note-review-integration/native-owner-release-full.log`.
Installed-wheel replay reopened all 21 existing actual report checkpoints with identical
published graph hashes and zero model calls; result:
`.local/note-review-integration/native-owner-wheel-replay.json`.
The overall service goal is not marked complete: note-continuation handling, condition
interpretation and downstream numeric decision receipts remain outside this checkpoint.
