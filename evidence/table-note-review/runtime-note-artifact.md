# Runtime note review artifact contract — 2026-09-14

`freeze_note_review(graph, source, packet, extracted, tenant_id=...)` creates a
canonical JSON string containing the exact base-graph hash, source/tenant/version/
manifest identity, original packet/result and recomputed source validation.
Coverage and ownership remain unapproved. Its content hash excludes its own
artifact_sha256 field. Source validation checks the original PDF again.

`replay_note_reviews(artifacts, graph, source, tenant_id=...)` accepts only new,
nonduplicated artifacts bound to that exact immutable base graph. It recomputes
each artifact before returning a new graph with open QualityIssue records for
each affected table and its descendants. The issue references the artifact hash;
the artifact retains raw fragments, coordinates, proposed ownership and model/
prompt/request provenance. Original blocks, edges, candidates, prior issues and
parser files remain unchanged. Unknown coverage, including zero detected notes,
never creates an approval. No source quality or grade is promoted.

This uses the existing QualityIssue shape (kind is already an open string), so
no API/DB migration or new parser projection fields are introduced. Publication
uses new artifact files/output directories; caller must retain the canonical
JSON alongside the derived graph's hash. Old artifacts and parser manifests are
not rewritten. Multiple reviews must share one exact base graph; replay rejects
stacking them on a previously augmented graph or silently rebasing manifests.
An issue cannot be dismissed by changing its state inside this artifact: replay
reconstructs open issues. Rollback must retain prior artifacts and may not treat
registered unresolved conditions as absent.

Retrieval, numeric checks and tagging must honor these open source issues. This
contract supplies a reusable runtime input bridge; automatic publication into the
API run/job registry is separate and not claimed by this artifact API.

Validation and actual-report evidence will be recorded after execution.

## Executed evidence

`report_demo.attach_table_notes` embeds the canonical artifact once per reviewed
page and records its hash, derived graph hash and relevant issue IDs in each
table review. Existing numeric candidate status remains not_run/blocked; this
does not fabricate a claim binding or execute an otherwise unsupported numeric
comparison. All three archived CLI commands succeeded into fresh
`.local/note-review-integration/{kia,kakao,samsung-life}/review-runtime-notes-v1`
directories, preserving previous outputs and showing complete=false/zero decisions.

An isolated `python -I` process loaded the built proofops wheel with imports of
evaluation/scripts/tests explicitly rejected. It read the new artifacts from the
actual report outputs, revalidated original PDFs and exact base graphs, and checked
new note issue IDs against the shared runtime source-issue guard for every cell.

| Report | Notes | New table-note issues | Cells connected to new issues | Existing parse issues retained | Artifact bytes |
|---|---:|---:|---:|---:|---:|
| Kia | 3 | 2 | 24 | 24 | 161664 |
| Kakao | 6 | 3 | 209 | 209 | 450600 |
| Samsung Life | 12 | 3 | 296 | 296 | 697868 |

Existing parse issues already prevented approval in these real graphs. The
check explicitly intersected each cell's runtime issue IDs with the NEW note
issue IDs; it did not mistake pre-existing blockers for successful registration.
This is a 529-cell provenance/guard connection check, not a numeric accuracy score.
Results: `.local/note-review-integration/runtime-note-artifact-replay-final.json`.
Reproduce with `.venv/bin/python -I .local/note-review-integration/check-runtime-note-artifacts.py`.
No paid API calls or original PDF/archive modifications.

## Guard and replay verification

Failing tests reproduced numeric consistent despite an open table-note issue,
retrieval candidate despite a parent-table issue, and tagging accepting a packet
which omitted all table candidates despite its claim's parent issue. The shared
`unresolved_source_issue_ids` follows explicit table ancestors, terminates cycles,
and preserves open/unreadable issues. Numeric checks return not_computable;
retrieval blocks/excludes affected candidates; tagging rejects before calls or
budget attempts even if parent/table references were omitted from the packet.

Artifact tests cover deterministic replay, original graph preservation, duplicate
receipts, changed source, foreign tenant, wrong base graph, rehashed forged
coverage, and zero detected notes remaining unknown/open. New artifacts pin both
validator and layout code hashes using package resources (also works in a wheel).
Only exact canonical JSON is accepted, up to 16 MiB. A code/profile mismatch
requires a NEW artifact; do not rewrite historical artifacts. Persist the artifact
with its exact base graph, not just the fixed v1 graph projection which omits
rich issues. Replaying the receipt recreates the derived graph and its hash.

Orca Muse Spark 1.3 Free review: task `task_3bc13aa51dcc`, dispatch
`ctx_249350e2bc0c`, accepted completion `msg_925c93db8112`. Reviewer found no
blocking path in scope. Its minor tenant-check concern was not reproduced:
freeze calls validate -> prepare -> table_layout_context -> _validate_graph,
which rejects a foreign tenant; both detected/empty-note tests confirm this.
No duplicate tenant guard was added. Worker released, exact terminal closed and
completion delivery acknowledged.

Ruff passed; mypy passed 165 files with existing untyped-body notes; build passed.
Full regression: 1871 passed, 2 existing deprecation warnings, 124.33 s, logged at
`.local/note-review-integration/pytest-runtime-note-artifact-final.log`.
Documentation/contracts: 758/758 (not an application accuracy benchmark).
