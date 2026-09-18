# Dense-page note diagnostics — 2026-09-14 KST

The service-readiness goal remains active. These changes improve actual input and
source-bound proposals; they do not finish the service, semantic acceptance, or
numeric integration. The previous turn was progress, with a real implementation
commit and measured failures that determined this follow-up.

## Shipped changes

- `UpstageProbe` checks and sends identical compact UTF-8 JSON bytes. Its16KB body
  limit, USD1 reservation, USD10 cumulative ledger policy and settlement remain
  unchanged. No ledger migration/reset or increased request allowance was used.
- Note discovery omits character-level typography but retains every fragment's
  complete text and four-coordinate box. The full immutable packet retains native
  geometry; only model-wire coordinates are rounded to0.1pt. Shortened discovery
  prompts and coordinate-removal/XY-only experiments caused regressions and were
  reverted. They are not the final behavior.
- Discovery's provisional kind strings stay in raw receipts; normalized discovery
  notes start unknown. The binding step still validates its supported kinds.
- A model group made solely of complete, individually and distinctly numbered
  lines is split into those source-fragment units. Groups with continuation lines
  are not split by this rule. This is lexical normalization, not semantic approval.
- Native suffix markers support a raised closing parenthesis. Tiny font/position
  floating-point noise no longer makes ordinary Scope1 a styled word. Raw native
  character geometry remains unrounded in the packet.
- An explicit `데이터 커버리지:`/`data coverage:` note can propose only a uniquely
  horizontally aligned, vertically separate table. Multiple aligned tables stay
  ambiguous. A neighboring metric cannot replace that table target.
- Binding requests contain only supported marker/coverage targets and their needed
  typography. Notes without an anchor remain unknown without a futile second call.
  Bare numeric fragments cannot trigger unrestricted ownership requests.

No domain grading criterion, accepted source quality, numeric result, graph
footnote edge or production API/DB contract was changed. Existing frozen receipts
and outputs were not rewritten to conceal failed variants.

## Original-PDF inspection and real calls

The coordinator viewed Kia, KB, Naver, Kakao physical114 and Samsung Life physical121
original page images. Local review artifact:
`.local/table-note-wave/dense-review.html`.

Final controls are `.local/table-note-wave/final-coverage-controls/{kia,kb,naver}`.
Kia retains all3 conditions and correct proposed owners. KB/Naver return0 external
notes on these inspected pages; this is not validation of their inline conditions.

Kakao's local graph had conflicted metric cells. The existing Document Parse
adapter recovered3 tables and209 cells on that one page. The final archive
`.local/table-note-wave/recovered/kakao/notes-numbered-discovery` retains6 notes,
including the two-line9.6MJ/kWh conversion condition. Four proposals match the
visually inspected metric cells: Scope3 share, indirect-energy conversion,
investment exclusions and renewable-energy total. Notes3/4 attach to table titles
outside the current word-suffix target path and remain unknown. The original
source/version and new parse snapshot remain explicit; cells remain unlocated,
not approved evidence. Current-code source replay passed for all four controls.

Samsung Life's local graph had2 conflicted data tables. Document Parse recovered
3 tables and296 cells, but the final rich-geometry discovery request still exceeds
16KB and is stopped before billing. Rejected compact experiments are preserved:
one found11 of12 actual notes plus a false numeric candidate363, missing the
commuting-basis note5. A more aggressive XY/prompt experiment merged unrelated
notes and selected table markers. These are observed failures, not a quality
benchmark or accepted output. Standalone/prefix markers and repeated note numbers
still need a different source-bound ownership path.

This turn made36 settled paid calls (2 parser calls and34 text calls), costing
USD0.0730239400. Shared committed/reserved total is USD7.7710933900 across1319 calls;
all6 old unsettled reservations remain unchanged. No AWS call or deployment.

## Verification and Orca

Muse Spark1.3 Free reviewed UTF-8/preflight parity and source-preserving request
compaction in Orca run `run_bd4f467aede6`, task `task_8f53543f4d87`, dispatch
`ctx_e0f37f5c34ce`. Its accepted report found no transport/budget blocker. The
worker was released and its exact externally created terminal closed; no
reclaimable worker remains. Later note-normalization and coverage changes were
coordinator-tested against the original PDFs and regression fixtures.

- Fail-first: Korean request falsely too large; typography float noise; parenthetic
  marker rejected; missing anchors spending a second call; merged numbered notes;
  numeric-only unrestricted candidate; coverage attached to a neighboring metric.
- Focused tests:36 passed.
- `uv run pytest -q`:1816 passed,2 existing deprecation warnings,114.22s;
  `.local/table-note-wave/pytest-dense-stable.log` is the final-code log.
- Ruff passed. Mypy162 files passed with existing untyped-function notes.
- Four Python package builds passed. `git diff --check` passed.
- Document/contracts validation is recorded separately and is not an app benchmark.

The next work remains the original goal: dense-page discovery without condition
loss, standalone/prefix/title-marker ownership, accepted condition interpretation
and original-source lineage in the actual service flow, then service E2E and
independent quality checks. The numeric checker still has no direct app caller.
