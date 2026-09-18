# TASK-010 integration repair evidence

Dispatch: `task_a38e1ae84ffa` / `ctx_1c2f01edf1d9`.
Scope: two coordinator-reported integration defects, original TASK-010 files,
minimal authorized retrieval helper, and this report. No Git operations, shared
contracts, manifests, subagents, or whole-workspace test runs were performed.

## Implemented behavior

1. `freeze_track_packet(retrieved_packet, *, track, rulepack)` creates a new immutable
   `EvidencePacket` with the complete approved catalog for the selected track.
   Its canonical hash covers `track`, `safe_harbor_category`, `allowed_elements`,
   selected candidate permissions, and the original `retrieval_packet_sha256`.
   Original retrieval bytes, source evidence and provenance remain unchanged.
   The helper validates claim/tenant/document/manifest/source/rulepack identity,
   track/category and catalog completeness. Revalidating the selected packet is
   idempotent; changing track requires selection from the original retrieval.
2. `tag_replicates` requires that explicit selected packet before any provider or
   cache work. `form_consensus` uses its entire catalog without silently removing
   elements according to model output. Both reject an unselected or incomplete
   packet, and all three replicas retain the selected packet hash.
3. Bedrock JSON parsing, structured content validation and typed usage construction
   now share the bounded-response error boundary. Malformed usage objects/counts,
   non-array content and invalid JSON preserve `provider_response_json`; unknown
   usage remains unknown. Failed raw envelopes survive actual service invocation,
   immutable raw-cache storage and exact-request recovery without another call.

## Acceptance and regression coverage

- The integration test calls actual `retrieve_evidence`, freezes its full track
  catalog, runs all three service calls, and calls actual `form_consensus`.
  It checks different original/selected hashes, immutable original bytes,
  idempotent selection, full P1–P6 requests/candidates and rejection of the
  original unselected packet by service and consensus.
- All three approved tracks have a complete-catalog selection test; removing a
  selected element is rejected before dispatch.
- The old setup rewriting `allowed_elements=[P1]` is gone. Every tagging fixture
  now freezes the complete performance catalog from actual retrieval. The former
  single-P1 auto-confirm expectation was unsafe for that full catalog: tests now
  require retained verified P1 evidence and binding, P2–P6 unknown, and review.
  Majority counts and citation union are still checked for all six elements;
  explicit product attribution is retained in every immutable review run.
  No applicability, P4 or P6 gate is suppressed to obtain auto-confirmation.
- One parameterized malformed-provider regression covers nine bodies: invalid
  JSON, null/list/string usage, invalid token count, and null/number/object/string
  content. It verifies all three raw provider envelopes, failed/unknown usage,
  exact cache recovery, no redispatch and no confirmed tags.
- Fixtures, search transport, SDK transport and token counters are explicitly
  synthetic. Citation, binding, retrieval, packet hashing, tagging, consensus,
  budget ledger and cache behavior are the actual implementations.

## Exact commands and observed results

Red regression command, before implementing either repair:

```sh
uv run pytest tests/acceptance/test_tagging.py -q -k 'malformed_provider or retrieve_select or selected_packet'
```

Exit 1: **9 failed, 4 passed, 36 deselected in 0.40s**. Five failures reproduced
lost provider envelopes for invalid usage/content; four failed because the
track-scoped freeze helper did not exist.

After implementation and complete-catalog fixture correction:

```sh
uv run pytest tests/acceptance/test_tagging.py -q
```

Exit 0: **49 passed in 1.46s**.

Formatting pass:

```sh
uv run ruff check packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py packages/proofops/application/evidence/retrieval.py apps/agent/src/proofops_agent/tagger.py tests/acceptance/test_tagging.py --fix
uv run ruff format packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py packages/proofops/application/evidence/retrieval.py apps/agent/src/proofops_agent/tagger.py tests/acceptance/test_tagging.py
```

First command exit 1: four formatting/import findings, one fixed automatically;
three line-length findings remained. Second command exit 0: three files formatted,
two unchanged; the subsequent lint command below passed.

Final scoped checks (after executable changes and formatting):

```sh
uv run pytest tests/acceptance/test_tagging.py tests/acceptance/test_retrieval.py -q
uv run mypy packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py packages/proofops/application/evidence/retrieval.py apps/agent/src/proofops_agent/tagger.py
uv run ruff check packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py packages/proofops/application/evidence/retrieval.py apps/agent/src/proofops_agent/tagger.py tests/acceptance/test_tagging.py
uv run ruff format --check packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py packages/proofops/application/evidence/retrieval.py apps/agent/src/proofops_agent/tagger.py tests/acceptance/test_tagging.py
```

All exit 0: **70 passed in 2.45s**; **no mypy issues in 4 source files**;
**all lint checks passed**; **5 files already formatted**. The final format check
also covers the later docstring documenting the stable caller sequence.
Tests exercise unit invariants, structured-output contract validation, local
retrieve→freeze→tag→consensus integration, recovery and tenant/provenance guards.
No separate broad unit/contract/integration/security directory run was repeated.

## Stable caller interface and remaining gates

```python
selected = freeze_track_packet(retrieved, track=track, rulepack=rulepack)
runs = tag_replicates(selected, context=context, track=track, original=original,
                      relation_tags=relation_tags, rulepack=rulepack,
                      settings=settings, cache=cache, usage_store=usage_store,
                      invoke=invoke, tenant_id=tenant_id, ensemble_id=ensemble_id,
                      consent_profile=consent_profile, token_counter=token_counter,
                      now=now)  # optional pricing=PricingSnapshot
result = form_consensus(runs, packet=selected, rulepack=rulepack,
                        tenant_id=tenant_id, tag_revision=tag_revision)
# Optional form_consensus rule_gaps=tuple[str, ...].
```

Persist both immutable packets and the `TagRun` receipts. The return interfaces
remain `tuple[TagRun, ...]` and `ConsensusResult`; no field or storage contract was
changed. Existing raw/provider envelopes, request identity, usage, guarded tags,
status/errors, source/binding provenance and product attribution remain present.
The coordinator received this interface via Orca message `msg_0e8ca572a43c`.

- **not_run:** live product model, Bedrock/AWS mutation, private customer processing,
  production tokenizer/pricing/accuracy, product browser E2E and deployment.
- **not_run in this repair:** package builds and broad workspace checks, per the
  explicit request for scoped tests/lint/mypy only.
- **blocked/not_run:** human data/rights/legal/model/domain approvals. No approval,
  applicability attestation, assurance result or numerical check was fabricated.
- **Coordinator integration remains:** persist the selected packet and supply it
  to both tagging and consensus in worker/storage composition. Neither this
  repair nor its local synthetic integration claims complete product deployment.

Coordinator acceptance: `uv run --no-sync pytest tests/acceptance/test_tagging.py
tests/acceptance/test_retrieval.py tests/security/test_prompt_injection.py -q` passed
80 checks. Ruff passed and checked-body mypy passed across all five affected application/
agent source files, including the existing tracks module. The repair worker transferred
to the bounded local tag executor task on its exact terminal before acknowledgement.
