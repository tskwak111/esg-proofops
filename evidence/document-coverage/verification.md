# Document extraction omission accounting — 2026-09-13

Baseline e305b8b. User authorized continued core fixes and Orca review. No domain,
public API, DB, dependency, production routing or paid-model changes.

## Root cause and implementation

`bind_document_rows` previously reported only successful quotations and rejected
model proposals. Entire source cells omitted by a model were invisible. A native
cell with no selected canonical winner was also silently skipped.

The binder now emits `cell_coverage` for selected native cells, with full SourceRef,
quality, structural context role and normalized original-text offsets/quotes for
unreturned ranges. `_text_coverage` reuses the prior text-extraction algorithm for
both text and image-response paths. Every residual is unknown, never absent.
Header and row-heading roles describe structural context, not confirmed semantics.
Conflicted cells, cells selected from another parser and missing row/column metadata
are recorded in `unresolved_cells` with the relevant original candidate sources.
If no usable native rows exist, the existing hard failure remains; there is no
successful empty coverage result for an unusable table.

Existing claims, legacy coverage string, exact span checks, duplicate/overlap rejection,
unknown status ownership, decision=null and ineligible-for-scoring flags remain.
Fields are additive in an internal evaluation result, not the v1 public API.
Rollback: use the prior evaluator; old immutable responses and results stay intact.

## Stored-response results

Same five image responses/source snapshots as evidence/source-binding/replay.json;
new detailed outputs in `.local/document-coverage-wave`, hashes/counts in replay.json.
No new API call or altered receipt/ledger. Budget remains USD7.68289506 committed/
reserved out of10, including the same six historical unsettled reservations.

| Crop | Data candidate cells | No bound quote | Residual text | Fully quoted |
| --- | ---: | ---: | ---: | ---: |
| Naver | 4 | 1 | 3 | 0 |
| KB investment | 9 | 6 | 0 | 3 |
| KB opportunities | 20 | 0 | 20 | 0 |
| Kia numeric0 | 8 | 8 | 0 | 0 |
| Kia numeric1 | 4 | 4 | 0 | 0 |

These45 cells are a structural scope, not45 claims. Naver residuals include statuses,
bullets and the known ambiguous recycling task. KB investment residuals are numeric
amounts/funding-source text; KB opportunity residuals are bullets. Kia outputs are
numeric-only cells. This accounting enables targeted review without calling numeric
cells missed narrative claims or turning empty output into absence. Existing30
linked proposals and1 unbound proposal are unchanged; none is approved evidence.

Coverage only concerns cells already present in the selected native table. Missing
parser cells, crop-external titles/footnotes, table detection and semantic completeness
remain outside this metric. It is neither whole-report coverage nor claim recall.

## Verification

Fail-first regressions exercise omitted rows/cells, partial spans with standalone
status, empty model output and a conflicted source cell. Final checks recorded below.

## Orca review

Run run_ed40d756d489, read-only task task_929ddcb46b44, Muse Spark1.3 Free dispatch
ctx_2d31c4689814. Worker inspected the final diff, confirmed omission/conflicted-cell
accounting and identified numeric footnote-marker-to-body linkage as still unresolved.
No file writes or paid extraction calls by the reviewer. The initial completion had
a mistyped sender handle and was rejected; it was not treated as completion. After
coordinator guidance to copy the original injected preamble, corrected worker_done
msg_3217693d68ca settled successfully. Release returned retained/external_terminal;
the exact coordinator-created terminal was then closed (ptyKilled=true). No remaining
reclaimable worker resources. Full tests are coordinator-owned evidence below.

Numeric footnote body linkage and crop-external note selection remain deferred:
existing normalize.py has explicit footnote edges; nearby-page context is merely a
candidate and cannot certify marker ownership. No distance heuristic was promoted
to accepted numeric evidence in this wave.

- `uv run pytest -q`:1,789 passed,2 existing warnings,119.93s;
  `.local/document-coverage-wave/pytest.log`.
- Focused `tests/integration/test_table_atomic_claims.py`:17 passed.
- Ruff over apps/packages/tests/evaluation passed; mypy161 files passed with
  existing untyped-function notes; four Python packages built.
- `uv run python scripts/validate_package.py`:755 documentation/contract checks
  passed (not an application or model accuracy benchmark).
- `git diff --check` passed. New model/API, full-report accuracy, web UI/E2E,
  AWS and production deployment trials: not_run this wave; no corresponding
  implementation was changed.
