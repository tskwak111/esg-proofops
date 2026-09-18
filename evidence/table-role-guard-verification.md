# Expected-effect / achieved-result guard — 2026-09-12

## Reproduced failure

Replayed the archived LG Chem p24 table-role packet and Upstage response in
`.local/table-role-pilot/first/`. All nine original proposals passed. Independently
changing each of c2, c8 and c14 from `expected_effect` to `reported_result` also
passed the old validator, although each cited only the literal `기대 효과` header.
These three mutations are adversarial test inputs, not new model responses.

The old shared validator checked cell/header identity and column alignment, but
did not enforce the prompt's explicit expected-versus-achieved distinction.
This was acceptance as a model proposal, not an observed final-grade failure.

## Scope and compatibility

The repair rejects `reported_result` whenever any supplied same-column candidate
header has the literal `기대 효과`, even if the model cites another header or omits
the contradictory one. Mixed headers require review rather than automatic role
reassignment. The initial sole-basis repair was tightened after coordinator review.

The repair is confined to the opt-in evaluation table-role validator. It does
not infer semantic roles generally, approve source quality, accept bindings,
or change grades. Literal header matching ignores whitespace only; other wording,
merged-header interpretation and semantic accuracy remain unresolved. Unknown
remains unknown and successful tags remain model_proposed/binding undetermined.

Future request receipts use tagging contract version 4 (version 3 was an
intermediate local repair with no model calls). Archived requests,
responses, source references and earlier validation records remain immutable.
No API/DB schema, dependency or migration changes. Rollback restores the earlier
validator for new evaluation runs; preserve both versions' receipts and do not
treat rollback as source or evidence approval.

## Coordination

Orca run `run_d31424bff15e`, task `task_77d8a088f471`. The initial Kiro session
ended before task execution and its dispatch `ctx_8c05ac63c357` was stopped after
observing the exit. OpenCode Muse Spark 1.3 Free executed the replacement
`ctx_d5163d78960d`, followed by task `task_a91fb1e18c23` / dispatch
`ctx_ddc34578bd45` for the omitted-header bypass. Both completed; the external
terminal was released from orchestration, then explicitly closed. No reclaimable
workers remain. The coordinator independently reproduced the archived-source
failure and owns integration evidence. No live report-model calls or ledger
changes; the last committed/reserved amount remains $2.0411683250 / $10,
including two previously unsettled calls.

## Coordinator verification

- `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync
  pytest -q`: **1,461 passed in 96.21s**, three warnings (Starlette/httpx,
  AnyIO alias deprecation, and a Pydantic cursor-field alias warning in the
  run-lifecycle test). No test failures. A focused table-role/table-binding/
  evidence-binding run also passed 60 tests in 1.22s; it overlaps the full suite.
- Final archived replay: original nine tags preserved, all three adversarial
  achieved-result mutations rejected. Original packet/response hashes match the
  earlier evidence record; exact source/basis refs and final validator hash are
  in `table-role-guard-replay.json`. This is archived response validation, not a
  new PDF parse or live model performance measurement.
- `uv run --no-sync ruff check .` and `ruff format --check .`: passed, 234 files.
- `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src
  apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`: passed,
  146 source files, existing untyped-function coverage note retained.
- `uv build --all-packages --out-dir /tmp/proofops-table-role-build`: four Python
  packages built. The modified evaluation script is outside those packages.
- `uv run --no-sync python scripts/verify_architecture.py`: passed.
- `uv run --no-sync python scripts/check_licenses.py --env
  ENABLE_LEGACY_PYMUPDF=false`: supply-chain gate passed; human release approvals
  remain separate.
- `uv run --no-sync python scripts/validate_package.py`: 734/734 documentation
  and contract checks passed, separate from application tests.

Live model, approved source-quality/vision validation and deployed end-to-end
processing remain `not_run`. Frontend/browser checks were not repeated for this
evaluation-only change; no frontend, API or worker composition changed.
