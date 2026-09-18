# Parent-preserving clause review — 2026-09-10

Added an opt-in evaluation helper `clause_review_candidates`, reusing
`prepare_dimensions` / `selected_targets` provenance validation and the existing
explicit-unit quantity extractor. Exactly one comma/whitespace/`이를 통해`
connector and at least one supported value on each side yield two source-exact
review candidates. The first retains its comma; the second retains `이를 통해`.
Whitespace between them remains available in the unchanged parent sentence.
Unsupported inputs preserve the parent with no children. This is a deliberately
narrow diagnostic rule, not a general Korean parser or proof of atomicity.

Every child retains its own SourceRef, original quality and parent SourceRef.
Entity, boundary and year are not inherited. The second back-reference remains
unresolved; binding is undetermined and scoring eligibility false. No Claim
revision, grade, canonical metric, evidence approval, API/DB or dependency change.

The existing LG Chem p25 source (original normalized offsets 129–214) is replayed
locally against the PDF-validated graph. The resulting parent and two candidates
are in `clause-context-results.json`, with original model-artifact/request linkage
and the local candidate-rule hash. This local split does not alter the archived
model response, which returned the whole compound sentence. Source quality remains
unverified; no corpus accuracy or semantic decomposition success is claimed.

OpenCode Muse Spark 1.3 Free reviewed five edge families under Orca run
`run_4b5aae737665`, task `task_d25d6a3d63fa`: marker variants/multiplicity,
unsupported quantities, back-reference leakage, offsets and empty/period cases.
Coordinator retained the narrow diagnostic scope. Whitespace including line breaks
is permitted by the connector; variant words are unsupported. The worker completed,
delivery was acknowledged and its external terminal was closed. No model calls
were added: cumulative committed/reserved remains $2.040014315 / $10, with two
previously unsettled calls. The budget ledger and credentials were untouched.

Two failing-first regressions cover exact child spans and parent preservation,
no inherited boundary/scoring, altered source rejection and unsupported parents.
Focused dimension tests: 24 passed. Ruff lint and format passed (234 files);
mypy passed (146 source files, existing untyped-body note). Four Python packages
built successfully; architecture and supply-chain gates passed. Live Upstage,
AWS/deployed E2E and deployed-image security checks: not_run this turn.

Final verification commands and results:

- `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`
  — 1,455 passed in 135.23s; two existing Starlette/AnyIO deprecation warnings.
- `PYTHONPATH=. uv run --no-sync python .local/clause-context/replay.py`
  — original p25 parent and both source spans verified.
- `uv run --no-sync ruff check .` and `uv run --no-sync ruff format --check .`
  — passed after shortening one overlong comment.
- `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`
  — passed.
- `uv build --all-packages --out-dir .local/clause-context/dist` — passed.
- `uv run --no-sync python scripts/verify_architecture.py` — passed.
- `uv run --no-sync python scripts/check_licenses.py --root . --env ENABLE_LEGACY_PYMUPDF=false`
  — passed; human rights approvals and deployed-image verification remain separate.
- `uv run --no-sync python scripts/validate_package.py` — 727/727 documentation
  and contract checks passed, separately from application testing.

Next unresolved work: evaluate the separate candidates' explicit semantic fields
with parent context available but attribution unapproved. Then validate evidence
links against E/data/appendix on adjudicated cases; neither is completed here.
