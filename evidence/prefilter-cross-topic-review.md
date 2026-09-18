# Cross-topic sentence selection review — 2026-09-09

## Outcome and operating decision

Keep local sentence segmentation and code-owned source resolution. For the next
E narrative extraction, use the broad `all_text` input mode, with lexical filtering
remaining an optional comparison. The filter's savings were inconsistent, while
source conversion and model inclusion of background text caused concrete problems.
This decision does not expand claims into S/G sections or reduce evidence search:
all ESG DATA and APPENDIX must remain available for environmental claim evidence.

This is **one company's development sample**, not independent gold evaluation.
The coordinator inspected rendered PDF pages and original parser data. Draft
reviews are not human-approved labels. Precision, recall and grading accuracy
remain unmeasured; exact source matching proves origin, not claim correctness.

## Paired trials before the fixes

Reuse the previous climate page 24 comparison, and add physical pages 33
(recycling), 38 (water/waste/soil management) and 48 (biodiversity restoration).
Page selection was recorded before calls in `.local/prefilter-study/selection.json`.
Both modes use the same model/prompt/graph per page and the existing shared ledger.
No keyword tuning was applied to improve these results after viewing them.

| Page | All-text → filtered input tokens | Cost saving | Candidate counts | Source validation |
|---|---:|---:|---:|---|
| 24, previous trial | 10,384 → 6,970 | 29.32% | 25 → 21 | Both passed |
| 33, recycling | 7,302 → 6,230 | 9.55% | 30 → 21 | Filtered partial: one failed packet |
| 38, water/waste | 6,350 → 6,160 | 0.26% | 35 → 36 | Both passed |
| 48, biodiversity | 5,112 → 4,164 | 16.41% | 23 → 19 | Both passed |

Costs include the existing conservative VAT allowance, not invoice reconciliation.
The p33 difference of nine candidates is a failed-response effect, **not nine
lexical omissions**. A model mutated one UUID, and the packet was correctly
rejected. Source validation passed on 17 of 18 new calls; all 18 had usable billing
receipts. The smaller input was not uniformly faster: p38 and p48 filtered calls
took longer in these single trials. Do not extrapolate latency from these samples.

Artifacts under `.local/prefilter/`:

- p33: `35856b86-332f-4804-9d1f-6f8f84145116`
- p38: `527d38e3-4e5f-482f-b286-f205a910d309`
- p48: `02f4db87-eda6-45cd-afd3-a7e1ad6282c0`

## Source-context findings

The draft review ledger is `.local/prefilter-study/review.json` (18 entries,
reviewer explicitly identified as the Codex coordinator, `human_verified=false`).
It separates comparison differences from selected background examples.

- **p24:** the three locally deferred phrases occur in a graph/table as plan or
  activity labels. They need their enclosing structures, not automatic treatment
  as three missing standalone claims. The same applies to the additional
  model-selection difference on the low-carbon fuel label.
- **p33:** the model selected process definitions, a GRS definition and regulatory
  background alongside actual company activities and certifications. Adjacent
  company assertions must be separated from those descriptions during atomic
  extraction. No claim is made here about whether the report's legal statements
  are correct or current.
- **p38:** the sole additional filtered candidate was the ZWTL box heading. The
  actual company certification assertions occur in its body. Selecting the heading
  does not establish an additional independent company assertion.
- **p48:** the baseline-only fragments were diagram labels/process text and a
  general impact description. These remain useful context but are not automatically
  independent company claims. The model also selected a general seagrass description.
- **p48 source gap:** a paragraph ended after the equivalent of “local…”. The PDF
  visibly continued with fisheries, marine litter collection and citizen education.
  The original OD JSON contained that continuation under `list items`, but the
  adapter visited only `kids`, `rows` and `cells`. Thus the continuation never
  reached canonical candidates. This was a genuine software omission upstream of
  both model input modes, not an LLM recall result.

Rendered original pages were inspected using the already installed pypdfium2
renderer. The PDF was not changed or re-exported. Original SHA-256 remains
`c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde`.

## Fixes and actual verification

1. **Visit OD list children.** `list items` is traversed and `list item` content
   maps to existing paragraph candidates. Native ID, text, position and parent
   relations are retained. No fabricated text joins or source-quality upgrades.
   A failing unit case reproduced zero recovered children before the fix.

   Identical archived JSON replay confirms native item **798**, absent from the
   old candidate snapshot, now produces an exact candidate citation. Record:
   `.local/prefilter-study/raw-replay-result.json`. This isolates the code change
   from any variation caused by rerunning the parser.

   A separate new one-page parse/reload also recovered the full paragraph:
   `.local/prefilter-study/reparsed/9705bf16-e1e7-4d55-af9d-722b9aa1ba94/86af32c1-b91c-4dcf-8d98-05ce1aae447c/cebb3007-fbd9-407c-8e79-1892bd91f6d0/manifest.json`.
   The original 20-page manifest's bytes and replayed graph remained unchanged.
   The new one-page parse has different block boundaries; it is not a controlled
   before/after measure of parser or model accuracy.

2. **Use short IDs only on the model wire.** UUIDs are no longer copied into
   selected-ID responses. The runner sends `s0`, `s1`, etc. and records an explicit
   mapping per request, the original packet hash, wire packet hash and wire version
   2. It resolves replies back to original IDs before the existing source validator.
   Unknown and repeated IDs still fail. Raw responses and failed attempts remain
   intact. No fuzzy UUID matching or repair of provider text is used.

   New p48 paired trial: **6/6 calls passed**, all-text 22 candidates versus filtered
   19. All three sentences of the restored paragraph were selected in both modes.
   Input tokens were 4,258 versus 4,343; settled costs USD 0.0007586700 versus
   0.0007819350. Here the filter increased cost because context/batching overhead
   outweighed removed targets. Artifact:
   `.local/prefilter/4d1ffb65-de1b-4b63-977e-6bff611a5a1f`.

   The exact previously failed p33 source packet was then sent with short IDs:
   it passed and returned nine candidates. This was a separate protocol regression
   trial, not a rewrite of the original partial comparison. Artifact:
   `.local/prefilter-study/d404e260-842f-41c8-bd16-c60b481ac9f8`.

An intervening long-ID probe on the newly recovered p48 paragraph failed source
validation; it is retained at `.local/prefilter-study/7f321dec-8a2b-45a2-8876-cf8d12e85e4d`.
It is not reported as a successful extraction. The short-ID tests prove ID/source
mechanics on these samples, not perfect semantic selection in future calls.

## Budget, compatibility and remaining work

This task made **26 calls**, including the failed validation attempts. Settled
estimated cost added: **USD 0.0124545300**. Cumulative ledger: **61 calls**, settled
estimates **USD 0.0314100600**, plus **USD 2** still reserved for the two early
unreconciled probes. Total committed/reserved: **USD 2.0314100600**, within the
user's USD 10 limit. Reservations are not known actual charges. No budget reset,
key disclosure, cloud deployment or GitHub push occurred.

There are no new dependencies or API/DB schema changes. Old parser manifests load
their original candidate snapshots and are not upgraded in place. Old comparison
artifacts retain UUID-based wire data; new requests explicitly record wire version
2 and their maps. Rollback stops new evaluation calls, preserves the shared budget
ledger and all artifacts, and can continue reading old parser snapshots.

Next implementation work remains atomic company-claim decomposition, background
exclusion with reasons, table/figure contextual binding and evidence retrieval
across all ESG DATA/APPENDIX. No production default, rules, grade, source quality
or human review revision was changed by these diagnostic annotations.

## Verification commands

Final regression: **1,418 passed**, two existing Starlette/AnyIO deprecation
warnings, 100.74 seconds. Focused parser/ID/budget checks: 22 passed (overlapping
scope, not added to the total). Ruff passed, formatting passed for 222 files,
mypy passed for 141 source files, and four Python package builds passed.
Documentation/contract validation passed 705/705; this is not an application test.
RED reproductions: `.local/prefilter-study/list-red.log` and `short-ids-red.log`.

```sh
uv run --no-sync pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py
uv build --all-packages --out-dir .local/prefilter-study/build
uv run --no-sync python scripts/validate_package.py
```

Use the unchanged `python -m evaluation.prefilter_comparison` CLI documented in
`local-prefilter-verification.md`, supplying each manifest and physical page above;
add `--live` only for paid calls through the shared ledger. Model outputs may vary.
AWS, vision validation, human gold scoring and three-replica evidence tagging were
not run. Full PDF-to-grade accuracy and production readiness are not established.
