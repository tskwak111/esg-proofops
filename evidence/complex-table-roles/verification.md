# Complex table role path — 2026-09-13

Correction from the later enlarged-image review: KB's original table itself shows
`개발 개발`; the earlier parser-duplication diagnosis below was incorrect. See
[document-input verification](../document-atomic/verification.md). Historical model
receipts and the rest of this experiment remain unchanged.

Baseline 3028f4f. The numeric helper's zero candidates on KB/Naver did not mean no
source content: these are narrative/amount-with-unit tables requiring semantic
extraction. This wave repairs the existing table_role_pilot path, not a new parser.

## Changes and independent review

Orca run run_f4e52cd85f8f; review Task task_c9b1ae8fb931 / Dispatch
ctx_017855e67640 succeeded in read-only mode. The worker identified first-row-only
context losing KB subheaders and missing guards for expected financial effects
and mixed progress. It ran in an explicitly configured OpenCode Muse Spark 1.3
Free terminal. Accepted completion, external-terminal release, exact coordinator-
created terminal close and delivery acknowledgment completed; no reclaimable worker.
Kiro/Antigravity unchanged availability constraints were not retried.

Coordinator changes:

- table_row_contexts retains additional leading rows indicated by first-row merged
  spans. This is a structural header candidate, not proof of a thead or parent edge.
  It is limited to earlier rows in the same native table/parser/page.
- prepare_rows supplies those source IDs and spans with the existing first row.
  Non-unknown tags must cite every covering candidate header, including parent and
  leaf; partial overlap or cherry-picking a favorable header is rejected.
- Expected-effect headers now include literal 예상 재무적 영향 and 향후 계획.
  Their cells cannot escape into activity/category/reported-result roles; ambiguous
  cells can remain unknown. Mixed 달성 + 진행 중 cells must remain unknown for any
  role, pending finer claim/status separation. Result headers cannot support an
  expected-effect fallback. These are proposal guards, not domain grades.
- Prompt and tagging contract version10 changed. Old requests/results are immutable;
  their validation results are version-specific. Current revalidation is recorded
  separately, never silently rewriting an old passed result.

No domain grade, source approval, inferred number/unit/year, DB or API change,
new dependency, external numeric source, production activation or cloud operation.
Rollback requires the previous helper/prompt/contract for its archived results.

## Real source and model evaluation

Six settled Upstage calls: Pro3 on two prompt versions and Pro4 on the latter,
using identical per-company packets (KB9 target cells, Naver6). All use the original
USD10 ledger. Request IDs, packet/prompt/provider response hashes and costs are in
live-comparison.json; raw source-bound packets/responses remain under
`.local/complex-table-role-{v9,v10,pro4}/{kb,naver}`. Original PDF hashes were checked
against restored candidate snapshots before requests. Stored graph/source references,
parser IDs, row/column spans and original quotes are preserved.

KB's packet gained five subheader cells across its two selected rows, including
단기/중기/장기 and 2025/향후 계획. Pro3-v9 correctly used these in its expected-effect
proposals, though contract acceptance is not semantic accuracy or source approval.
The later Pro3 and Pro4 responses relabelled expected effects as activity descriptions;
the final validator rejects them. Naver's mixed progress cell was incorrectly tagged
as expected_effect or reported_result across all three calls, now all rejected.
Current strict revalidation accepts1 and rejects5 packets. This is a diagnostic
sample, not an accuracy score, independent replicas, or grounds to select Pro4.

Original PDF images were rendered and directly viewed: KB physical30 and Naver84.
Naver shows 달성/(진행 중) in a KPI status position beside the outcome bullets.
Both standard and enhanced parser receipts instead attach 진행 중 after the first
6MW PPA bullet. Thus blindly interpreting the flattened cell can misassign the
status even with a larger model. KB also has a duplicated 개발 in parser text.
The originals and parser receipts were not overwritten to hide these errors.
Image hashes are retained in live-comparison.json.

Six calls cost USD0.0032092500 (ledger's VAT allowance included). The committed/
reserved total moved from USD7.2721452150 to USD7.2753544650 of USD10. The six
pre-existing unsettled reservations remain untouched. No further blind retries.

## Remaining bottlenecks

The role model is not reliable enough on these inputs. A geometry/vision-aware
status-versus-bullet split with original spans is needed before treating the
Naver row as atomic claims. Multirow header inference still lacks explicit parser
header semantics, and expected effects/amounts require broader paragraph context.
Current guards prevent wrong promotion; they do not demonstrate complete recovery.
SF6-share and the KEPCO121 discrepancy from earlier waves remain unresolved.

## Verification

- First two regressions failed (missing subheaders and unsafe role acceptance), then
  passed. Live outputs exposed alternate-role bypasses; five additional cases and
  the expected-effect-as-activity case failed first and pass after the guard fixes.
- Focused table-role/section integration suite:24 passed.
- Ruff over apps/packages/tests/evaluation passed; changed files formatted.
- Mypy application/evaluation/load/staging paths:158 files passed, existing notes.
- Actual API executions and source-image review described above; no production
  rules, assurance verdicts, consensus or AWS test performed.
- Final `uv run pytest -q`:1,759 passed, two existing dependency warnings,135.15s.
  This covers repository unit/contract/integration/acceptance/E2E/security tests,
  not general report accuracy.
- Four Python packages built after final guards. Documentation/contract validator:
  749 passed; explicitly separate from application/model verification.
