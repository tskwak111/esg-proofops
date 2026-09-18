# Document-input atomic extraction — 2026-09-13

Baseline f427fc3. The user approved continuing external-model extraction and
evaluation under the existing cumulative USD10 limit. No production activation.

## Implemented and called

Added `UpstageExtractProbe.extract(document_bytes, schema, request_id=...)` for
one PDF page or one PNG. It reuses the existing authenticated probe/SQLite ledger
and PDF validator, with a pinned Information Extract model and fixed enhanced
mode. No SDK, dependency, cloud configuration or budget-policy change.

Official protocol and model verified at
[Universal extraction](https://console.upstage.ai/docs/capabilities/extract/universal-extraction).
The endpoint accepts a document in the image_url data field and a JSON schema.
Enhanced price verified at [Upstage pricing](https://www.upstage.ai/pricing/api):
USD0.06/page before VAT. This probe conservatively records USD0.066 for the known
one-page request at that rate; it is not an invoiced amount inferred from token
usage. Price expires 2026-09-16. Unknown receipts/errors retain the USD1 reservation.

Input/schema/size/page/image-frame validation precedes reservation. Fixed host/path,
no redirects or retries, bounded responses, sanitized failures, immutable raw receipts,
model/usage validation and duplicate-request protection apply. Only one PDF page or
single-frame PNG is accepted; unsupported schemas and external schema refs are rejected.

`table_layout_context.table_crop` verifies the original PDF SHA, tenant and table
geometry, then renders at3x and crops outward to integer pixels. It records original
page/table bounds, pixel transform, image hash and renderer version. Rotated/nonzero-
origin geometry remains unsupported. Rendering is bounded to16 million page pixels.

`table_atomic_claims.bind_document_rows` reconnects returned quotes only within a
unique literal row heading in the selected native table/parser/page. Missing or
ambiguous quotes remain unknown. Other rows/documents are not fallback matches.
Exact source references and offsets are preserved; duplicate/overlapping proposals
are rejected. Standalone statuses remain unassigned, source approval is not_run,
and all claim candidates remain ineligible for scoring. Coverage is returned quotes
only: an empty model response does not establish absence or exhaustive extraction.

## Six real calls and source review

One whole Naver PDF page, then five cropped table PNGs across Naver, KB and Kia.
Schema was identical across all six calls; each is replica1, not consensus. Raw
requests/responses and crop lineage are in `.local/document-atomic-v1`; public
hashes/counts are in live-comparison.json and the schema is in schema.json.

| Input | Observed result |
| --- | --- |
| Naver physical84 full PDF | Again attached `(진행 중)` to the PPA claim |
| Naver same table, cropped PNG | Separated that status from the PPA; preserved goal period |
| KB physical30 investment table PNG | Recovered the previously omitted annual installation-budget plan |
| KB opportunity table PNG | Returned21 candidate activity/effect quotes across five rows |
| Kia physical45 two numeric-table PNGs | Returned no narrative claims, avoiding isolated label/unit/value outputs |

The Naver image produces seven quotes across both rows, including both the recycling
task and its completion. Earlier text experiments selected fewer cells; counts are
not comparable recall scores. Its five first-row quotes rebind exactly. Two recycling
quotes use straight apostrophes instead of original curved quotes and remain unbound;
no fuzzy normalization silently accepts them. KB produces24 exact parser-source
matches, including two amount/period fragments that still require structured-table
interpretation. Overall29 literal matches and2 unbound quotes, not29 approved facts.

Directly viewed all five cropped images and the Naver original. The Naver status
separation agrees with visible placement. This is a successful diagnostic example,
not proof of reliable general status ownership. The document API's internal visual/
OCR architecture is not established by this experiment. Image transcription is still
a model proposal and cannot replace provenance or rule validation.

**Correction to earlier KB reviews:** the enlarged original opportunity table visibly
contains `개발 개발`. The earlier claim that the parser introduced that duplication
was incorrect. The input image and model transcription both contain it. Preserve the
source wording; this is not a parser repair target. Prior raw artifacts remain intact.

These crops omit material outside the located table, such as titles or footnotes.
For example, Kia's product-scope footnotes sit below the cropped table. They must be
retrieved as context before numeric interpretation; this run only tested narrative
claim selection. The current corpus is development material, not an independent test.

Six calls conservatively cost USD0.396. Shared committed/reserved total moved from
USD7.2868950600 to USD7.6828950600 / USD10;1,271 ledger entries, six pre-existing
unsettled reservations unchanged. No blind retry or external factual evidence.

## Verification

Transport success/budget sharing, malformed input/schema, unknown receipt, failure
redaction/reservation, image-frame limit, source-bound crop and row-limited quote
matching regressions failed before implementation and pass afterward. Focused
transport suite44 passed before the PNG extension. Final suite/build results below.

- Final `uv run pytest -q`:1,784 passed, two existing dependency warnings,197.29s.
- Ruff over apps/packages/tests/evaluation passed; mypy161 files passed.
- Four Python packages built. Documentation/contracts validator753 passed;
  this is not an application or model-accuracy test.

Production routing, whole-report performance, external-note recovery, downstream
status/element tagging, grades, assurance and AWS deployment remain not_run here.
