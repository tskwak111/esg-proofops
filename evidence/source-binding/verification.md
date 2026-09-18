# Document-source binding hardening — 2026-09-13

Baseline d34656b. Evaluation-only change; no production routing or domain changes.

## Fixes and regressions

- Align only four curly/straight quotation glyphs, preserving character lengths,
  original source quotes/offsets and the unchanged model quote separately. Whole
  row headings use the same equivalence. No case, number or whitespace repair.
- Reject competing cells before validating an individual cell's span. Previously
  a cell containing two occurrences failed validation and disappeared from the
  candidate list, allowing another matching cell to be accepted incorrectly.
- Exclude leading merged header rows using the existing section-pipeline structural
  boundary (first row plus maximum row span). This is conservative structural
  filtering, not semantic proof that every header/data row has been identified.

Fail-first regressions cover glyph alignment, changed numbers, competing cells,
multiple occurrences within a cell, repeated occurrences competing with another
cell, and merged headers. All proposals remain ineligible for scoring. Standalone
status ownership, semantic validation and original-image approval stay undetermined.

## Stored-response replay (no new model calls)

Inputs are the immutable responses from `.local/document-atomic-v1` and their exact
native parser snapshots. Outputs: `.local/source-binding-wave/final-replay`.

| Crop | Source-linked proposals | Unbound |
| --- | ---: | ---: |
| Naver | 6 | 1 |
| KB investment | 3 | 0 |
| KB opportunities | 21 | 0 |
| Kia numeric table 0 | 0 | 0 |
| Kia numeric table 1 | 0 | 0 |

Total30 linked/1 unbound, compared with29/2 previously. The newly linked Naver
completion quote differed only in apostrophe glyphs. The remaining quote occurs
in both a task cell and its completion cell and must remain unknown without an
independent column cue. These counts are source-binding diagnostics, not accuracy,
recall, verified facts or service readiness. Numeric empty output proves no absence.

No paid extraction calls this wave. Existing committed/reserved USD7.68289506 /10
is unchanged; prior six unsettled reservations were not modified.

## Independent review and disposition

Orca run run_23e4034644ec, task task_9047cd0ee33d. Kiro exited without findings;
default OpenCode returned insufficient balance on MiniMax. Explicit OpenCode
Muse Spark1.3 Free completed read-only review (ctx_f7a58b1cc201,
msg_55c9ed112f98). All three attempt terminals were closed. First two dispatch resources were
released; Muse release returned retained/external_terminal, then its exact
coordinator-created terminal was closed (ptyKilled=true). Muse did not edit files or call the paid extraction API.

Accepted/reproduced: quotation mismatch in row headings and merged-header leakage.
Coordinator additionally reproduced/fixed the disappearing ambiguous-cell bug.
Deferred: word grouping can fragment a synthetic sloped baseline. Changing the
anchor to the previous word can instead chain separate lines; no real-source
semantic failure was demonstrated, so this layout hint was not changed.

Remaining limitations: no exhaustive omitted-cell coverage; no independent numeric
footnote recovery; ambiguous task/result ownership; source text agreement does not
validate source image or the claim/evidence semantics. No model accuracy or full
report benchmark, AWS trial or production deployment was run in this wave.

## Verification

Focused final atomic/layout suite:19 passed. Final full checks recorded below.

- Final `uv run pytest -q`:1,787 passed,2 existing warnings,115.79s.
  Logs `.local/source-binding-wave/pytest-final.log`; the earlier run preceded
  the final competing-cell fix and is not the final verification evidence.
- `uv run ruff check apps packages tests evaluation`: passed.
- `uv run mypy packages/proofops apps/api apps/worker apps/agent evaluation tests/load infra/cdk/staging_gate.py`:
  passed,161 files (existing untyped-function notes remain).
- `uv build --all-packages`: four Python packages built from final code.
- `uv run python scripts/validate_package.py`:754 documentation/contract checks
  passed; not an application or accuracy benchmark.
- `git diff --check`: passed. No new dependency, API or DB migration.
