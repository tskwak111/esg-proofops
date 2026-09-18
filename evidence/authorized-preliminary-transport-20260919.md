# Authorized preliminary transport — 2026-09-19

Scope: the real Upstage transport boundary for preliminary source-quote
classification. Service/API wiring is still incomplete; this is not a production
or model-accuracy result. No paid model calls or AWS operations in this change.

`UpstagePreliminaryTransport` reuses the existing transport's request-time
authorization, lock, exclusive receipt directory, incomplete-call fence, raw
response retention and shared USD ledger. The distinct preliminary profile
requires its own settings hash and the current preliminary system prompt. An
element-tagger approval cannot be substituted. The caller must authorize the
actual packet/source and validate returned quotes against the original graph.

The wire accepts exactly the preliminary envelope: tenant, claim, source graph
and claim hashes, prompt hash, and indexed literal source text. It rejects grade
fields, source-index booleans, reordered indices, invalid identity and tampered
packets before provider dispatch. Transport success never approves a grade.
Existing compact tagger wire identity is unchanged. No API/DB migration or new
dependency; rollback removes preliminary callers while preserving receipts.

## Executed checks

- Initial focused preflight + existing tagger + new transport: 89 passed.
- `uv run pytest tests/unit tests/contracts tests/acceptance tests/integration
  tests/security tests/e2e/test_staging_gate.py -q`: 2334 passed, 7 skipped,
  2 existing dependency deprecation warnings, 195.40 s. Log:
  `/tmp/proofops-preliminary-transport-suite.txt` (local).
- The final test-only change recomputes malformed envelope hashes to exercise
  schema validation and adds an independent digest-mismatch case.
  `uv run pytest tests/integration/test_upstage_preliminary_transport.py -q`:
  28 passed. Full-suite collection preceded that one added test.
- `uv run ruff check .`: passed; `uv run ruff format --check .`: 313 files
  formatted before the final test-only change.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src
  evaluation tests/load infra/cdk/staging_gate.py`: 178 source files passed.
- `uv run python scripts/verify_architecture.py`: passed.
- `uv run python scripts/validate_package.py`: 823 documentation/contract checks
  passed (not application or model accuracy).
- `uv run python scripts/check_licenses.py --root . --env
  ENABLE_LEGACY_PYMUPDF=false`: passed; human rights approvals remain separate.
- `uv build --all-packages`: four Python packages built.
- `pnpm --filter proofops-web typecheck` and `pnpm --filter proofops-web build`:
  passed. These do not establish a live browser/model E2E result.
- `git diff --check`: passed.

## Remaining integration

Independent immutable preliminary/element runtime bindings, current-time source
authorization, durable preliminary ensemble consumption, validated token-budget
reservation, relation tagging, and live worker/review composition remain open.
Rulepack domain gaps and independent gold evaluation are not resolved by this
transport or its tests. Real provider execution for this transport: `not_run`.

OpenCode implemented the transport and its tests; coordinator integrated the
shared authorization change, strengthened boundary tests and ran verification.
Antigravity completed an independent read-only runtime review. The coordinator
accepted the traced integration blockers, but rejected the unproved byte-plus-500
token ceiling and the proposed omission of independent preliminary binding pins.
The proposal also conflicted on whether live extraction and tagging could
coexist. It is not an approved implementation contract; the corrected constraints
are recorded in `docs/autonomous-completion-plan.md`. Both workers were released
and their external terminals closed after accepted lifecycle completion.
