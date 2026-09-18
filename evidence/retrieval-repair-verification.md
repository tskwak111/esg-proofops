# Major blocker audit and local retrieval repair — 2026-09-10

## Root causes and change

Two failing-first regressions reproduced defects in the existing `SectionSearch`:
Korean inflected words such as `온실가스를` did not match `온실가스` in data or
appendix, while numeric query `4` incorrectly matched `54` and `400`. The old
unweighted substring count also let common fragments dominate full sentences.

The same local search class now uses Korean character bigrams and whole Latin /
numeric tokens with BM25 ranking. Corpus term counts are built once per search
instance from the allowed E + all ESG DATA + all APPENDIX pages. It returns at
most 20 same-document source-hashed hits; raw text, source identity and quality
are unchanged. The deterministic index generation changes from lexical-v1 to
korean-bigram-bm25-v2. Existing stored packets/results remain immutable; callers
must use the new search scope for new searches. Rollback restores the previous
search code and starts new searches under the prior generation, without rewriting
old artifacts. No API/DB migration, external dependency, domain threshold or
production OpenSearch change.

This is candidate routing, not a Korean semantic parser, accepted atomic claim,
numeric equivalence or evidence attribution. Bigram overlaps can be irrelevant;
short headings, duplicate parser representations and GRI entries can compete for
the top 20. No semantic recall/precision or corpus-wide accuracy is claimed.

## Actual-source diagnostics

Replayed the PDF-validated 57-page LG Chem graph with its existing section map.
For the selected lookup phrase `온실가스를 감축하였습니다.`, old hits were only
p24/25/26; new hits include p97 environmental data and p118 verification-related
text. Renewable-energy wording now also reaches p99 energy data; water-use wording
reaches p101 water data. These are related-source routes, not assertions that the
specific company values or reduction effects are supported by those pages.

The comparison includes three coordinator-selected lookup phrases and four full
original sentences from the previous semantic extraction trial. Source hash,
map hash, index generation, implementation hash, old/new ranks and source quality
are recorded in `retrieval-repair-results.json`. Full original source refs and
quotes remain in the linked local artifact. No stored model result was repaired.

## Orchestration review decisions

Run `run_8da39461f3eb`, OpenCode Muse Spark 1.3 Free workers:

- `task_4e876c761135` / `ctx_595db7baac49`: extraction audit succeeded.
  Archived responses show all-null output and wrong semantic roles; source-exact
  validation does not establish correct roles. The proposed string-null coercion
  and batch salvage were **not adopted**: strict rejection is intentional, and
  changing it would not repair semantic errors. Single-claim and few-shot trials
  already exist and do not establish a reliable fix. Model capability remains
  unresolved; no further speculative prompt variants were called here.
- `task_fbfe399316d6` / `ctx_35cce0b18096`: retrieval audit succeeded.
  Confirmed that unverified graph sources remain blocked by production retrieval.
  That quality gate is required and was preserved. Index generation was already
  tied to the section map; the change additionally versions the new algorithm.
  No unsafe same-table acceptance was reproduced in this audit, so that proposed
  concern was not presented as a fixed defect.

Both worker deliveries were processed and acknowledged, both external terminals
closed after release receipts, and the reclaimable worker list is empty.

## Verification

Five section-pipeline integration tests pass, including the two reproduced defects
and the existing tenant/map/quality guards. Ruff lint/format (234 files), mypy
(146 files), four-package Python build, architecture and supply-chain checks pass.
No new model calls or ledger changes: cumulative committed/reserved $2.040014315
of $10, including two prior unsettled calls. Live model, AWS/deployed E2E and
production-image security verification: not_run this turn.

Final commands/results:

- `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`
  — 1,457 passed in 129.13s, two existing Starlette/AnyIO deprecation warnings.
- `PYTHONPATH=. uv run --no-sync python .local/retrieval-repair/expanded.py`
  — seven same-graph old/new routing cases passed source-hash/scope/top-20 checks.
- `uv run --no-sync ruff check .` and `uv run --no-sync ruff format --check .` — passed.
- `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`
  — passed, with the existing untyped-body annotation note.
- `uv build --all-packages --out-dir .local/retrieval-repair/dist` — passed.
- `uv run --no-sync python scripts/verify_architecture.py` — passed.
- `uv run --no-sync python scripts/check_licenses.py --root . --env ENABLE_LEGACY_PYMUPDF=false`
  — passed; human rights approvals and deployed-image verification remain separate.
- `uv run --no-sync python scripts/validate_package.py` — 728/728 documentation
  and contract checks passed, separately from application testing.

Remaining priorities: semantic-field capability on explicit report spans; a
validated source/table-quality path; then same-company/period/metric evidence
attribution. Better retrieval only repairs the candidate-search stage. The
industrial-complex water-supply sentence remains a diagnostic negative/ambiguous
case for company attribution, not an accepted company-consumption claim.
