# Controlled semantic capability check — 2026-09-10

Created six short Korean synthetic cases with fictitious companies to distinguish
explicit entity/metric/boundary extraction from correct null handling. Expectations
are coordinator-authored development annotations, not human-adjudicated corpus gold.
There are eight explicit facts and ten required nulls. No company PDF, production
source-quality approval, immutable revision or grade is changed by this experiment.

## Actual paired trials

Same six cases, same existing SEMANTIC_SYSTEM, solar-pro3, temperature 0, maximum
2,048 output tokens; one call with JSON mode and one without. Expected answers
were not sent to the model. No few-shot examples or automatic retries were used.

- JSON mode on: all 8 explicit facts exactly matched and all 10 required nulls
  remained null. Own-claim source/schema validation passed. Development positive
  precision and recall were 8/8 each; this is not representative report accuracy.
- JSON mode off: the returned object lacked its final closing brace. Strict JSON
  parsing rejected it; no repaired/partial output was scored or accepted.
- All-null baseline: positive recall 0/8. Null correctness alone cannot count as
  successful extraction. Existing element_metrics was reused with positive facts
  only; valid_source_binding=False throughout these synthetic comparisons.

These observations establish success on these simple examples only. They do not
explain or fix the prior long-report failures and are not independent replicas or
a statistically reliable JSON-mode comparison. The failed real-report trials
remain failed; semantic extraction is not promoted into product inference.

Frozen cases/results and offline replay are alongside this document. Full
packets/requests/responses are in `.local/semantic-capability/{json,text}/`;
the original live runner is `.local/semantic-capability/run.py`. Cases, prompt,
packet, rule, provider-model and request identities are recorded. Synthetic graph
identity uses the existing test fixture and is not a real document hash.

Two calls added $0.000426030. Shared ledger: 93 calls, $2.038971185
committed/reserved of $10, including two earlier unsettled calls. No new provider,
Bedrock/AWS action, dependency, environment setting or credential output.

## Verification

`PYTHONPATH=. uv run --no-sync python evidence/semantic-capability-replay.py`
passed: exact positives, required nulls, all-null recall and malformed-response
rejection. The replay uses archived responses and makes no network calls.
`uv run --no-sync pytest -q tests/integration/test_claim_dimensions.py tests/acceptance/test_binding.py`
passed 58 tests. Ruff lint/format passed for the replay. No application code changed;
full application build/E2E and deployed/cloud tests were not rerun for these
evaluation artifacts. The previous 1,439-test result remains historical evidence.
`uv run --no-sync python scripts/validate_package.py`: 717/717 documentation and
contract checks passed, separate from application tests.

## Orchestration review

Run `run_c517efae4a61`, task `task_959709f95b43`: read-only failure review completed
by OpenCode Muse Spark 1.3 Free (explicit launcher model
`opencode/muse-spark-1.3-contributor-free`, confirmed in terminal output), dispatch
`ctx_05ec268a6ac3`, accepted completion `msg_1c8643e1519f`.
The reviewer checked original requests/responses and confirmed the quoted entity
borrowing and incorrect token-role examples. Successful completion receipts give
no observed transport failure in those trials, but do not prove a unique root
cause for the semantic errors or all-null response. No reviewer edits or live
calls occurred. Coordinator retains implementation and acceptance ownership.

The reviewer suggested six isolated synthetic calls. Those were not run: the
batched synthetic cases already pass, and the next useful distinction is matched
short-clause versus full-sentence real-report inputs with the same explicit facts.
That next experiment remains not_run; no semantic product promotion is justified.

Earlier Kiro dispatch `ctx_b8b07dcf9aef` exited before reporting, with no established
credit cause. Default OpenCode dispatch `ctx_383d919a591d` used configured MiniMax-M3
and ended its turn with `Payment Required: Insufficient balance`; it produced no
review. Both attempts were stopped after observed termination/failure. The third
attempt explicitly selected the requested free Muse model. No Codex worker was
used. After settlement, worker-release reported external_terminal, so the exact
coordinator-created Muse terminal was closed with terminal close, then completion
was acknowledged. Reclaimable worker enumeration returned empty.
