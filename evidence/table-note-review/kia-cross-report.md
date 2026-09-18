# Kia cross-report review — 2026-09-14 KST

Extended the existing immutable report-review CLI to a third actual report,
Kia2025 physical/printed page45. The same source/packet/table-cell checks used for
Samsung Life and Kakao passed. No paid call was made: the current source-replayed
note packet and archived parser/claim receipts were reused, and the section map
was rebuilt locally. Neither historical packet nor prior report was overwritten.

The coordinator rendered the original PDF with installed pypdfium2 (Poppler was
not installed) and visually compared the two bottom tables and their notes. The
three proposed links match the page: domestic coverage qualifies all6 waste table
values; EV3/EV6/EV9-only qualifies39,884ton; the average over those models qualifies
2.5%. The latter is not a fleet-wide share or a ratio derived from the39,884total.
The waste columns retain2024target,2024actual and2025target separately.

Orca Muse Spark1.3 Free independently checked source text/coordinates and the
archive: task_d912d046da19 / ctx_96148d0faf35 / msg_38693f5fa7a4. It found the same
3 correct proposed links across8 value candidates and explicitly did not claim
visual review or source approval. Coordinator visual review completes the
separate page check. Worker settled, release returned external_terminal, exact
terminal close confirmed ptyKilled, delivery acknowledged.

The browser review exposed an unreadable whole-table Markdown quote in the note
owner label. The artifact now retains table_source_id and renders that exact
matching owner as `표 전체`; cell owner labels and all raw source refs remain
unchanged. This is an evaluation artifact display change, with no API/DB or domain
contract change. Final standalone HTML and the original PDF links were inspected
in Orca's embedded browser after regeneration.

## Local evidence

- `.local/note-review-integration/kia/review-final/index.html`
- `.local/note-review-integration/kia/review-final/review.json`
- `.local/note-review-integration/kia/source-page45.png`
- `.local/note-review-integration/kia/final.png`
- `.local/note-review-integration/kia/verification.json`
- `.local/note-review-integration/kia/command.json` (initial CLI; final uses new output folder)

Final artifact hash:6ea895d963d684b726f55480e41b3d8646ed584048cebd94f0de500c03063cb9.
Source hash:d0d814d98c4aeedbbdb2bf8631b8981ae5cde94dec32aa32c57510420274da1f.
A runtime assertion checked exact3-to8 linkage, artifact hash, copied PDF hash,
unknown coverage, numeric not_run and blocked admission for every value.
All8 still have unresolved source/condition acceptance; visual comparison does
not mutate source verification or authorize rule grading. The17 archived claims
are from other selected pages, so this is table-note cross-report verification,
not a page45 claim-to-note pipeline benchmark. The unprocessed chart and the rest
of the report are not counted as covered. Goal remains active.

Focused report/numeric-candidate tests29 pass; Ruff, mypy162 files and4 Python
package builds pass. Documentation/contracts validator758 passes separately.
No parser/model/AWS/deployment calls, new dependency or corpus changes.

Final full suite:1841 passed,2 existing deprecation warnings,124.16s;
`.local/note-review-integration/pytest-kia-final.log`. Diff check passes.
