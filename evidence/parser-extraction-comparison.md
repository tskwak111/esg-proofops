# Real parser and extraction comparison — 2026-09-12

This is a development sample, not a production acceptance or human gold benchmark.
Inputs and raw receipt hashes: `parser-extraction-comparison.json`; local artifacts
remain in `.local/parser-comparison/`. No source was promoted to verified and no
grade/label was issued. Original reports were preserved.

## Parser findings

Three selected pages per report, using original physical pages LG Chem 25/97/99,
Hanwha Aerospace 28/90/110, Samsung SDI 35/115/126. Hanwha uses a separately hashed
content derivative: one mouse-down URL action removed, all three rendered images
pixel-identical. The original still fails the existing upload security policy.

| Report | Local seconds | Standard seconds | Enhanced seconds |
|---|---:|---:|---:|
| LG Chem | 1.11 | 7.07 | 9.83 |
| Hanwha derivative | 1.05 | 6.78 | HTTP 429 |
| Samsung SDI | 1.45 | 7.80 | 21.88 |

Single observations, different processing paths, no throughput or p95 claim.
Local graph recount: LG 211, Hanwha derivative 144, SDI 363 `table_cell` blocks.
The original diagnostic counter incorrectly queried kind `cell`; its zero count
is not evidence of absent tables. Original receipts retained.

Nine preselected rows cover 27 year-value cells, but no aggregate accuracy score
is claimed: the development reference lacks human approval and cell matching
needs to distinguish text presence from correct row/year/unit attribution.

- LG: both paths retain domestic renewable electricity 622/511/335 MWh. This does
  not establish support for the narrative's 93 GWh procurement claim.
- Hanwha: local tables preserve selected Scope 1, total and renewable energy rows.
- SDI: local text retains direct emissions 242,116/272,196/282,108, but it is a
  combined paragraph, not a correctly extracted structured table row.
- SDI Standard misplaces the direct-emission label. Enhanced restores that row,
  but labels the Scope 3 total 1,203,935/2,208,938/2,051,175 as purchased goods;
  the source purchased-goods values are 789,059/1,029,887/911,604. Further rows
  also shift. An API table is therefore a candidate, not trusted evidence.
- Reference label correction: SDI recycled-metal metric is 사용률, not 사용량.
  `expected-rows-v2.json` records the correction; original reference is retained.

Decision: keep local parsing; offer external parsing as a bounded evaluation/
recovery candidate. Do not globally switch defaults or approve API-derived cells.
Five settled parser calls cost USD 0.297 including the VAT allowance. Hanwha
Enhanced's 429 retains USD 1; it was not automatically retried.

## Actual extraction defect and fix

The new adapter used canonical ASCII JSON as model text. Korean characters were
literal Unicode escape sequences inside the model's user message. All three
selected paragraphs produced invalid quotations (rewriting, wrong meaning or
literal escapes) and were rejected. The shared canonical hash format remains
unchanged; only the model-facing payload now uses literal Unicode JSON. The
extraction rule hash changes to distinguish the new input representation.

On the same three source paragraphs after that change: LG 7, Hanwha 4 and SDI 2
proposals passed exact unique non-overlapping source-span validation. Before/after
receipts are separate, no failed response was overwritten. One observation per
paragraph/version establishes improvement here, not general accuracy or recall.
Context-dependent fragments still require their parent paragraph for evidence
search; literal validity alone is not proof of atomicity or substantiation.

The adapter also rejects overlapping repeated substrings (e.g. 가가 in 가가가),
invalid source hashes, schema/grade additions and quote overlap. It pins identity,
model/prompt/rule hashes and preserves successful transport content before
extraction validation. Shared budget remains USD 10: 120 calls, 3 unsettled,
USD 3.3401504700 committed/reserved after this comparison. The three unsettled
reservations are included, not additional spend.

## Remaining service gates

Real extractor is injectable but API/worker composition remains synthetic-only.
Run-level usage accounting, bounded E-block batching, real evidence/tagging wiring,
untagged claim detail UI and upload-to-review browser acceptance are not complete.
Do not bypass processing-region/rights bindings or source quality to enable them.
Human domain gaps remain blocked. No public deployment was performed.

## Verification

- `uv run pytest -q`: 1489 passed, 2 warnings (before Unicode-only change).
- Unicode regression: failed before change, 15 extractor tests passed after.
- `uv run ruff check .`: passed before final formatting; final scoped checks follow.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src`: 132 files passed.
- `uv run python scripts/validate_package.py`: 734/734, documents/contracts only.
- Architecture and license/supply-chain scripts passed.
- `npm --prefix apps/web run build`: passed (TypeScript and Vite).
- Real-service browser E2E and deployment: not_run; synthetic tests do not substitute.

Final adapter review added exact reservation settlement, mandatory billing-mode coverage, private parser archives, hard budget/rate-limit stops and recoverable model-output failures. See `upstage-adapter-review.md` coordinator disposition. `uv run pip-audit` found no known vulnerabilities; four local workspace packages are not PyPI-auditable. Final lint and 132-file mypy checks passed.

Final post-review full suite: `uv run pytest -q` — 1496 passed, 2 warnings, 97.17s. Final architecture check passed; package validator 735/735 (new comparison JSON included). No additional live calls after the measured Unicode comparison.
