# Agent visual and candidate review — 2026-09-13

Baseline: 7cc1c04. User delegated candidate judgment and original-PDF visual review.
This is an agent's source-specific assessment, not human gold, an independent
assurance opinion, general accuracy measurement or production evidence approval.

## What was actually reviewed

Original PDFs rendered with installed pypdfium2 at scale 2 and images directly
inspected: Samsung Life physical pages 23,24,121,138; KEPCO 74,75,76,205,259.
The two JSON files beside this document pin the input demo hash, original PDF hash,
image hashes, all five claim IDs, all 100 candidate IDs, and five parser table IDs.
The raw extraction, candidate bindings, table cells, source quality, decisions,
receipts and earlier demo artifacts remain unchanged.

Five extracted claim sentences match the source after whitespace/subscript
normalization. This does not establish atomicity or factual truth: compound
2030/2050 goals and activity/46% assertions need separate semantic judgments;
pronouns retain their preceding paragraph as context.

100 lexical candidates were individually reviewed: 11 partial support, 26 context,
34 insufficient fragments, 14 not supporting this claim, 10 duplicates and 5
self-quotes. These are candidate triage counts, not precision/recall or rule labels.
The UI now prioritizes partial support and collapses the other items with reasons.
It does not silently delete candidates or promote any item to verified/present.

Four data tables and one wrongly categorized navigation menu were visually
compared to the parser output. The menu is excluded from the data-table rendering
and remains in JSON. Important remaining qualifications are shown beside each table:

- Samsung: footnote positions are reordered in parser output. 2024 region/market
  columns must stay distinct. Footnoted year headers remain deferred; company
  subrows lack their preceding Scope subtotal context, and Scope3 items lack
  preceding Category context in numeric candidates. These bindings are not accepted.
- Samsung: data total 66,717 vs assurance total 62,083 differs by 4,634, the Samsung
  Card row; the assurance explicitly excludes that separately assured entity.
  Do not report a contradiction from those differently bounded totals.
- KEPCO: 2024 Scope1 639,296 and Scope2 234,537 agree with the assurance table.
  Their sum 873,833 differs from the stated assurance total 873,712 by 121.
  Preserve this unresolved difference; the source rounding note alone is not
  sufficient to claim this specific discrepancy has been reconciled.
- KEPCO: national transition-sector, power-group and KEPCO separate targets are
  distinct. Page76's 276.2→149.4→0 series is the transition sector.
- KEPCO: extra E page74 visually shows SF6 decomposition demonstration and a
  commissioning photo (banner date 2025-05-29), providing activity context outside
  the original four-page parsed selection. It is an agent note, not a new graph
  source or an invented coordinate. The 46% gas share remains unsubstantiated by
  the reviewed tables; no Scope total is substituted as its denominator.

## Implementation and reproduction

`evaluation.report_demo.attach_agent_review` checks the canonical input artifact
and exact claim/candidate/table coverage, accepts only agent review metadata and
known triage labels, then produces a new hashed artifact without modifying input.
`--agent-review evidence/agent-visual-review/samsung-life.json` (or kepco.json)
can be appended to the prior source-linked demo command, with a new output folder.
The review is explicitly bound to these source artifacts; it is not a hardcoded
company-specific production classifier or evidence approval service.

Outputs: `.local/report-demo/agent-reviewed/{samsung-life,kepco}/index.html`,
`review.json`, `source.pdf`. Original PDFs and PNGs remain workspace-private.
No new dependency, network/model call, API/DB change or cloud operation.
The USD10 ledger was not changed. Rollback omits the optional review parameter;
old demos and original extraction archives are intact.

## Verification

- Failing-first integration regression: 2 passed / 1 failed because review attachment
  did not exist; after implementation 3 passed. Covers immutable source binding,
  incomplete/foreign candidate rejection, agent-only metadata and escaped review text.
- `uv run ruff check apps packages tests evaluation`: passed.
- `uv run ruff format --check evaluation/report_demo.py tests/integration/test_report_demo.py`: passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`: 158 files passed; existing unchecked-body notes.
- `uv build --all-packages --out-dir .local/visual-review/dist`: four packages built.
- `uv run python scripts/validate_package.py`: 745 documentation/contract checks passed;
  this is not an application accuracy test.
- Both actual CLI replays passed with the pinned agent review files. Original PDF
  hashes, all nine page-image hashes, review hashes, unchanged claim/table payloads
  and exact rendered HTML were independently checked.
- Headless Chromium rendered both reviewed HTML files and both screenshots were
  visually inspected. Native visible-browser click automation: not_run (unavailable).
- Actual model calls, semantic tagging worker, production rules, AWS: not_run.
- `uv run pytest -q`: 1,749 passed, 2 existing dependency deprecation warnings,
  146.92 seconds. Includes unit, contract, acceptance, integration, E2E and security
  tests under the repository's testpaths; this does not measure report accuracy.
