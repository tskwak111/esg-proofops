# Local evidence search verification — 2026-09-19 KST

Promoted the existing section evaluator BM25 implementation into the local adapter
and removed duplicate ranking code from SectionSearch. No live model call or budget
mutation. No grades or source approvals published. Contract:
`docs/local-evidence-search-contract.md`.

- Orca run run_d3d72e0506f0, Muse Spark1.3 free worker implemented the adapter and
  failing-first tests in its two owned files; coordinator integrated/reviewed it.
  Worker released and terminal closed after accepted completion.
- Focused integration/retrieval/security-scope tests:48 passed. An initial four
  failures exposed a changed evaluation exception message; the compatibility
  wrapper restores the old message without weakening the scope check or tests.
- Ten pre/post search results (including empty and zero-match queries) and their
  scope hashes were identical. Original comparison artifact is local at
  /tmp/proofops-search-before.json.
- Actual original-PDF manifest/hash reload across Kakao, KB and Doosan; three
  selected E/data/appendix pages each; three fixed environmental queries each.
  All9 searches deterministic, <=20hits, correct scope/source hashes. The9 outputs
  have177 hits total (including repetition across queries), all still unverified.
  This is routing smoke evidence, not relevance precision/recall or gold accuracy.
  Counts and original source/graph hashes: local-evidence-search-20260919.json.
- Real model/AWS/embedding calls:not_run; unchanged cumulative model ledger.

The service still needs real tagger composition, independently pinned runtime
bindings and provider token accounting. Candidate retrieval is not accepted
claim-to-evidence attribution. No whole-pipeline/service-readiness claim is made.

## Final checks

Whole suite:2305 passed,7 skipped,2 existing deprecation warnings in187.57s
(`/tmp/proofops-local-search-suite.txt`). After the final added distant-number
scope regression, focused tests:48 passed; no implementation change after the
whole suite started. Ruff check/format, mypy177 files, architecture, package823
checks, all4 Python packages and web typecheck/build passed. Source/license gate
passed; no new dependency or network vulnerability audit. Browser E2E:not_run;
staging-gate E2E included in the whole suite. Existing legacy-reference skips
remain; software checks do not establish model quality or production readiness.
