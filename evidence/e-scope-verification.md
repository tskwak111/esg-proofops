# E narrative → appendix → rules: first local case

Date: 2026-09-09 KST. Source: LG Chem report supplied by the user, SHA256
`c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde`.

## Implemented and executed

- Actual OpenDataLoader/pdfplumber parse and immutable reload of physical pages
  **24, 97, 117** under one new manifest. Original PDF hash is unchanged.
- Existing `ClaimScope(declared_subset, (24,))` visits only E narrative for claim
  extraction. Appendix pages remain in the original graph for evidence search.
- Explicit offline span fixtures identify **2 claims** on p24: a 2030 target and
  an energy-efficiency achievement. Unmatched text stays unknown. No topic quota
  or automatic non-claim classification is introduced.
- New `normalize_table_bindings` supports explicit cell-role assignments for
  nonstandard headers. **9 real numeric values** from the p97 global Scope 1/2,
  Scope 1 and Scope 2 rows (2023–2025) normalize through existing decimal and
  provenance code. Every assignment and original cell reference is retained.
- A bounded local lexical probe searches the selected appendix pages through
  `retrieve_evidence`. All source quality remains unverified: **0 verified
  evidence candidates are admitted**. Missing search results remain unknown.
- The real Python rules engine executes an explicitly synthetic guard replay:
  **2 blocked_evidence results, grades and labels null**. It receives no invented
  present/absent facts. Fixture replica hashes are not real model-call receipts.

The default automatic normalizer still returns **0** in this case. The new path
accepts structured extraction assignments; it is not an automatic table tagger
and is not wired to a live model/API inference path. Raw units such as `tCO e\n2`
are retained, not silently rewritten to tCO2e. Numeric extraction here does not
establish unit interpretation, source verification or usable approved evidence.

## Reproduce

```sh
uv run --no-sync python evaluation/e_scope_case.py \
  --pdf '기업보고서/배터리 에너지/LGChem_Sustainability_Report_2025_KOR.pdf' \
  --output .local/e-scope/reproduction \
  --java /opt/homebrew/opt/openjdk@21/bin/java
```

The script requires the pinned hash and a fresh output directory, validates the
rule pack, asserts page/claim isolation, parses/reloads real artifacts, checks the
nine observations and null decisions, and writes `result.json` with receipts,
source cells, role assignments, packets, decisions and limitations. It never
modifies the PDF or a previous run. Executed output is `.local/e-scope/case/`.
No third-party source code or new dependencies were added.

## Validation

- New binding tests first failed: 5 expected missing-function failures in
  `.local/e-scope/bindings-red.log`.
- Final focused scope: **167 passed**, 3.53s, covering bindings, tables, geometry,
  numeric checks, retrieval and rules (`.local/e-scope/targeted.log`).
- Ruff lint passed; format check: **213 files**. Mypy: **137 source files**.
- Four Python packages built as wheels and sdists.
- Broad regression: **1390 passed**, 2 existing dependency deprecation warnings,
  103.05s (`.local/e-scope/full-tests.log`). Overlapping scopes are not summed.
- Document/contract validator: **705/705 passed**. This is not an app test.

Commands:

```sh
uv run --no-sync pytest tests/acceptance/test_table_bindings.py tests/acceptance/test_tables.py tests/acceptance/test_geometry_issues.py tests/acceptance/test_numeric.py tests/acceptance/test_retrieval.py tests/acceptance/test_rules.py -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py
uv build --all-packages --out-dir .local/e-scope/build
uv run --no-sync pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q
uv run --no-sync python scripts/validate_package.py
```

## Remaining boundaries

Full declared E scope is provisionally p16–49, with environmental data p97–102;
only this three-page case was executed here. Automatic section identification,
semantic table role extraction, live claim/tagging replicas, source-quality vision
approval and accepted numeric/assurance attribution remain unverified/not_run.
No production grade, full-E accuracy, AWS/staging, browser rerun, or live
product-model result is claimed. No GitHub push or cloud mutation occurred.

Kiro independently reviewed source cases in Orca run `run_593a2a208ae4`;
coordinator corrections to page ranges and domain interpretation are documented
in `evidence/e-scope-case-review.md`. Worker completion was accepted, dispatch
released, and the exact coordinator-created terminal closed before acknowledgment.
