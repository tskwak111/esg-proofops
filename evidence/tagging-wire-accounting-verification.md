# Tagging wire-input accounting — 2026-09-13 KST

Baseline `1c89ee1`; Orca run `run_15b3add9cec8`. This closes a real
preflight-input mismatch, not the remaining real-worker activation or accuracy gates.

## Change and evidence

The tagging service previously reserved input tokens against concatenated logical
prompts. Upstage then rewrote source references, schema and Unicode serialization,
so a tokenizer at that old boundary would count different input. The adapter now
uses one validated wire builder for counting and dispatch. The service requires a
request counter for non-synthetic bindings, validates its integer result before
reservation, and retains the synthetic-only legacy fallback. Missing configuration
fails before spending. Invalid counts or validation errors are sanitized as
`invalid_request / TAGGING_INPUT_COUNT_INVALID`. Cache recovery neither counts nor
dispatches again. No API DTO, database migration, dependency or wire-profile change.

Failing-first checks reproduced the missing real-counter guard and then incorrect
cache-error classification for boolean/negative/string counts and counter failures.
Fake-HTTP integration checks compare counted system/user messages against actual
probe request bodies, inspect reserved token values, exercise all three replicas
and cache recovery, and prove a wire count above the run limit creates no paid call
or transport receipt. Fixture token values are not model-token accuracy evidence.

Six archived Samsung Life/KEPCO requests from
`.local/tagging-holdout/frozen/tagging/` reproduce identical wire system/user content,
source-ref maps and logical request hashes. This offline comparison invokes only
the side-effect-free builder; their historical diagnostic profiles are not accepted
current runtime bindings. No old receipt is re-approved or counted as a new vote.
The initial harness compared Python tuples with JSON lists; canonical JSON-type
comparison corrected that harness mismatch without changing production code.
Private replay output: `.local/tagging-wire-accounting/replay.json`.

## Tokenizer boundary

The official [Solar Pro3 tokenizer repository](https://huggingface.co/upstage/solar-pro3-tokenizer)
was checked at revision `c41b71f0519c580610cb0fd2af4ed2b23cad544f`.
Its [tokenizer configuration](https://huggingface.co/upstage/solar-pro3-tokenizer/blob/c41b71f0519c580610cb0fd2af4ed2b23cad544f/tokenizer_config.json)
has no `chat_template` and disables automatic BOS/EOS insertion. These files do
not establish the full provider chat-framing count, nor Pro4 compatibility.
No tokenizer package or guessed overhead was added. A validated model-specific
counter and pinned runtime composition remain required; this hook supplies the
correct messages to that future counter, not a claim of exact billed counts today.

## Verification

- `uv run pytest -q tests/integration/test_upstage_tagging.py tests/acceptance/test_tagging.py tests/integration/test_local_tag_runner.py tests/integration/test_worker_recovery.py tests/contracts tests/e2e/test_staging_gate.py tests/unit/test_prefilter_budget.py tests/unit/test_atomic_pilot_budget.py`:
  **167 passed**, 2 existing dependency warnings, 9.32s.
- `uv run pytest -q tests/security/test_prompt_injection.py`: **10 passed**, 0.06s.
- `uv run ruff check .`: passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
  155 source files passed; 3 existing untyped-body notes.
- `uv run python scripts/verify_architecture.py`: passed.
- `uv build --all-packages --out-dir .local/tagging-wire-accounting/dist-final`:
  all four Python packages built as sdists and wheels.
- `uv run python scripts/validate_package.py`: **743/743 passed**;
  documentation/contracts only, not app or model accuracy verification.

The targeted suite includes worker HTTP integration, contract and offline staging
gate tests. Full-suite rerun, browser E2E, actual real-worker tagging, semantic
accuracy measurement and deployment: **not_run** this checkpoint. No model
quality improvement or production readiness is inferred from these tests.

Muse Spark1.3 free completed two bounded read-only reviews: integration blockers
and the implementation diff. The latter ran17 focused tests and identified the
counter-error status issue; coordinator reproduced and fixed it with four more
cases afterward. Reviews are not full service certification. Both dispatches
settled, were released and their external terminals closed. Reports remain at
`.local/tagging-accounting-review.md` and `.local/tagging-wire-diff-review.md`.
Kiro's recorded monthly exhaustion and Antigravity's previous readiness failures
were respected; no Codex worker was needed. One initial review conflated token
reservations with monetary consumption: the USD probe's fixed per-call reservation
is independent, and no such policy change was made.

## Spend and remaining gates

Read-only verification of the sole `.local/upstage/budget.sqlite3` ledger:
1237 calls,6 unsettled,USD7.2391452150 committed/reserved, unchanged. **New paid
calls:0.** Six uncertain USD1 reservations remain retained; no refund, retry,
alternate spending ledger or Bedrock. Original PDFs and credentials were untouched.

Remaining: validated real tokenizer/provider counting and runtime/replay pins;
source-quality approval; table/claim attribution; representative independently
labelled accuracy evaluation. LocalTagRunner still rejects non-synthetic transports.
LLM proposals remain separate from source verification and Python-only grading.
