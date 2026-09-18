# TASK-031 — Snapshot exports and private downloads

Status: local implementation verified; live AWS/model and human gates remain not_run.

## Scope and integration

Implemented `packages/proofops/application/exports.py`, `packages/proofops/adapters/local/export_store.py`, `apps/api/src/proofops_api/routers/exports.py`, and `tests/acceptance/test_exports.py`. The coordinator authorized the new local adapter through Orca and owns the separate `composition.py`/`main.py` wiring and shared contracts; those files were not edited by this worker. No dependency, commit, push, AWS mutation, real product inference, or customer processing was performed.

The API implements the frozen POST run exports, GET export metadata, and POST download contracts, plus a private authenticated local content endpoint. The existing TASK-021 report projection and JSON/CSV/HTML renderers produce a real ZIP containing requested reports and `manifest.json`; neither export creation nor download recomputes grades. `LocalSummaryStore._claim_ids`, `_decision_has_valid_lineage`, immutable revisions, `current_tag(connection=...)`, and existing audit transactions are reused.

One capture pins the run mutation epoch, every discovered claim's tag/decision revisions (including 0/0 unfinished claims), source version/hash, parse manifest, model/prompt/replica hashes, rule hashes, coverage, original tagged inputs and revision records. Heavy source/graph replay happens outside the SQLite write transaction; the epoch is checked again before publication. Review mutations discard only the attempted capture: one initial attempt plus at most three retries, then durable queued state with `EXPORT_SNAPSHOT_BUSY` and five-second retry eligibility. The local GET poll resumes eligible queued work; this is explicitly local behavior, not a deployed cloud scheduler. Mutation after freezing never changes the rendered snapshot.

Only ready artifacts receive download tickets. Tickets expire after five minutes, bind tenant/export/user and content SHA, and require current session/membership authorization when consumed. CSRF and per-user limits apply: create 10/min, metadata 120/min, ticket issuance 60/min. Responses disable caching; content is an attachment. Idempotency accepts the contract's 16–128-character strings, including non-UUID keys. Failed jobs retain fixed pollable metadata; allow_partial=false rejects unfinished reports with REPORT_NOT_FINALIZABLE.

## Storage compatibility and limits

The local schema migration is additive: `export_schema` version 1 and export-prefixed kinds in existing `job_records`. Immutable insert/update/delete guards cover requests, snapshots, ZIPs and ticket records, including INSERT OR REPLACE. Initialization is repeatable and unknown schema versions fail closed. Existing readers ignore these kinds. Rollback disables export routes/writers and retains stored artifacts and audit history; there is no destructive down migration.

Local export capture is limited to 1000 claims and 32 MiB of serialized captured records; final ZIP size is limited to 32 MiB. Requested report formats are rendered sequentially. Larger outputs fail explicitly and publish no ZIP. The shared local SQLite transaction model is retained; distributed AWS storage/scheduling is not implemented or claimed.

## TDD and acceptance results

Initial RED command:

```text
uv run pytest tests/acceptance/test_exports.py -q
exit 1 — 5 failed because proofops.adapters.local.export_store did not exist.
```

Additional RED checks caught fixed failed-job polling behavior and the overly narrow UUID-only idempotency validation. Fixture-only corrections aligned the preexisting Auth/Review APIs, JSON tuple/list serialization, and the documented membership-revocation 404 response; no assertion about export protection was removed or weakened.

Final assigned command:

```text
uv run pytest tests/acceptance/test_exports.py -q
exit 0 — 13 passed, 2 existing dependency deprecation warnings in 4.14s.
```

Coverage includes actual guarded human resolution between capture/freeze; review after freeze; repeated mutation and durable retry/poll resume; real rule-engine rescore lineage; old ZIP bytes unchanged after rescore and adapter reopen; append-only SQLite guards; preparse zero-claim and untagged candidate-source reports; correct unfinished labels/hashes; blocked/final-report gates; tenant/user/CSRF/revocation/expiry/tamper checks; deliberate on-disk ZIP corruption; mixed revision rejection; bounded output failure; valid non-UUID idempotency and malformed JSON.

The fixtures explicitly label synthetic parser/tagger boundaries and reuse generated PDFs, actual local stores, actual guards/rules, and FastAPI HTTP calls. Race hooks perform real review/store transactions at the capture boundary; they do not mock snapshots, decisions or artifacts. Production accuracy or legal/regulatory correctness is not inferred from these fixtures.

## Exact verification commands

```text
uv run ruff check packages/proofops/application/exports.py packages/proofops/adapters/local/export_store.py apps/api/src/proofops_api/routers/exports.py tests/acceptance/test_exports.py
exit 0 — All checks passed!

uv run ruff format --check packages/proofops/application/exports.py packages/proofops/adapters/local/export_store.py apps/api/src/proofops_api/routers/exports.py tests/acceptance/test_exports.py
exit 0 — 4 files already formatted.

uv run mypy --follow-imports=silent packages/proofops/application/exports.py packages/proofops/adapters/local/export_store.py apps/api/src/proofops_api/routers/exports.py
exit 0 — Success: no issues found in 3 source files.

uv run pytest tests/acceptance/test_exports.py tests/acceptance/test_report.py tests/acceptance/test_reviews.py tests/acceptance/test_audit.py tests/acceptance/test_auth.py tests/integration/test_revision_coverage.py tests/integration/test_local_api_composition.py tests/contracts/test_package_contracts.py tests/unit/test_package_validation.py -q
exit 0 — 135 passed, 2 warnings in 9.88s.

uv build --package proofops --out-dir /tmp/proofops-task031-build
exit 0 — proofops wheel and source distribution built.

uv build --package proofops-api --out-dir /tmp/proofops-task031-build
exit 0 — proofops_api wheel and source distribution built.

uv run python scripts/validate_package.py
exit 0 — 705 checks passed, 0 failed (documentation/contracts only).
```

After the 135-test batch, the coordinator requested incremental capture size accounting before retaining records. This final adjustment and a dedicated capture-limit acceptance check passed the refreshed 13-test TASK-031 suite; lint, formatting, mypy and the proofops package build were rerun successfully. The broader batch was not repeated because the change is confined to the tested local capture ceiling.

The two known warnings concern FastAPI/Starlette's httpx integration and the deprecated anyio BlockingPortal alias. There were no application/test failures in the final verification batch. Security validation is the actual auth/export negative tests above; no new dependency was introduced.

## Not run / separate ownership

- Real model calls, AWS/S3/DynamoDB operations, deployment and live distributed scheduling: not_run (outside authorization).
- Human domain, legal, licensing, data-rights and private-customer gates: blocked/not_run; none were invented or approved by this work.
- Browser-to-composed-export end-to-end flow: not_run by this worker. ExportWorkspace browser checks and final browser integration are separate coordinator/UI-worker ownership; controlled UI-response tests are not represented here as actual backend export tests.
