# Cross-report service evaluation — 2026-09-12

Status: development evaluation; **not service ready**. Machine-readable source,
page, manifest, map, receipt and cost references: `cross-report-service-results.json`.
Orca run `run_c113b48f36e3`: Muse Spark 1.3 Free implemented stable selection;
Muse Spark 1.2 Free audited evidence linking. Coordinator corrected the worker
regression test and unsupported audit assertions. Both tasks settled and external
terminals explicitly closed; reclaimable worker list is empty.

## Actual sample and calls

Five additional companies span machinery, automotive, food, finance and IT.
Each successful report uses three developer-selected physical pages: E narrative,
ESG data (embedded in E for KB), and appendix. This is not full-report coverage or
an approved automatic section scope. The original PDFs were not modified.

| Report | Physical pages | Local parse | Baseline / experimental claim proposals | Unknown outputs |
|---|---|---|---|---|
| Doosan Bobcat | 27, 97, 110 | 254 blocks, 2.35 s | 16 / 17 | 0 / 0 |
| Kia | 24, 106, 128 | 562 blocks, 2.44 s | 17 / 21 | 1 / 0 |
| CJ CheilJedang | 19, 108, 128 planned | PDF_INVALID | not_run | not_run |
| KB Financial | 30, 46, 109 | 474 blocks, 1.74 s | 14 / 12 | 0 / 0 |
| Kakao | 47, 114, 130 | 373 blocks, 1.87 s | 13 / 10 | 0 / 0 |

CJ's original fails the action guard on an automatic `/AA` action with `/S /Named`
and `/N /Print`. It was not sanitized, sent externally or excluded from reporting.
This is an upload compatibility limitation, not proof that its text cannot parse.

Identical sets of 20 source paragraphs per company were verified before comparing
prompts: 160 real Solar calls. Standard Document Parse: 4 × 3 pages; enhanced:
Doosan and Kakao, 2 × 3 pages. Six parser calls, 18 billed pages, 166 total new calls.
All new calls settled; added USD0.3513762450. Shared ledger now has 310 calls,
USD3.6945506700 committed/reserved of USD10, including three older unsettled
reservations. No reservation was cleared to make room for this wave.

## Changes retained

- Stable bounded real-worker paragraph selection sorts by physical page, bounding
  box and text, independently of generated source UUIDs. Nonparagraph and excess
  inputs remain unknown. The rule descriptor freezes this policy; incompatible
  old queued extraction profiles fail before calling a model. Old stored revisions
  and replay discovery order remain intact.
- Section-map policy v5 recognizes ESG Fact Sheet / 지속가능경영 Data, indirect
  annotation/destination arrays, rotated TOC markers and multi-column CONTENTS.
  It still requires actual internal destinations and preserves unknown/conflict.
- Evaluation CLI `uv run python -m evaluation.cross_report_probe --folder PATH
  --action extract` prints a plan without API calls. `--invoke` explicitly enables
  a bounded paid run against the existing ledger. Original and sample SHA checks,
  unique archives and shared budget/429 hard stops are enforced; partial outcomes
  record selected/processed/unknown counts and propagate the stop error.

Candidate page counts changed as follows; these are coverage observations, not
precision or approved section boundaries:

| Report | E pages before → after | Evidence pages before → after |
|---|---|---|
| Doosan | 0 → 12 | 19 → 30 |
| Kia | 32 → 32 | 63 → 63 |
| CJ | 46 → 46 | 58 → 71 |
| KB | 48 → 48 | 72 → 72 |
| Kakao | 0 → 9 | 0 → 34 |

## Experiments not promoted

The stricter prompt removed some glossary/risk-label proposals and recovered Kia's
previous invalid output, but Doosan gained a heading proposal and retained a
truncated KPI assertion. Counts are not accuracy scores: no independent human gold
exists and differing boundaries change proposal totals. The experimental prompt
was archived and **reverted from the runtime default**; it is included in the JSON.

Standard/enhanced parsing both left Doosan's KPI sentence split and Kakao risk
labels present. E-page element counts remained 38/38 (Doosan), 24/24 (Kakao).
Enhanced sometimes generated a figure description; this is not source-exact evidence.
These observations do not establish table value/year/unit accuracy. No parser
default changed and no returned source was promoted to verified.

The evidence audit found lexical candidates with mismatching Scope/period context,
not a reproduced production binding bypass. Actual four-identity search guards are
regression-tested; see `cross-report-link-audit.md` for the correction to the worker's
hard-coded archive claims. No LLM grading or unverified accepted evidence was added.

## Verification

- `uv run pytest -q`: 1531 passed, 2 dependency deprecation warnings, 104.14 s.
- New `uv run pytest tests/unit/test_cross_report_probe.py -q`: 3 passed.
- `uv run ruff check apps packages tests evaluation`: passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`: passed, 150 source files.
- `npm run build`: TypeScript and Vite passed.
- `uv run python scripts/verify_architecture.py`: passed.
- `uv run python scripts/validate_package.py`: 737/737 document/contract checks only.
- Locked dependency `pip-audit --strict --no-deps --disable-pip`: no known vulnerabilities.
- `pnpm audit --audit-level low`: no known vulnerabilities (Node deprecation warning).
- New browser E2E for this wave: not_run. Existing local real-upload/browser evidence
  remains in `local-upstage-service-pilot.md`; this wave did not change UI routes.
- Human benchmark, deployed load/SLO and cloud acceptance: not_run.

## Next acceptance work

1. Reuse the existing local sentence selection / parent-context atomic extraction
   pilots to address fragments and nominal labels; evaluate on these frozen inputs
   plus untouched companies before runtime promotion. Count every model call in
   the same budget. Preserve unresolved spans rather than silently dropping them.
2. Test E → DATA/APPENDIX retrieval on source-reviewed claim/evidence pairs,
   including metric, period, entity, unit, boundary and target-vs-result negatives.
   Validate table coordinates and values against original rendered pages; agreement
   between parsers cannot authorize `present`.
3. Obtain independent human gold and unresolved domain decisions before reporting
   precision/recall or activation-ready rule outcomes. Real API success and passing
   engineering tests cannot close those gates.
