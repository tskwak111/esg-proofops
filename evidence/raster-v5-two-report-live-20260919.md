# Actual raster v5 two-report evaluation — 2026-09-19

Both fresh pilots ran committed code `8cd099c848bf04dfdb548ac7848ebfe14b67ecc8`,
with native verification, standard Document Parse (four crops, one request), real
Upstage extraction/preliminary/relation/element calls, and the original cumulative
USD20 ledger. Historical runs and receipts were not changed. Both CLI processes
exited 0; both tag stages ended in `needs_review`, not a completed domain verdict.
Exact hashes, coverage, usage and run identities are in the companion JSON.

| Report / physical pages | OCR eligible / sent / corroborated | Claims | Candidate reviews | Calls | Committed or reserved USD |
|---|---:|---:|---:|---:|---:|
| Doosan / 27,97,110 | 16 / 4 / 0 | 12 | 3 | 34 | 1.0602231300 |
| KB / 30 | 5 / 4 / 0 | 6 | 3 | 39 | 0.0738405800 |

Every decision remains null. Blocked/unknown sources were not promoted to present.
Doosan has one new unsettled text request; its reservation remains charged against
the cap and was not automatically retried/refunded. The shared ledger moved from
1752 calls / USD9.2214240400 / 7 unsettled to 1825 calls / USD10.3554877500 /
8 unsettled. The delta is **USD1.1340637100 committed or reserved**, not a claim
that this amount is a settled provider bill. Raster alone cost USD0.044 per report.

## What failed and what was inspected

The first four Doosan eligible IDs selected an assurance organization/date,
signature, short bullet and navigation header. IDs derive from run/manifest
identity, so sorting them gave an arbitrary bounded sample. External text differed
by organization-symbol spelling, extra signature recognition, bullet whitespace
and header ordering. The preserved normalizer intentionally did not certify them.

KB's four crops included three bullet-bearing fragments and the numeric text
`1.6억 원`. The provider omitted bullets and substantially misread that numeric
crop. Direct visual review of the rendered source confirmed the bullet in the
first KB crop and the decimal/number in its numeric crop. Doosan page 27 and its
third request crop were also visually inspected. No semantic gold labels or
manual approval were fabricated from this review. The numerical misread stayed
unresolved. Raw/crop images remain private under
`.local/raster-visual-review-20260919`; the JSON lists their hashes. Hash inventory
also includes renders that were generated but not individually visually reviewed.

## Read latency

With both Upstage text and raster invocation methods forbidden, two consecutive
Doosan `load_run_evidence` reads produced the identical graph hash and 22 verified
blocks, taking **49.632s** and **51.253s**. These are shared-host observations while
the KB pilot was active, not controlled benchmark medians. This demonstrates a
material repeat-read bottleneck: v5 currently redoes expensive native/raster
verification on each read. A bounded cache must retain all source, graph, scoped
artifact, policy and reader pins and must never cache failed validation.

## Applied scheduling fix, still requiring live re-evaluation

The worker now shares extraction's existing prose/page ranking instead of sorting
run-derived IDs. Extraction's ranking semantics are unchanged; only raster
selection changes. A regression changes source IDs and input iteration order while
requiring the same prose/page selection. The 23 focused extraction/raster/pipeline
tests passed. Stored-report replay of selection (no provider call) now puts three
Doosan prose fragments ahead of short signatures; a navigation header can still
occupy the fourth slot. KB's mostly short/diagram fragments remain difficult.
This is a routing improvement, not demonstrated OCR accuracy improvement.
Details are in `raster-prose-priority-replay-20260919.json`.

A Luna read-only audit ran 35 focused tests. Its proposed multi-request ordering
bug was rejected after source inspection: `record_id` is the request UUID and SQL
already orders by it, not insertion time. Its proposed out-of-scope coverage
case is rejected earlier by `OpenDataLoaderParser.load_verified` for unselected
blocks. No acceptance boundary was weakened in response to those findings.

Remaining work: cache fully validated v5 replay; freshly evaluate the improved
routing and small-crop recognition; expand real-report coverage and independent
semantic gold. Zero recovered crops in these two bounded samples does not prove
all external OCR is ineffective, and successful integration is not service-grade
accuracy. Exact-head CI for 8cd099c passed (run 35406104504).

Scheduling-fix verification: full local unit/contract/acceptance/integration/
security/staging-gate suite passed **2728 tests, 7 skipped, 2 existing warnings in
210.45s**. Ruff/format (357 files), mypy (191 sources), source/wheel build and866
package documentation/contract checks passed. The helper regression first failed
on the missing shared ranking function, then passed after implementation. No paid
call was made after changing the ranking; live results above remain explicitly
attributed to 8cd099c.
