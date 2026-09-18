# Source-bound preliminary classification — 2026-09-18

Developer A, TASK-009/013 continuation. This is a preparatory boundary and a
worker reliability fix, not live tagging runtime completion or a production release.
Developer B integration files, domain rules, APIs and database schemas are unchanged.

## Contract and compatibility

`application/tagging/preliminary.py` builds a bounded request from an authorized
canonical graph and verified atomic claim sources. Tenant, document, manifest,
source hash, actual source quality, literal claim text and citation lineage are
checked before building input. The request pins claim/graph/prompt hashes.
Only the atomic source texts enter `untrusted_document_data`; report metadata,
other claims and topic shortcuts are excluded.

The response contains exactly claim_id, track, independent safe_harbor_category,
track_confidence and dimensions. Track null means unresolved, with null confidence;
an independently extracted category is retained even if track is unresolved.
No new domain track enum is introduced. A numeric confidence is
uncalibrated model output, not an approval threshold. Domain GAP-002 stays open.

`preliminary-source-quotes-v2` asks for a source_index and literal quote per
non-null dimension. The server finds the quote only inside the indexed atomic
source, accepting exactly one occurrence. Missing, repeated, blank or altered
quotes are rejected. Provenance, coordinates and absolute raw character offsets
are restored from the verified parent and checked by the existing citation guard.
Explicit v1 start/end spans remain strictly validated; incorrect supplied offsets
are never repaired. V1 probe failures remain failures in their original artifacts.

Entity/metric/reporting_period keys are required. Applicable optional axes use the
existing ClaimContext vocabulary, with null retained as unresolved. Literal
validation does NOT prove semantic role correctness or completeness of optional
axes. There is no invented confidence cutoff, no inferred relation tags, no
source-quality promotion, and no grade. Every candidate needs the remaining
semantic/consensus/binding gates before use in a decision.

The existing worker supplier may return None or (None, context, relations).
Those claims now receive PRELIMINARY_TAGS_UNRESOLVED with no model calls/decision;
the worker can continue instead of failing the entire job or raising AttributeError.
Existing non-null tuple suppliers keep their behavior. Checkpoint v1 already
supports blocked records and string reasons, so no migration is needed.
Rollback restores the old runner and stops using the new preparatory helper;
existing blocked checkpoints remain readable. No stored revision is rewritten.

## Actual development probes

Source: the existing native-attested KB pilot, physical page30, run
4f16bfeb-c1cc-4a8a-94d9-47a29b226177. Each probe group freshly replays the source
attestation and extraction checkpoint, then selects its two verified claims;
other five claims are excluded from this bounded experiment, not treated as absent.
Original run/tagging checkpoints were not modified. Six calls were authorized
by the user's cumulative USD20 development allowance, using the existing ledger.

| Experiment | Calls | Literal/schema-valid candidates | Cost USD |
|---|---:|---:|---:|
| Solar Pro3, first offset prompt, escaped JSON | 2 | 0 | 0.0005047350 |
| Solar Pro4, explicit JSON shape, literal Unicode, offsets | 2 | 1 | 0.000843150 |
| Solar Pro4, literal Unicode, unique quote selection | 2 | 2 | 0.000785730 |

Total incremental committed cost: USD0.0021336150. The source/claim set is the
same tiny development set, and both model and prompt changed in the first
comparison. This is not a controlled model ranking, gold accuracy, recall,
cross-company performance estimate, or grade validation.

Observed failure: Pro4 copied a company name correctly but gave an incorrect
end offset. This motivated moving exact character lookup into local code.
Pro3 also returned arrays instead of dimension objects and string "null".
The final candidates still disagree with earlier calls on track, and a selected
"entity" phrase refers to funds rather than an explicitly named company. Those
semantic ambiguities remain unapproved; the source validator correctly cannot
resolve them. The final requests contain no company-specific prompt exception.

Raw request/response/validation files are immutable mode0400 under the three
`.local/preliminary-probe*20260918` directories. The public evidence JSON records
artifact SHA256s, statuses and costs without report text or keys. Each request
records model/prompt/rule/claim/graph identity and replica1. These standalone
probe artifacts are not service revisions or three-replica consensus evidence.
No automatic retry, budget reset, tokenizer estimate or real-runtime gate bypass.

## Orchestration and checks

Orca run run_74184bda2ea5. OpenCode Muse Spark1.3 Free performed the contract
review (task_f65602bfb779); Muse Spark1.2 Free reviewed the initial code
(task_9e6072694cc8). Both settled successfully and their terminals were closed.
The second reviewer found the null-track tuple AttributeError; the coordinator
reproduced it with a failing integration test and fixed it. Quote-selection v2
was added after that review and verified by coordinator regression/live probes.

Red tests first reproduced missing boundary, whole-job failure on unresolved
classification, whitespace evidence acceptance, extreme integer overflow, absent
quote-only support, and null-track AttributeError. Final verification results
are appended below; synthetic test success is not model accuracy.

Remaining: separately frozen extractor/tagger bindings and preflight, validated
provider token reservation contract, durable preliminary supplier wiring,
semantic/independent-gold validation, evidence-relation supplier and cross-report
coverage. The real LocalTagRunner transport gate stays closed until these exist.
AWS/deployed-service tests: not_run. New browser interaction test: not_run
(no UI/API change); local staging E2E gate is included in the Python suite.

Final coordinator review also preserved an independently extracted safe-harbor
category when the track is unresolved (GAP-002); a regression proves these fields
are not coupled. Current-runtime source replay plus validation of all six archived
responses reproduces all six original accept/reject statuses with zero model
calls. Historical rejected spans are not repaired. The final prompt differs from
the last live probe only by a line wrap; the exact sent prompt is in each receipt.

No new dependency, API, database or rulepack schema is introduced. GitHub PR1 was
already squash-merged by the time of finalization; origin/main tree matched the
prior feature HEAD exactly. This increment uses the new branch
feature/developer-a-preliminary-validation on origin/main, preserving that merge.

## Final verification

- `uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`: **2243 passed, 7 skipped, 2 warnings**, 188.99s. Seven legacy-reference tests lack the ignored snapshot in this checkout; warnings are existing Starlette/httpx and anyio deprecations. Log: `/tmp/proofops-preliminary-release.txt`.
- Focused preliminary + worker tests: **53 passed** (included in the full suite); 32 preliminary boundary cases and 21 worker integration cases. The previous 51-case run preceded the nonzero atomic-offset and independent-category regressions.
- `uv run ruff check .` and `uv run ruff format --check .`: pass, 306 files formatted.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`: pass, 175 source files.
- `uv run python scripts/verify_architecture.py`: pass.
- `uv run python scripts/validate_package.py`: 821 documentation/contract checks pass; not an app test.
- `uv build --all-packages`: all four Python packages built.
- `pnpm --filter proofops-web typecheck` and `pnpm --filter proofops-web build`: pass (UI unchanged).
- `uv run python scripts/check_licenses.py --root . --env ENABLE_LEGACY_PYMUPDF=false`: supply-chain/source-secret gate passes. Dependency locks unchanged; vulnerability network audits were not rerun in this increment.
- Actual model probe totals and zero-call archived-response replay are recorded in `preliminary-probes-20260918.json`.
