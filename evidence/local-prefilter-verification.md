# Local sentence prefilter comparison — 2026-09-09

User authorization: local preprocessing plus context-aware LLM candidate selection;
Upstage/cheap APIs rather than Bedrock; cumulative USD 10 testing limit remains.
This is a bounded extension of TASK-008's local evaluation path. No API/DB schema,
domain rule, production model composition or original PDF was changed.

## Delivered behavior

- Reuse verified OpenDataLoader artifact loading, original SourceRef creation,
  tenant/version checks and the existing durable Upstage budget ledger.
- Local punctuation-based sentence spans preserve code-point offsets; decimals
  are not split at the decimal point. Whole parent-block sentences, adjacent
  native-order blocks and the preceding same-page heading provide context.
  Parser order and source quality are not automatically approved reading order.
- Broad lexical/numeric signals select target blocks. Every deferred block has
  an explicit reason and unknown/conflict/unreadable state. Tables, cells, rows,
  figures and unsupported block kinds remain separately unresolved in this text
  experiment. Missing requested pages and oversize blocks are recorded.
- At most eight target blocks and 11,000 serialized packet bytes per request;
  this is batching, not a quota on how many claims may exist. No silent truncation.
- The model returns only selected sentence IDs. Python resolves original quotes
  and SourceRefs, rejecting invented/repeated/context IDs or altered source data.
  Sentence candidates retain `atomicity=not_reviewed`, source quality and candidate
  citation state. No grade or atomic-claim completion is inferred.
- Default CLI behavior is offline planning; `--live` opts into the already
  authorized shared budget. Separate UUID directories retain plans, requests,
  response bodies, source validation, prompt/policy/model hashes and differences.
  Files are created exclusively; previous trial artifacts are not rewritten.
- The original full extraction and one-paragraph atomic quote probe remain
  available. No BERT, embeddings, local generative model or dependency was added.

## Final real comparison

Source: user-provided LG Chem 2025 Korean report, **physical page 24 only**.
Original full-document parser batch manifest:
`.local/corpus-geometry/full-document/artifacts/9705bf16-e1e7-4d55-af9d-722b9aa1ba94/86af32c1-b91c-4dcf-8d98-05ce1aae447c/bbf44c73-bd9e-4b1d-bea4-8ee05a59c488/manifest.json`.

Final artifact directory:
`.local/prefilter/f1fdc28d-97fa-434e-b682-0a4ca72bd72e/`.
Model: observed `solar-pro3-260323`; JSON object request mode accepted by the live
endpoint. Format support does not establish semantic correctness.

| Metric | All eligible text blocks | Locally filtered blocks |
|---|---:|---:|
| Target blocks | 51 | 31 |
| Deferred blocks, including non-text structures | 48 | 68 |
| Actual requests | 7 | 4 |
| Failed ID/source validations | 0 | 0 |
| Input tokens | 10,384 | 6,970 |
| Output tokens | 943 | 759 |
| Settled cost estimate including VAT allowance, USD | 0.0023357400 | 0.0016509900 |
| Sum of request/validation durations, seconds | 9.226 | 5.816 |
| Sentence candidates | 25 | 21 |

Input decreased **32.88%**, estimated cost **29.32%** in this paired trial.
Timing is a single sequential trial, not a latency benchmark or service guarantee.
These cost estimates use the existing published-price snapshot and conservative
allowance; they are not invoice reconciliation or predictions for 50 reports.

There were 21 exact matching source spans. Of the four baseline-only candidates,
three came from sources the local filter deferred (electrification, biomass/hydrogen
fuel use, and power optimization phrases); one was a selection disagreement on a
source sent in both modes. Whether these are standalone company assertions still
requires contextual review. The all-text model is **not a gold labeler**. Therefore
recall is null, not 84% or 100%, and no accuracy claim is made. This page is a
development case and must not subsequently be represented as an untouched holdout.

The lexical filter is opt-in and **not promoted to the production/default path**.
Whole E-section testing and a labeled sample are needed before accepting its
omission behavior. E evidence search must still include all ESG DATA and APPENDIX;
this feature does not restrict their evidence scope.

## Failure evidence and cost accounting

Earlier artifacts remain intact:

- `3f68d281-5252-4eaa-b115-b5283f11e077`: long free-quote batches produced invalid
  JSON in one response per mode. Both were rejected, with receipts retained.
- `5f26a3a4-cce7-42ba-b28e-32df10f54089`: JSON object mode removed JSON syntax
  errors but long outputs omitted targets and mixed source IDs; still partial.
- `172036b3-4d13-4cbd-b547-8be2c2c60486`: eight-block batching alone did not solve
  copied-quote errors or context leakage (5/11 validations failed).
- Final sentence-ID selection avoids copying text or generating offsets. It
  intentionally leaves atomic decomposition for a subsequent stage; the failed
  atomic quote trials are not recast as successful atomic extraction.

Final cumulative ledger: **35 calls**, **2 unsettled calls**, committed/reserved
USD **2.0189555300**. This comprises USD **0.0189555300** in settled usage estimates
and the **USD 2** unchanged holds for two early unreconciled probes from the
previous task. The holds are not known actual spend. This task added 30 calls
and USD **0.0183968400** settled estimates, including unsuccessful validation
attempts. No automatic paid retries, budget reset or ledger deletion was used.
The local guard cannot control other applications using the same API key.

## Reproduction and validation

Run from repository root; module invocation is required (direct script invocation
cannot resolve the repository's `evaluation` namespace and makes no model call):

```sh
uv run --no-sync python -m evaluation.prefilter_comparison \
  --pdf '기업보고서/배터리 에너지/LGChem_Sustainability_Report_2025_KOR.pdf' \
  --manifest .local/corpus-geometry/full-document/artifacts/9705bf16-e1e7-4d55-af9d-722b9aa1ba94/86af32c1-b91c-4dcf-8d98-05ce1aae447c/bbf44c73-bd9e-4b1d-bea4-8ee05a59c488/manifest.json \
  --pages 24
```

Add `--live` for paid calls using `.env.upstage.local` and the existing
`.local/upstage/budget.sqlite3`. Preserve that ledger across revisions/rollback.
The pinned price expiry still requires rechecking on/after 2026-09-16 UTC.

RED evidence: `.local/prefilter/{red,comparison-red,json-mode-red,batch-red,sentence-ids-red}.log`.
Final broad regression: **1,415 passed**, two existing Starlette/AnyIO deprecation
warnings, 97.80 seconds (`.local/prefilter/verified-tests.log`). Ruff check passed;
format check passed for **221 files**; mypy passed for **141 source files**.
Four Python packages built successfully. Documentation/contract validator:
**705/705 passed**, which is separate from application tests.

```sh
uv run --no-sync pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py
uv build --all-packages --out-dir .local/prefilter/build
uv run --no-sync python scripts/validate_package.py
```

No AWS, vision,
full E/DATA/APPENDIX semantic tagging, human gold evaluation or three-replica
tagging was run. Rollback stops this optional CLI and retains artifacts/ledger;
existing application contracts and stored revisions require no migration.
