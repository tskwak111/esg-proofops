# Source-table numeric basis review — 2026-09-12

## Concrete source findings

Inspected rendered physical pages 97 and 99 of the pinned LG Chem PDF. Poppler
was unavailable; used the already-installed PDFium renderer (no new dependency).
The render hashes and exact source/table-cell references are recorded in
`numeric-basis-review.json`. Visual inspection here is a coordinator diagnostic,
not an approved source-quality or vision profile; graph quality is unchanged.

- p97, 2025 domestic Scope 2: Location-based 2,813,566 and Market-based 2,770,838.
  Their arithmetic difference is 42,728. The p97 footnote describes deducting
  REC/green-premium reductions from Location-based emissions to calculate
  Market-based emissions. This is a plausible review trail for the p25 reduction
  statement, not proof that it is the same quantity/entity/period or that a
  rounding rule makes it consistent with approximately 4만 톤.
- p99, 2025 domestic renewable electricity: **335 MWh**, including MWh on the
  rendered PDF itself. The p25 parent says approximately **93GWh**. Exact unit
  conversion gives 93,000 MWh, so the displayed values differ. This is an apparent
  source value/unit issue to review after attribution, not a parser repair or an
  accepted numeric inconsistency finding. Do not relabel MWh to TJ to make 335
  resemble 93GWh. The p99 notes about electricity conversion and REC/green-premium
  coverage are retained; they do not authorize changing the displayed unit.

The p25 parent span does not contain an explicit reporting year. A preceding
paragraph mention of 2025 is not inherited as an accepted claim period. Carbon
`톤` is also not silently normalized to tCO2e. The raw p97 subscript text order
is preserved even though the rendered table visually shows tCO2e.

## Preserved review material and checks

Selected thirteen original cells for values, subjects/bases, units, headers and
metric context. These are coordinator role hypotheses, not accepted table-role
tags or normalized observations. Kept each native table/row/column, parser run,
page/bbox, quote, hash and source quality, plus three original method notes and
the original claim candidate. Computed 42,728 only as a review arithmetic result.
No numeric engine acceptance, quality update, comparison label or grade occurred.

`PYTHONPATH=. uv run --no-sync python .local/numeric-basis/replay.py` loads the
PDF-validated graph, rebinds all selected cells and notes, checks the literal
2025 headers and displayed units/values, and verifies the diagnostic difference.
`uv run --no-sync pytest -q tests/acceptance/test_numeric.py tests/acceptance/test_binding.py`
— 118 passed in 1.58s. No application code changed; full lint/type/build/E2E suite
was not repeated. The last full application checkpoint remains 1,459 tests.
Live model, approved vision/source quality, real accepted binding and deployed
AWS/E2E checks: not_run.

## Agent audit and limits

Orca run `run_a3878312753d`, task `task_55aa6cf3bf13`, dispatch
`ctx_d639c81de0c9`, OpenCode Muse Spark 1.3 Free completed read-only numeric/binding
review. It found no reproducible guard flaw and identified absent accepted
bindings, unverified source quality, unset claim year and unit/measurement-kind
problems. Its exact predicted return status depends on which guard runs first;
no real accepted ClaimBinding was fabricated to force a computation. In particular,
the numeric engine's temporal reduction-rate kind is not a same-year subtraction
between Location-based and Market-based emissions. No new computation kind or
domain criterion was introduced. The worker was released, terminal closed and
delivery acknowledged.

Next prerequisite for an accepted comparison: source-quality confirmation,
explicit subject/period/metric and basis-role tagging, and an authorized relation
between the claim and the chosen table values. The displayed energy unit/value
issue needs source clarification; the system must not silently make values agree.
No model calls or ledger changes. Last committed/reserved total remains
$2.0411683250 / $10, including two previously unsettled calls.

`uv run --no-sync python scripts/validate_package.py` — 733/733 documentation
and contract checks passed, separately from the numeric/binding tests.
