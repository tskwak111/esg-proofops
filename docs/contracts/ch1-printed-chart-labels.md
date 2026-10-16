# CH1 printed chart and image-table recovery

Authority: `quality-CH1.md`, DEC-25, DEC-85/92/93. Baseline `ac1f0e6` (v25).
This is an opt-in local extraction reader and immutable review artifact. It does
not replace the canonical graph, change a default, publish a claim, or admit a
grade fact. No shared profile or source-reader registry entry is changed.

`ch1_charts.extract` accepts original PDF bytes, tenant/run/document/parse identity,
selected physical PDF pages, and bounded layout proposals. A proposal describes
bar, line, pie, or image-table regions, row/column/single alignment, local legend
and unit labels, and any known axis-tick IDs. It does **not** supply measurement
values. Existing vision/parser output or a reviewed region selection can supply
these hints. Automatic whole-page region/legend discovery is not implemented.

For an unlocated figure, two or more exact OCR anchors can recover a region;
no synthetic zero box or guessed figure coordinate is used. The deterministic
layout reader selects printed numeric words and proposes aligned years. A missing
label remains missing; bar length, line interpolation, pie area, and inferred
percentages never supply evidence. Multiple same-unit series and year ties remain
unknown. Axis values must be identified as ticks in the proposal and are excluded.
This reader does not prove that a detector correctly distinguished an axis from a
data label: all semantic binding remains unknown, including apparently aligned
tuples. Layout hints are extraction inputs, not an authorized evidence scope.

Every value, unit, year and legend is independently matched to exact whole OCR
words of the original annotated PDFium render. Coordinates and polygon vertices
come from OCR, not the proposal. All selected words require confidence >= 0.98.
Repeated text needs explicit word IDs; disconnected/overlapping/tilted/low-confidence
words remain unknown. Unit and year slices retain the entire original word and
its bbox; measurement values cannot be sliced or repaired. Thousands separators,
printed percentages and unit multipliers remain literal. This supports scanned
image tables without pretending they contain native PDF glyphs.

The immutable OCR collection must match the private trusted SQLite ledger,
tenant, original-source hash, render hash, policy and response bytes. The artifact
binds document version, parse manifest, run, selected pages, layouts, proposals,
page reads and code/policy hashes. Cold replay re-renders and recomputes all proofs,
never invokes acquisition, and preserves recorded missing-cache failures even if
new cached data subsequently appears. CLI replay also re-runs layout extraction.

`status=verified` has the explicit scope `printed_labels_only`. It means all four
proposed fields have printed source proofs; it does **not** mean that their
association is approved. Every observation has `binding_status=unknown` and
`eligible_for_scoring=false`. All proposals and their individual proofs are useful
review inputs. Unresolved fields stay unknown, never absent. No record is fed into
present, E grades, or the existing 3/3 fact assembly. A future integration must
retain numeric/year borrowing rules, exact same-chart ownership, conflict handling,
three fresh votes and DEC-93's rejection of inferred performance (AP-04b).

Run `python -m evaluation.ch1_recover --print-policy` in the target image to get
the `ch1_printed_chart_labels_v1` hash. The CLI requires that exact hash plus
`--source`, `--request`, `--ledger`, and a new `--output` path. Request JSON contains
`scope` (identity, source SHA-256 and sorted selected_pages) and `layouts` (above).
It uses the existing ledger read-only and makes zero paid calls. An authorized
runtime can inject the existing bounded `PageOCRStore` to collect missing pages;
this change creates no additional budget or key-loading path. Rollback simply
stops choosing CH1; historical policies, graphs and receipts are untouched.

Validation: real R17 LG Electronics printed labels and their original pages;
fresh Linux ARM64 raster PDF/bar/line/pie/image-table simulation with newly
generated transport responses; strict replay, uncertainty and tamper counterexamples;
QT1/FXF focused regression and frozen DL4/holdout scoring. Simulation is a wiring
check, not Upstage/model accuracy. Detailed results, failed sim diagnostics and
remaining limits are in the task's `lab/quality/CH1/` directory.
