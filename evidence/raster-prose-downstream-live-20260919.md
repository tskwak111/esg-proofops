# Prose recovery downstream trial — 2026-09-19

The parse-only run documented in `raster-cache-prose-live-20260919` was resumed
for actual authorized extraction and tagging at commit 7ab0d3b. No parsing or
OCR request was repeated. Extraction committed in 55.315s; tagging finished
`needs_review` in 254.808s.

- 12 claims extracted; seven have verified source text.
- Six immutable candidate reviews published; five claims blocked on source
  validation and one on unresolved preliminary tags. All decisions remain null.
- The recovered CHRO paragraph yielded three claims. Two reached candidate
  review; one remains blocked because reporting-period replicas disagree.
- The previous run had three reviews; this run has six. Only two additional
  reviews are directly traced to the recovered paragraph. These are fresh
  stochastic model outputs, not a controlled accuracy experiment.
- Reopening through the pilot without `--invoke` returned HTTP200 for the claim
  list, first claim detail and cost. Twelve claims returned; cost status remains
  `partial`, correctly avoiding a fabricated complete dollar total.

The blocked claim reports management activity once per quarter. All three
preliminary responses passed source/schema validation, but reporting-period
quotes were `null`, `분기 1회`, `분기 1회`. The existing consensus gate kept the
claim unresolved. This exposes a prompt-definition gap: reporting frequency
must be distinguished from the period to which the claim applies. Do not
reinterpret frequency into an invented calendar period or force agreement.

Downstream work added 61 provider calls and USD1.0497347950 committed/reserved.
Shared ledger is 1,887 calls, USD11.4492225450 / USD20, nine unsettled (one new
unsettled request). No uncertain call was retried or refunded. Earlier parse
trial cost USD0.044 separately; its evidence remains historical.

CI35408172756 passed for 7ab0d3b, including frontend, Python, architecture,
supply-chain, package contracts and containers/IaC. This follow-up changes only
evaluation evidence/documentation; the prior 2,732-test result is not a new
accuracy claim. Next: reporting-frequency adversarial cases, safe prompt-version
handling, broader reports and the measured cold-replay bottleneck. Independent
domain gold and production approval are still absent.
