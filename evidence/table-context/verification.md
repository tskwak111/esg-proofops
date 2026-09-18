# Crop-external context and unit-note safety — 2026-09-14 KST

Baseline e2b93cf. This is a checkpoint toward the user's service-readiness goal,
not completion of automatic table-note ownership or a production-readiness claim.

## Implemented

The same source-checked PDF read now preserves native words outside the selected
table, including boundary-crossing words, as `page_context`. Whole-page context
avoids guessed nearest-table ownership. It includes original PDF SHA, physical page,
word indices, point coordinates, text and candidate fragments. `table_crop` returns
it beside image lineage and `prepare_rows` passes positioned context to the table
role/atomic extraction packet. Context remains unassigned and cannot be used as
an allowed role basis or extraction target. No original table crop was expanded,
no source text was rewritten, and existing raw API responses were preserved.

Each outside-word collection is bounded at1,000 words, with no silent truncation.
Rotated words intersecting a table still fail closed. Rotated outside labels remain
in raw context with unreadable indices and partial_unreadable status, excluded from
upright fragments. Rotated pages/nonzero origins retain the previous hard gate.
Native-word retention does not cover text embedded in images or prove OCR quality.

The production `_observation` function previously accepted arbitrary text following
`단위:`/`unit:` as a unit, including '천 tCO2e (부산만 해당)', and multiplied values.
Both normalizers now allow only an explicit bounded literal-unit grammar with the
existing optional '천 ' scale. Empty, scoped, compound or unsupported note units
produce unreadable observations without numeric values, preserving original notes
and refs. This conservative parser grammar is not a domain/unit ontology; unsupported
valid units also require interpretation. Plain linked unit notes remain supported.
No new scope, metric or rule grade is inferred.

Normalizer identity version is2: new runs cannot silently reuse the old observation
identity for changed interpretation. Public v1 DTO/DB schema is unchanged. Prior
observations/reports stay immutable. Rollback uses the old normalizer/extractor;
retain all new receipts/artifacts instead of rewriting old records.

## Real-report evaluation

54 table instances across seven companies: Doosan10, Kakao14, KB8, Kia8, Kepco3,
Samsung Life10, Naver1. Local-parser cached tables and previously tested document-API
tables are different parser instances, not necessarily54 unique tables. Six Doosan
instances initially failed on rotated sidebar text; after preserving those words
as unreadable context, all54 produce explicit output (48 candidate_only,
6 partial_unreadable). None is accepted semantic evidence. Counts/hashes are in
cross-report.json; source-bound private outputs in `.local/table-context-wave`.

Directly rendered and viewed Kia physical45. The outside context recovers '데이터
커버리지 : 국내' above the left table and the two EV3/EV6/EV9 qualification/average
notes below the right table. Both note bodies are deliberately visible to both
same-page table contexts; their membership has not been automatically approved.
This confirms retention on the observed source, not ownership accuracy.

No new paid extraction calls; existing committed/reserved USD7.68289506 /10 remains.
No budget reservations or credentials were altered.

## Orca review

Run run_bd4f467aede6. Kiro task task_2a95f5bd70e8 exited with 'Session ended' and
no findings; exact worker terminal stopped/released. Muse retry ctx_9ed666959e23
reported the scoped-unit conversion bug (msg_210552825ca1). Coordinator retained
valid table-level plain-unit behavior instead of rejecting all linked unit notes.
Second Muse task task_906bb4bebb22 / ctx_6fc9018cdef0 reviewed the diff and found
hyphen-joined scope text still passing the initial loose grammar; coordinator
reproduced and replaced it with bounded literal units. Empty-unit notes deliberately
remain unreadable. Corrected cases are tested in both normalization paths.
Both Muse dispatches settled successfully, release returned external_terminal, and
the exact coordinator-created terminals were closed. No reviewer edits or paid calls.

## Remaining goal work

- Context-to-table/metric ownership proposals with exact source validation and
  abstention for duplicate markers, neighbouring tables and ambiguous scope.
- Independent original-image evaluation of those associations across reports.
- Demonstrate downstream numeric interpretation receives the resolved conditions;
  context retention alone is insufficient.

## Checks

Final checks recorded below. No new live model evaluation, whole-report accuracy,
web UI test, AWS trial or deployment was run in this checkpoint.

- `uv run pytest -q`:1,798 passed,2 existing warnings,117.04s.
- Focused table/binding/numeric suite:118 passed; combined layout/role/atomic/table
  suite66 passed before the final three additional unit-note cases.
- Ruff passed; mypy161 files passed with existing untyped-function notes.
- Four Python packages built; final change afterward only split an identical
  regex literal across source lines to satisfy lint.
- Documentation/contract validator756 passed (not an app/accuracy benchmark).
- `git diff --check` passed. All changes remain local.
