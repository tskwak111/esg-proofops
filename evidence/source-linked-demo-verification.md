# Source-linked report demo — 2026-09-13

Baseline79e2609. This wave builds a runnable local review artifact from real
archived extraction, actual graph retrieval and actual parser receipts. It does
not activate the production non-synthetic tagging worker or evaluate grades.
The earlier proposed full PDF-to-decision flow remains incomplete at those gates.

## Implementation

`uv run python -m evaluation.report_demo` loads the original PDF through the
existing manifest/hash validation, validates source-bound extraction archives,
replays `discover_atomic_claims`, uses `SectionSearch` and `retrieve_evidence`,
and attaches numeric table candidates from the verified request/response/page
mapping. No raw hit or reconstructed table becomes accepted evidence. Unprocessed
text stays unknown; decisions remain null and rule evaluation is explicitly not_run.
No fake tokenizer is supplied: a request needing one stops with its actual reason.

The standalone HTML provides exact claim quotes, candidate text, original PDF page
links, reconstructed tables and readable year/unit/metric/value rows. JSON retains
source/version/manifest/graph/map/rule/profile and extraction receipt identities.
Source PDF is copied and hash-checked, not edited. Output directories are create-only.
Static HTML escapes report text and has no scripts, external resources or model calls.
No API/DB changes, new dependency, source-quality approval or old revision overwrite.

Run example (workspace-private inputs; no credentials needed):

```sh
uv run python -m evaluation.report_demo \
  --selection .local/tagging-holdout/samsung-life/body-and-evidence/selection.json \
  --section-map .local/report-demo/samsung-life-sections-final.json \
  --extraction .local/tagging-holdout/live-v2/extraction/a0ae20bb-b893-58f7-9385-5baa99950ba1 \
  --table-receipt .local/showcase-eval/samsung-life/response.json --table-page 121 \
  --output .local/report-demo/new-samsung-review
```

The section map can be freshly generated using `evaluation.report_sections`.
Selection files name the original source and parser manifest. This is a review
replay command, not an arbitrary new-PDF inference endpoint.

## Actual finding and root fix

KEPCO initially replayed zero claims: source page75 was inside a map conflict
caused by same-page unclassified large heading “Green in Action” and explicit
TOC link “탄소중립”. `build_map` now ignores only an unclassified fallback heading
when a classified outline/TOC anchor exists at that same physical destination.
Opposed known roles still conflict; fallback-only unknown remains unknown. All
anchors stay retained. A failing-first regression covers these boundaries.

Map policy version9 changes its hash. Old maps remain immutable and require their
original policy for historical replay; new execution must regenerate a new map.
Rollback uses the previous policy with its matching maps. No source or domain
criterion was altered. Candidate E pages increased20→47 in this KEPCO map;
this is routing coverage, not ground-truth scope accuracy. Five conflict pages remain.

## Measured replay output

- Samsung Life:PDF23/24/121/138;2 claims from one prior actual extraction request;
  40 bounded lexical hits total;3 provider tables,87 numeric candidates.
- KEPCO:PDF75/76/205/259;3 claims from one prior actual extraction request after
  routing fix;60 bounded lexical hits total;2 provider tables,114 numeric candidates.
- Both disclose missing E/evidence pages and all unprocessed exclusions. Neither
  is full-report extraction or held-out accuracy. The same source pages were used
  in prior development; archived responses are not new independent replicas.
- Source-backed retrieval returns blocked_evidence for these unverified claims.
  There are0 decided claims. LLM semantic tagging, numeric comparison, assurance
  coverage, consensus and pure-rule evaluation were not run in this demo.
- No paid call this wave. The existing cumulative USD10 ledger was not changed.
  Last established committed/reserved amount:USD7.2721452150, six unsettled calls.

Private deliverables:`.local/report-demo/ready/{samsung-life,kepco}/index.html`,
`review.json`, `source.pdf`. Intermediate baseline and v2 outputs are preserved.

## Verification

- Focused section/retrieval/demo/table suites:56 passed,0.82s; final metadata
  addition separately checked by the2 demo integration tests.
- Ruff over apps/packages/tests/evaluation passed; mypy155 source files passed.
- Four Python packages built. Documentation/contract validator743 checks passed.
- Chromium headless rendered the Samsung HTML; screenshot visually inspected.
  PDF HTTP bytes were independently hash-checked;45 Samsung/65 KEPCO page links
  point to the bundled source. CUA browser connection was unavailable, so visible
  browser click automation was not_run; no click-through result is claimed.
- Full suite:1748 passed, two existing dependency warnings,117.43s.
  After the final mixed-heading guard, the56-test focused suite passed again;
  both actual section maps retained the same candidate pages. No web React/API schema change.
