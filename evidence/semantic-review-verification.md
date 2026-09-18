# Semantic diagnostic — 2026-09-13 KST

This is a development diagnostic, not a release benchmark or human gold.
Baseline code:93fe505. Orca run:run_2913ca7db124.

## Method and actual calls

Frozen `.local/semantic-review/packet.json`:30 source paragraphs, six each from
Doosan, Kia, KB, Kakao and NAVER. Four per company came from previously selected
unseen-page artifacts and two from short baseline paragraphs. The selector used
`page_num`/`original_page` instead of the input `page` key: the four-case ordering
therefore actually followed text hashes, not physical pages. This is NOT a
page-stratified sample or a held-out company benchmark. Repeated text at distinct
source IDs remains separate cases. Original source/version/manifest/page/bbox
bindings were checked against graphs and frozen in `live/plan.json` before calls.

Kiro reviewed source-only inputs without model outputs. Its definitions concern
company assertions in general, not strict environmental relevance or evidence
sufficiency. All30 IDs and every returned quote were independently checked for
exact unique source occurrence. Labels:11 assertion,3 mixed,16 nonassertion.
These labels remain agent proposals; they do not authorize grades or evidence.

Thirty actual solar-pro4 calls using the shared ledger all settled. The baseline
extractor processed29 paragraphs and left one unknown. It selected at least one
claim in13/14 assertion-containing paragraphs and none in16/16 nonassertions.
These counts measure paragraph-selection agreement with one agent, not precision,
complete claim recall, environmental classification accuracy or audit accuracy.
Original packets and provider receipts remain immutable under `live/receipts`.

## Reproduced defect and fix

Kia physical page38, source0a30acff-f395-5066-9554-7aa8f84783e7, casep09:
the model rewrote its first quote but exactly copied the second. Previously the
invalid sibling discarded the valid one too. The new extraction rule profile
validates each quote independently, records rejected quote indices, and preserves
exact valid siblings. Uncovered source ranges retain the existing unknown state.
All-invalid responses, malformed schemas and overlapping accepted spans still
fail closed. No rewritten quote is repaired or admitted; no grade rules change.
Old stored extraction profiles and recorded-response replay semantics are intact.

A failing-first integration regression reproduced the lost sibling, then passed
while checking that the remaining text stays unknown and rejection index0 is
recorded. Offline replay of all30 original provider responses changed onlyp09,
retaining one valid claim. All30 then had structurally processed responses; this
is not a claim that every assertion was extracted. Replay uses fresh receipts and
profile hashes under `.local/semantic-review/replay`; it made no API calls and
added no ledger entries. The archived provider metadata describes the original
call, not a new model execution.

## Budget

Authority remains `.local/upstage/budget.sqlite3`, cumulative limitUSD10.
1201 calls; committed/reservedUSD6.1699600550, including five unresolvedUSD1
reservations. Settled recorded costUSD1.1699600550. This30-call wave cost
USD0.0072573600. Unresolved reservations were neither retried nor refunded.

## Verification

- Regression red:1 failed,31 passed; green:32 passed.
- `uv run pytest -q`:1640 passed, two dependency warnings,110.05s; unit,
  integration, contract, backend E2E and security tests included.
- `uv run ruff check apps packages tests evaluation`:passed after fixing new test
  import formatting; focused32 tests rerun after formatting.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
 153 source files passed; three existing untyped-body notes.
- `uv build --all-packages --out-dir .local/semantic-review/dist`:four packages built.
- `uv run python scripts/verify_architecture.py`:passed.
- No dependency or web change. New browser E2E, real element-tagging service,
  consensus integration, human gold and deployment:not_run.

## Table review and coordinator adjudication

Five cached tables,64 target cells: KB5:28, KB9:14, Kia10:10, Kia13:6,
NAVER8:6. Counts were computed directly from result tags; they are not accuracy.
All five cited finding IDs/quotes match the existing candidate result records.
The review was nonblind and did not inspect original PDF coordinates.

- KB9 cellc7:the amount `1.6억 원` under an investment-amount header was tagged
  category. This is a concrete routing mismatch; sibling amount cells have the
  same issue. Existing vocabulary lacks a numeric-value role, so automatic
  promotion to an achieved/verified result would not be justified.
- KB9 year/plan subheaders and KB5 time-horizon subheaders remain unknown.
  That is conservative under the current vocabulary, not itself an incorrect
  grade. Multi-level header binding still needs improvement.
- KB5 mixes projected costs and benefits under a financial-impact header.
  The current expected_effect role is defined as anticipated benefit; treating
  every negative projected cost as a known expected_effect answer would exceed
  that definition. This is a taxonomy/context limitation requiring evaluation.
- Kia values/units stay unknown; the diagnostic vocabulary does not include
  numeric-value/unit roles. The table-role pilot cannot substitute for the
  numeric observation and verified source-binding paths.

No table-role output was promoted to verified evidence or fed into grading.
Service readiness remains unproven; actual Upstage element-tagging composition,
verified table locations/binding and independent semantic benchmarks remain open.

`uv run python scripts/validate_package.py`:742/742 passed after adding the
machine-readable diagnostic summary; documentation/contracts only.

## Orchestration outcomes

- `task_1b0d74753a00`, Kiro:source-only30-paragraph diagnostic completed and
  independently quote-validated. Default TUI exited; the retry used legacy UI,
  model selection shown as `auto` on KIROPRO. No underlying model is inferred.
- `task_125c4abc51c8`, Kiro:separate five-table nonblind review, corrected after
  coordinator identified manual count errors and rubric overreach. Final64-cell
  counts and five cited source IDs/quotes were independently verified. This
  correction is further reason not to treat agent review as human gold.
- `task_3b98c1fde32c`, Antigravity:not_run. Three attempts failed Orca
  agent_readiness classification of the CLI trust screen, including after folder
  trust was accepted. The failure circuit was respected; no replacement retry or
  claim of semantic work. The terminal was released/closed.

No Muse or Codex worker was substituted in this wave. Kiro owns review artifacts
only; coordinator owns the code change, tests and adjudication.

Both Kiro tasks settled successfully; dispatches were released and externally
created terminals explicitly closed. The initial exited Kiro TUI terminal was
also stopped/closed. Final reclaimable-worker query returned none.
