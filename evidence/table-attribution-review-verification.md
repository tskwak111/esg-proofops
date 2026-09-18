# Table candidates, attribution and review — 2026-09-13 KST

Baseline d70db36; Orca run_1a1fc202da58. Development diagnostics, not service
readiness or human accuracy. No new dependency, API shape or DB migration.

## Changes and compatibility

- Production `accept_binding` now requires the complete merged value span to be
  covered by its attributed header. A row header covering only the first of two
  product rows and a year header covering only the first of two year columns
  previously passed. Both failing-first cases now reject; full coverage accepts.
  All callers share the guard. Existing tenant/version/verified-source, period,
  scope and graph-edge checks remain. This is attribution, not numeric equality.
  Persisted revisions/reports remain immutable. New evaluation can yield stricter
  results; retain the deployed code revision with replay inputs. Historical replay
  must use its original build. Rollback uses the previous build without rewriting
  receipts; it must not treat old accepted bindings as newly verified evidence.
- `evaluation/table_numeric_candidates.py` reuses the existing HTML parser and
  numeric normalizer. Explicit metric/unit/year headers, complete merged spans,
  target/actual qualifiers, hierarchical row headers and company section context
  are retained. Values such as `1 2`, `12,34`, embedded prose years and ranges do
  not silently become numeric/year values. Percent literals are supported only
  with an explicit matching percent unit header; raw text is preserved.
  Auto-discovery is deliberately limited to explicit first-row headers. Footnotes,
  inferred units, prose financial tables and unclear layouts remain deferred.
  All outputs are unverified candidates, never grading inputs or source approval.
  Default production ingestion is unchanged; this helper is an evaluation path.
- `evaluation/review_benchmark.py` freezes bounded source packets and scores
  separately supplied annotations/predictions by company/task. Missing predictions
  count against reviewed cases; null annotations remain visibly unreviewed.
  Agent review never populates human_accuracy. Reviewer kind/name are declared
  metadata, not authenticated identity or an approval mechanism. Source-only
  blinding requires a controlled workflow; arbitrary source dictionaries alone
  cannot guarantee that predictions were withheld.
  Offline HTML shows reconstructed tables, target cells, physical pages, source
  hashes, company filters and annotation export. It requests original PDF cross-check;
  parsed-table agreement cannot establish PDF transcription accuracy.

## Actual parser runs and frozen diagnostics

Three authorized Upstage document-parse-260128 standard calls, each one page:
Samsung Life PDF121 (6.906s), KEPCO PDF205 (6.953s), Hyundai Steel PDF113 (5.985s).
All succeeded and settled, total USD0.033. Original bytes and response hashes were
checked. Private receipts/lineage: `.local/showcase-eval/{company}/`.
Shared ledger `.local/upstage/budget.sqlite3`:1240 calls,6 unsettled,
USD7.2721452150 committed/reserved of USD10. Old reservations remain untouched.
No retry, refund, Bedrock, source verification, cloud change or deployment.

Together with prior Kia/KB/NAVER archives:14 provider table elements across six
companies, including navigation/prose layouts. Initial409 candidate records included
292 numeric candidates; final percent handling yields296 numeric candidates.
These counts are output volume, not accuracy or total numeric recall.

Source-based hash-order sampling (up to four number-starting cells per table)
froze38 cases across five companies before separate review. NAVER contributed no
sampled numeric cell. Samples include headers/footnotes; these are development
reports, not representative unseen holdouts. Packet SHA256:
`d780858af82a5821edb6a7bf1a0246dfa7f506e7c2ab4827031e6b855cd64923`.

Muse1.3 source-only review:28 labeled,10 null. Initial exact agreement25/28;
percent fix replay26/28, one missing footnoted-number prediction, one reviewer
changed a literal control character into spacing. The latter is a reviewer defect,
not a reason to normalize the source silently. We preserve both outputs and count
it as a mismatch. Two predictions also fall in unreviewed cases, so 26/28 must NOT
be sold as precision across all outputs. Human accuracy remains null.
Private `predictions.json`/`tables.json` retain baseline; `*-v2.json` records the
improvement; `agent-score-v2.json` records the diagnostic. No human labels invented.

## Agent accounting and review disposition

- task_35b10f9bd585: Muse1.3 table helper, completed; coordinator reproduced and
  fixed malformed numeric/period handling and added actual multilevel context.
- task_00838af45a68: Muse1.2 attribution review, completed. Accepted merged-span
  finding. Proposed numeric-equality layer overlaps existing numeric services;
  broad period/global-scope allegations were not reproduced. No speculative
  interfaces added. End-to-end numeric service integration remains an open gate.
- task_bbd2c77f713d: Muse1.3 source-only labels, completed with the qualifications
  above. Malformed JSON was corrected by worker before acceptance. Unneeded
  external-config/env access was rejected. Workers released and terminals closed.
Kiro monthly limit and Antigravity readiness failures were already established;
no retry or Codex fallback agent was used in this wave.

## Verification

- `uv run pytest -q`:1744 passed, two existing dependency warnings,125.71s before
  the final percent enhancement. Final relevant suite:149 passed (new percent test
  included),3.21s. Includes binding/tagging/retrieval plus table/review tests.
- `uv run ruff check apps packages tests evaluation`:passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation`:
 154 source files passed, existing untyped-body notes.
- `uv build --all-packages --out-dir .local/showcase-eval/dist`:four packages built.
- `uv run python scripts/verify_architecture.py`:passed.
- `uv run python scripts/validate_package.py`:743 passed; documentation/contracts only.
- Chrome UI:38 cards; Kia filter6 cards; missing reviewer and malformed JSON blocked;
  actual downloaded file verified with38 null labels and fixture-ui-test identity.
  Browser download-event observer timed out, but file contents verified independently.
  No browser console errors. Download moved to private ui-download-test.json and is
  excluded from human measurements. Target highlight/layout inspected visually.
- Independent human benchmark, end-to-end real service tagging, source approval,
  deployment and load performance:not_run. These remain necessary for service claims.
