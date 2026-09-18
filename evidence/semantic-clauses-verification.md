# Child clauses with and without parent context — 2026-09-10

Reused the existing parent-preserving clause helper on the pinned LG Chem p25
renewable procurement / carbon reduction sentence. Both child quotes remain
exact non-overlapping source slices, with the original parent SourceRef retained.
They are diagnostic candidates, not accepted atomic Claim revisions.

Ran four Upstage calls: each of the two children alone and with a separate
context-only parent field. Kept the previous few-shot system prompt, model,
JSON mode, temperature 0 and 2,048 output-token limit. All extraction quotes
still had to occur inside the own child; no parent quote borrowing was allowed.
Each variant was sampled once, so this is not a causal or corpus-accuracy result.

## Observed results

- First child, no parent: model metric `약 93GWh의 재생에너지`; the existing local
  splitter yielded source-bound `약 93` / `GWh` / `재생에너지` candidates.
- First child, parent included: model metric `93GWh`; the existing quantity-only
  metric guard rejected the entire response. No partial salvage.
- Second child, both variants: model metric `약 4만 톤의 탄소 감축 효과`; the
  existing splitter yielded `약 4만` / `톤` / `탄소 감축 효과` candidates. Entity
  and boundary remained unknown, including when the parent mentioned domestic
  business sites. No implicit domestic boundary was inherited.

The full compound in the previous single-claim experiment returned only the
procurement metric. This two-child probe makes both measurement descriptions
available for local review. It does not establish correct entity roles, atomicity,
causal attribution or a complete semantic fix. The first child's generic domestic
business-site phrase still needs entity-versus-boundary review. No assertion that
parent context generally helps or harms the model; no default prompt was changed.

## Offline continuation and provenance

Revalidated all archived packet/wire/system hashes and own-source selections
against the PDF-validated graph, replayed the same validators, checked every
component quote and preserved unknown entity/boundary states. The rejected
quantity-only metric was rejected again with no extra call. The two context-off
metric phrases were also sent through the existing bounded SectionSearch over
E + all ESG DATA + all APPENDIX, retaining source IDs, raw text hashes and quality.
Search hits are related-source routes only, not support for 93GWh or 4만 톤.

`semantic-clauses-review.json` contains source references, original model responses,
request/model/prompt/rule linkage, validator outcomes and search routes. Its linked
local full artifact retains original packets and the unchanged parent context;
request/response files live under `.local/semantic-clauses/`. Previous claims,
source quality, tags and decision revisions were not rewritten. All bindings
remain undetermined; no grade or evidence approval was generated.

## Verification and limitations

- `uv run --no-sync pytest -q tests/integration/test_claim_dimensions.py`
  — 25 passed, covering parent/source preservation, numeric and period guards.
- `PYTHONPATH=. uv run --no-sync python .local/semantic-clauses/replay.py`
  — archived response/source/hash checks, paired results and bounded search checks.
- No application code, API/DB, dependency or production default changed. Full suite,
  lint/type/build were not repeated for this artifact-only experiment; the prior
  code checkpoint remains 1,458 passing tests.
- Table/vision quality approval, human-adjudicated semantic gold evaluation,
  accepted company/period/metric evidence binding and deployed E2E: not_run.

Four calls added $0.0005761800. Cumulative committed/reserved $2.0411683250 / $10
across 108 calls, including two prior unsettled calls. No retry, Bedrock/AWS action
or credential output.

Observed search limit: `재생에너지` includes p99 ESG DATA and p113/p115 appendix
routes. `탄소 감축 효과` returns only E pages (16/17/23/24/26/49) in the bounded
result. No data/appendix hit for that query means retrieval remains incomplete,
not that supporting information is absent. A future retrieval comparison should
address differences in claim-versus-table terminology without equating metrics
or approving numeric/organizational attribution through lexical similarity.

`uv run --no-sync python scripts/validate_package.py` — 731/731 documentation
and contract checks passed, separately from the focused application tests.
