# Local extraction executor — contract before implementation

Additive private checkpoint schema `local_extract_checkpoint_v1` uses the existing
job schema v1 `job_records(kind=artifact)` immutable insertion and SHA256 pointer.
The payload contains exact serialized ClaimDiscovery (claims, receipts including
raw responses, exclusions, processed IDs, quality issues), ExtractionProfile,
run/input/source/graph/parser-checkpoint/manifest/rule/model-binding hashes,
coverage, and explicit synthetic/fast_preview status. META gains `extract_job`
and `claim_snapshot_sha256`. The existing commit transaction validates the scope
and pins, inserts the immutable artifact, advances current_stage to tag, and
creates the pending tag job/outbox atomically. Extract never marks the run complete.

Migration is retaining and additive: no table rewrite, deletion, new dependency,
or existing signature change. Old runs without explicit extraction pins fail
closed; create a new run to select extraction. Rollback stops extract workers,
restores the earlier application, and retains DB/artifacts/pointers and pending
outbox for a later forward restart. Parser CLI without --stage remains unchanged.

Storage API: LocalClaimStore(store, uploads, parser), load(tenant_id, run_id)
returns ClaimDiscovery; list returns tuple[Claim, ...]; get also accepts claim_id
and returns Claim; load_snapshot returns the checked checkpoint dictionary.
Missing publication or foreign claim raises KeyError; corrupted records fail
closed. All reads verify the original and graph via load_run_graph, checkpoint
hash/pointer, identities, immutable run pins, graph hash and exact replay of the
stored responses through TASK-008 discovery. Replay does not call a model.

LocalExtractRunner(store, uploads, parser, *, extractor, telemetry, clock=time.time)
requires an explicit ClaimExtractorPort. Synthetic mode requires persisted
extraction_mode=local_synthetic, extraction_profile and extraction_profile_hash.
Structured injection is only a caller-owned test transport. Source quality is
never upgraded; no hidden sampling, quota, grade, track or label is introduced.

## Implemented result

`LocalExtractRunner` consumes only explicitly addressed tenant/run extract outbox
messages through accepted consume_job/observe_job. It renews and checks the lease
before each extractor call and retains usage when cancellation races renewal.
The checkpoint artifact, exact discovery/receipt/exclusion snapshot, publication
pointer, coverage, and pending tag outbox commit in one existing SQLite transaction.
The run remains running/current_stage=tag, complete=false; no decision is fabricated.
The accepted parser CLI remains the default. Extraction additionally requires
`--stage extract`, `LOCAL_EXTRACTION_MODE=local_synthetic`, and matching frozen
ExtractionProfile pins. Legacy unpinned runs fail closed without extractor calls.

The accepted heuristic rule_sha256 is independent of the grading rulepack SHA256;
both are persisted, alongside graph/source/run input/manifest/parser checkpoint,
model binding, model and prompt hashes. Root owns the additive RunService snapshot
pins and public claims routes. LocalClaimStore verifies all publication inputs and
replays stored responses against the verified rich graph; it invokes no provider
or extractor transport. This currently verifies the entire graph/snapshot per read;
there is no sampling, quota, cache or semantic accuracy assertion.

## Actual verification (2026-09-09)

Initial red: `uv run --no-sync pytest tests/integration/test_local_extract_runner.py -q`
failed with ModuleNotFoundError for the not-yet-created claim_store module.

Final focused behavior and job regression:

```text
uv run --no-sync pytest tests/integration/test_local_extract_runner.py tests/acceptance/test_jobs.py -q
45 passed, 2 warnings in 17.22s; exit 0
```

This includes 23 extraction integration cases: generated PDF multipart HTTP upload,
HTTP run creation, actual OpenDataLoader/auxiliary parser, actual extraction worker,
SQLite reopen and exact Claim/receipt/exclusion equality, duplicate delivery, pending
tag outbox, zero product-client calls, unverified source quality, no raw/source logs,
failed/unknown/excluded chunk denominator retention, pre-call and in-flight cancel,
expired/superseded workers, crash inside the commit after artifact and outbox writes,
recovery, rehashed source-quality tamper rejection, all three extractor pin mismatches,
invalid publication pins/schema/coverage rollback, explicit real CLI selection and
reopen, manual retry, unpinned legacy rejection, and cancel/heartbeat race usage.

Earlier accepted-parser and discovery regression, before the final schema/race guards:

```text
uv run --no-sync pytest tests/integration/test_local_extract_runner.py tests/integration/test_local_parser_runner.py tests/acceptance/test_claims.py tests/acceptance/test_jobs.py -q
80 passed, 2 warnings in 21.63s; exit 0
```

Final lint/type commands:

```text
uv run --no-sync ruff check packages/proofops/adapters/local/claim_store.py packages/proofops/adapters/local/job_store.py apps/worker/src/proofops_worker/extract_runner.py apps/worker/src/proofops_worker/composition.py apps/worker/src/proofops_worker/main.py tests/integration/test_local_extract_runner.py
All checks passed!; exit 0
uv run --no-sync mypy --follow-imports=silent packages/proofops/adapters/local/claim_store.py packages/proofops/adapters/local/job_store.py apps/worker/src/proofops_worker/extract_runner.py apps/worker/src/proofops_worker/composition.py apps/worker/src/proofops_worker/main.py
Success: no issues found in 5 source files; exit 0
```

The two test warnings are existing Starlette/httpx and anyio deprecations. No
external dependency or framework was added by this worker. Wheel/build, full WIP
suite, public API/UI integration and manifests are coordinator-owned; not_run here.
AWS, real models, vision, customer documents, corpus accuracy and production readiness
are not_run. Local tests use generated PDFs and explicitly synthetic approvals.
No Git operations, cloud writes, provider invocation or document logging occurred.


## Coordinator acceptance

- Root actual `uv run --no-sync pytest tests/integration/test_local_extract_runner.py -q`: 23 passed, two existing TestClient warnings.
- Root numeric/lifecycle regression: 104 passed (68 numeric + 36 lifecycle). Optional extraction profile/mode now freezes the exact extractor receipt settings in RunService. The extraction heuristic rule hash is intentionally independent from the selected grading rulepack, as established by SyntheticClaimExtractor's existing profile.
- Focused Ruff and checked-body mypy passed for the five executor/store/composition files. Both worker and agent offline wheel/source builds passed; the internal workspace dependency was explicitly added in 6470bb8.
- Claims/source/composed-API checks: 3 passed, including actual multipart/parse/extract reads and signed immutable pagination. One intermediate run hit the concurrent request-control worker's transient JSON strict-mode regression; corrected before acceptance without changing the uploaded fixture.
