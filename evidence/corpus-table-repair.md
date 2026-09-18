# CORPUS-TABLE repair — graph_fusion evidence

Scope: owned files only — `packages/proofops/application/ingest/graph_fusion.py`,
`tests/acceptance/test_parsing.py`, this note. `parsing/opendataloader.py` (root)
and upload security (other worker) were not edited. Read AGENTS/master/v2-original,
docs 26/27/28/31/19, `evidence/corpus-first-pass.md`, baseline
`.local/corpus-first-pass/baseline.json`. Local processing only: no original-PDF
changes, no product/cloud/model calls, no new deps/commit/push. Commands used
`uv run --no-sync`.

## 1. Geometry / grouping / provenance (KOGAS physical 68, printed 134–135)

Measured on preserved candidates
(`.local/.../ee959ab9-6272-472d-9b98-3c73c3597609/candidates.json`), canonical space:

- OD table `193` native `[56.693, 275.852, 549.921, 433.564]` vs auxiliary
  `p68-t3` native `[210.827, 275.112, 551.596, 433.439]` → canonical IoU **0.682**
  (< 0.8). The overlapping tables correctly stay separate; neither parser is
  preferred.
- Agreeing cells are co-located but grid-shifted: `2021년` OD
  `(row 1, col 3)` vs auxiliary `(row 1, col 2)` → IoU **0.882**; `단위` →
  **0.874**; `17` → **0.909**. Pre-fix the exact-context gate blocked every
  cross-parser merge: **0** multi-candidate table/row/cell blocks on p68
  (359 cells + 83 rows + 11 tables, all singletons, all `unverified`).
- Fragmented bundle `p68-t3-r0-c2` (`2022년\n19\n56\n95\n0\n0\n26`, tall
  multi-row cell) vs OD `2022년` header → IoU **0.154**; vs OD `19` → **0.136**.
  `r8-c2` (`88\n89`, two rows bundled) behaves the same. Bundles can never reach
  the merge threshold, so no values are inferred or split by fusion.
- Provenance correction (coordinator msg_3d9c302ea115): OD raw carries
  7 tables / 45 rows / 191 cells with row/column/span fields across the sampled
  pages; OD rows omit bbox, which is the intended `unlocated` contract — no
  coordinates were invented. No parser is privileged either way.

Post-fix effect on the same preserved candidates (v2): **115** agreeing cells
fuse into two-family (`opendataloader`,`pdfminer`) blocks; 11 tables stay
separate singletons; the tall bundle stays a singleton; candidate retention
783/783; 701 edges, none dangling. Agreeing merges gain provenance; genuine
same-region disagreements become `conflicted` with no winner (none occur on p68
at IoU ≥ 0.8; the 2022 column stays honest singletons on both sides).

## 2. Upstream findings for root (adapter-owned, not fixed here)

- The auxiliary grid drops the first (`구분`) column of the board table and folds
  the 2022 data column into one tall header-anchored cell; `r8-c2` merges two
  rows (`88\n89`); headers lose the first column. Header/year-column loss
  originates upstream of fusion.
- Suggested root-side handling only: keep emitting the fragmented cells
  untouched (fusion depends on that), and consider an explicit
  fragmented-table/unreadable-column signal rather than silent bundling.
  Fusion must not split bundles or reassign years — it does not.

## 3. Version contract (coordinator msg_57382a964325 / msg_b376f633c1ae)

- `fuse_candidates(..., fusion_version: int = 2)`. v1 = legacy: full context
  equality for every kind. v2 = for `table_cell` only, ignore entries starting
  with exactly `row number=` / `column number=`; **all other context entries
  (scope/table/title/year/unit/…) still gate**, so different explicit scope on
  the same bbox never merges. Unknown versions (`0, 3, "2", None, True`, …)
  raise `ValueError("unsupported fusion version")`.
- Old-manifest semantics: `fusion_version=1` byte-reproduces the preserved
  KOGAS `graph.json` (778 blocks, verified locally); default call equals v2.
  Root's adapter records v2 on parse and defaults missing→v1 on reload
  (verified present in worktree diff; root ran reload tests + 4 baseline
  manifests unchanged). No schema or manifest-field change on my side, so no
  metadata-contract change was needed.
- `docs/27 §5` alignment: region overlap selects candidates; small-cell
  table alignment is still upstream's grid, which fusion does not rewrite.

## 4. Tests and verification (owned scope)

- `test_kogas_style_shifted_grid_cells_merge_without_merging_tables_or_bundles`:
  synthetic shifted-grid fixture (no real PDF data), written RED first
  (failed `assert 1 == 2` pre-fix), green post-fix. Pins agreement fusion,
  bundle/table/row separation, conflict-without-winner, lineage (merged cell
  keeps both row parents), order determinism, full candidate retention.
- `test_fusion_version_gate_keeps_v1_legacy_and_v2_semantic_context`: v1 keeps
  4 singletons; v2 fuses only the scope-matched pair; scope-mismatched pair
  stays separate (negative semantic guard); unknown versions rejected.
- Full file: `11 passed`. `ruff check` clean, `ruff format --check` clean,
  `mypy` clean on `graph_fusion.py`. Real-parse acceptance tests in the same
  file pass unmodified. Broad suite + final-50 rerun are root's per instruction;
  no duplicate integration tests were added here.

## 5. Remaining conditions

- Root: final-50 rerun and broad-suite results; confirm v2 manifest/reload
  behavior on fresh parses.
- Downstream (TASK-004 tables): consume two-family agreement and open
  `parse_conflict`s; numeric year–value–unit tuples still need row/column
  lineage from the (separate) tables — fusion deliberately does not join them.
- The 50 PDFs were used for diagnosis only; they are not a holdout for any
  later accuracy claim.
