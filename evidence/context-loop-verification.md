# Multi-report extraction loop — 2026-09-13 KST

**Not service-ready.** This wave fixes source fidelity, model identity and cost-stop
behavior and adds an opt-in Pro4 local route. It does not establish independent
accuracy, verified evidence attribution or automatic grades. Detailed receipts,
hashes and all unsuccessful variants are indexed in `context-loop-results.json`.

## Changes accepted locally

- All Upstage transport failures with unresolved accounting stop sibling calls in
  the real worker, atomic pilot, prefilter modes and cross-report probe. Paid
  reservations remain intact. Valid-usage malformed model output remains unknown.
- Exact quote validation rejects cutting Korean/Latin words, numbers, signs,
  decimals and percentages. An observed `지분투자` → `투자` truncation is now rejected;
  it is never silently repaired. Scalar dimension extraction retains its separate
  literal-span checks (`2030년` in `2030년까지` is a value, not an entire claim).
- TOC links supplement scattered E chapters even if one E chapter already exists.
  Bounded data/appendix containers remain evidence-only. A regression dropping Kia
  physical36–45 (자원순환) was reproduced, fixed and remapped. V8 maps retain unknown
  and conflict pages; branded `Green Innovation` still needs scope review.
- Pro4 is explicit, with separate model hash and price receipt, the same USD10
  ledger and no automatic fallback. Run creation and each call check binding ID
  against the frozen model hash. Pro3 remains the default. New rule hashes require
  new runs; old published results stay immutable.

## Actual model comparisons

Five companies: Doosan Bobcat, Kia, KB Financial, Kakao and NAVER. First-stage
comparisons reuse20 frozen paragraphs per company; mostly one E page per company,
so these are development samples rather than a representative benchmark.

| Variant | Actual calls | Proposed spans / selections | Unknown paragraphs |
|---|---:|---:|---:|
| Pro3 existing baseline | 100 | 74 | 2 |
| Pro3 target + nearby context v1 | 100 | 130 | 16 |
| Pro3 context v2 | 100 | 88 | 28 |
| Pro3 sentence-ID selection | 27 | 102 sentences | packet validation all passed |
| Pro3 atomic second stage | 60 | 81 | all60 requests passed; Doosan not_run |
| Pro3 Korean prompt | 100 | 108 | 2 |
| Pro4 medium reasoning canary | 6 | 0 | 2 |
| Pro4 default reasoning-off | 100 | 55 | 0 |
| Pro4 context | 100 | 59 | 3 |
| Pro4 compact-claim prompt/context | 100 | 77 | 12 |

More extracted spans do not mean better extraction. Context variants copied
neighbor-only statements, and sentence selection/atomic extraction admitted labels.
None of these alternative prompts is promoted. Pro4 medium reasoning timed out
once and exhausted4096 output tokens without a final answer once; both USD1
reservations remain unresolved. Official chat documentation says reasoning is off
by default; the next explicitly configured experiment omitted reasoning and used
the same1024 output cap as baseline. Sources: [Upstage chat guide](https://console.upstage.ai/docs/capabilities/generate/chat),
[pricing](https://www.upstage.ai/pricing/api). Promotional discounts are ignored.

NAVER was newly parsed from its original PDF. Orion failed `PDF_INVALID` (broken
object resolution), and POSCO Holdings was rejected for an automatic Print action.
Those original failures are included; no input was silently repaired or counted as
successful. New local parses of15 further E pages across the five companies all
succeeded (53 selected paragraphs, >=60characters, up to4 per page).

On these53 new paragraphs, Pro3 proposed104 spans with2 unknown responses; Pro4
proposed92 with1 unknown. An agent instructed not to view model outputs labeled
29 paragraphs assertion,17 nonassertion and7 ambiguous. Pro3 selected27/29 assertion
paragraphs (2 unknown), and3/17 nonassertion paragraphs; Pro4 selected28/29
(1 unknown) and0/17. These are **agent diagnostic agreements, not precision/recall**.
One nonassertion label is a numeric table row and itself warrants review. In a
subsequent real service call Pro4 selected that row, demonstrating instability.

The initial80-label agent review was found to have seen baseline outputs and is
explicitly recorded as non-blind. The later53 labels have matching IDs and hashes,
but are still not human gold. One late new-page plan read an updated on-disk
validator hash while Python retained its earlier import; the indexed correction
preserves that original plan. A separate zero-cost replay of206 recorded responses
with the final validator rejects the one mid-word truncation without rewriting
any previous result.

## Real local service execution

Two original PDFs, new isolated states, explicit Pro4 profile/source consent:

| Company | Physical page | Report period checked in original | Calls | Claims | API list/detail |
|---|---:|---|---:|---:|---|
| Kia | 45 | 2024-01-01–2024-12-31, report edition2025 | 8 | 7 | 200/200 |
| NAVER | 90 | financial/business FY2025; some management events extend into2026 | 8 | 3 | 200/200 |

Both parse and extract stages committed; tag stage is **blocked**, claims remain
`untagged`, source verification `candidate`, decision null. No synthetic tags,
source approvals or grades were created. Known API cost estimates totalUSD0.003500970.
Artifacts: `.local/context-loop/{kia,naver}/service-pro4/`.

Usage across the existing ledger:1145 calls,5 unresolved reservations, committed
or reservedUSD6.0124487450 ofUSD10. This wave added835 calls, including2 unresolved
reservations. Settled conservative estimates totalUSD1.0124487450; USD5 is reserved
for unknown prior/current calls, **not confirmed spend**. No ledger resets/refunds.

## Verification

- `uv run pytest -q`: **1609 passed**,2 dependency deprecation warnings,105.23s.
  Includes unit, integration, contract, backend E2E and security tests.
- `uv run ruff check apps packages tests evaluation`: passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
 151 source files passed; three untyped-body notes.
- `uv build --all-packages --out-dir .local/context-loop/dist`: four packages built.
- `npm run build`: TypeScript/Vite passed.
- `uv run python scripts/verify_architecture.py`: passed.
- Locked export plus `pip-audit --strict --no-deps --disable-pip`: no known vulnerabilities.
- `pnpm audit --audit-level low`: no known vulnerabilities; Node deprecation warning.
- `uv run python scripts/validate_package.py`: 739/739 passed; document/contract checks only.
- New browser UI E2E: not_run in this wave; actual API/worker calls above did run.
  Prior browser evidence remains in `local-upstage-service-pilot.md`.
- AWS, production deploy, legal/domain approval, human gold: not_run/unresolved.

Orca run `run_436abc222c05` used OpenCode Muse Spark1.3/1.2 Free workers. Coordinator
rejected/reworked overlong duplicate code, fake run-path tests, non-blind gold claims,
incorrect empty-vs-unknown comparisons and scope regression. Settled terminals were
reused or released and closed. No Codex workers, pushes or cloud mutations.

Next service-quality work: recover numeric table structure and keep table evidence
separate from narrative assertions, then integrate source-bound real tagging under
existing unknown/conflict gates. Independent source/element/assurance annotations
and frozen domain-gap decisions remain required before automatic release metrics.
