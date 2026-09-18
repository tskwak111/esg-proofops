# Atomic claim pilot — 2026-09-09

Coordinator implementation; Orca run `run_0e115dc53551`, OpenCode Muse Spark 1.3 Free
review `task_07d0bfbf0bae`. Worker completed, released and its terminal closed.
No dependencies, production API/DB contracts, source approvals or grades changed.

## Implementation and real trial

`evaluation.atomic_pilot` reuses `discover_atomic_claims`, `StructuredClaimExtractor`
and exact quote validation. The earlier candidate artifact supplies target character
ranges. Full paragraphs provide context; only target-contained exact quotes can become
claims. Unknown gaps remain unknown. Invalid, overlapping or out-of-source ranges fail
before a model call. Model replies outside targets fail the source response rather than
silently dropping offending quotes. Original application packet and actual wire packet
have separate hashes; prompt, map, extraction rules, model and raw response are retained.
Nonselected blocks are deferred locally: a processed receipt is not a model call.

LG Chem pinned PDF SHA256:
`c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde`.
Fresh manifest `1aaf9890-eaef-4898-812c-0718a63036a7` from the previous 57-page parse.
Input: `.local/section-pipeline/live-two-packets/result.json` (13 sentences, 8 sources).
First trial: `.local/atomic-pilot/first`, 8 calls / 13 candidates, including an unwanted
industry-background sentence and standalone introduction. That prompted the target guard.
Second: `.local/atomic-pilot/targeted`, 8 calls / 12 candidates, no invalid spans.
It recovers the Net-Zero Portal management sentence and excludes context-only industry
background, but omits the K-taxonomy management target. Several compound sentences and
an attached introduction remain. Source-exactness is tested; semantic completeness and
atomicity are NOT established. This is a development case, not a held-out accuracy test.

Total this turn: 16 calls, settled estimate $0.002813745. Shared ledger after trial:
79 calls, $2.034728870 committed/reserved of $10, including two earlier unsettled calls.
Ledger and both trial artifacts were preserved. No Bedrock or AWS calls.

## Evidence review and coordinator corrections

Worker observations are in `atomic-evidence-worker-review.md`; these are review notes,
not accepted bindings or source verification. Coordinator rendered original physical
pages 4, 24 and 97 using installed pypdfium2 after finding Poppler unavailable.
Images are retained in `.local/atomic-pilot/p4.png`, `p24.png`, `p97.png`.

- p24 visually attaches 890 (unit: 만 톤) to 2025; 951 belongs to both 2019 baseline
  and 2030 carbon-neutral-growth target. This resolves the worker's chart ordering doubt.
- The worker's “rounding-consistent” suggestion is NOT established: 8,889,779 / 10,000
  is 888.9779, ordinarily rounding to 889 at integer precision, not 890. Difference
  from the chart is 10,221 tons. No rounding policy or tolerance was invented; leave
  the chart/table comparison unresolved, without a conflict/false grade.
- p4 explicitly excludes LG Energy Solution/subsidiaries and FarmHannong from report
  coverage. This is document-level context outside the selected graph, not automatic
  proof of the target's 2019 entity boundary or Scope 2 method. No graph scope expanded.
- p97 visually confirms 2023–2025 headers, Market-based global Scope 2 footnote and
  provisional 2025 domestic figures. 2019 is not a column in this table; this does not
  establish absence elsewhere in the report. Historical totals cannot by themselves
  confirm the project-level 30,000-ton saving or future goal attainment.
- Assurance coverage remains undetermined. Broad assurance language must not become
  blanket coverage of a particular goal or project claim. Worker coverage inferences
  are not machine-approved facts or new domain rules.

The existing `normalize_table_bindings` was replayed on p97 rows 1/5/9 and columns
3/4/5: explicit global Scope 1+2, Scope 1 and Scope 2 observations for 2023–2025.
No merged blanks were filled. `.local/atomic-pilot/table-observations.json` retains
role assignments, raw units, source references and quality. All nine observations
remain unverified; 222 existing graph quality issues remain. This is a pinned case, not automatic table-role detection.

## Validation

Commands: `uv run --no-sync ruff check .`, `ruff format --check .`, mypy across
packages/apps/evaluation/load/staging gate, `uv build --all-packages`,
`python scripts/verify_architecture.py`, `python scripts/check_licenses.py --root .
--env ENABLE_LEGACY_PYMUPDF=false`, and `python scripts/validate_package.py`, all
through the locked uv environment. Lint/format, 144-source type check, four-package
build, architecture and supply-chain gates passed. Documentation/contracts: 707/707.
Full suite: `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q` — 1,425 passed in 111.87s; two existing Starlette/AnyIO deprecation warnings. Real production API E2E and
AWS remain not_run. No claim of production readiness or measured precision/recall.

Next: evaluate missed/compound claims across more E subsections; carry explicit
metric/year/Scope/unit/entity and source quality into evidence-binding review.
