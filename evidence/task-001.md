# TASK-001 — PDF upload and immutable document versions

## Contract before implementation

Existing v1 OpenAPI DTOs and paths remain authoritative. POST documents returns Document (201), POST versions returns UploadTicket (201), POST complete returns JobAccepted (202), and GET version returns DocumentVersion (200). Local completion performs real bounded PDF verification synchronously before returning a ready job; no production queue is claimed.

Coordinator owns composition/main and shared contracts. Approved development transport: POST `/local/uploads/{upload_id}/content`, multipart form with exact ticket fields and one `file`; authenticated editor, Origin + CSRF, bounded upload, ten-minute expiry, create-only receipt. Excluded from public v1 OpenAPI; router requires explicit local-synthetic composition to mount it. No custom multipart parser or production S3 claims.

Local persistence migration: additive `upload_records` and `upload_idempotency` tables, schema version 1, tenant composite primary keys, create-only version records; document latest pointer and accepted upload committed in one SQLite transaction. No existing tables/records changed or backfilled. Rollback disables router/writer and retains tables and immutable objects; downgrade must not modify source records. Files publish before the transaction; an interrupted publish may leave an unreferenced private original and retry adopts only identical bytes.

Local storage is explicitly synthetic SQLite + service-owned filesystem and retains object identity, SHA-256, company/document and period/rights metadata snapshots. `s3_version_id=null` locally; actual S3 version IDs and cloud security require a future approved live adapter and remain not_run.

## Verification

- RED: `uv run pytest tests/acceptance/test_upload.py -q` — exit 1, four failures due to missing `proofops.application.uploads`.

## Final behavior and review corrections

- `UploadService(database_path, object_root, registry)` stores real local upload state, validates company/approved same-tenant rights with TASK-045, and retains company/document-type/period/industry/rights metadata separately for each immutable version. Returned records are detached copies; client paths/object identifiers are never accepted.
- `build_documents_router(service, auth_store, allowed_origin=..., app_env="local", model_adapter="synthetic")` exposes document create/read, version initiation/read and completion. The coordinator mounted it in the actual composition, using the existing database path and its sibling `objects` directory, and closes the service at shutdown. The composed-app test verifies actual multipart upload and reconstruction after application restart.
- Ten-minute, authenticated, CSRF-protected local multipart POST tickets are single-use. Exact `ticket` + `file` fields, one file, one field, 512-byte text-field cap and actual stream byte cap apply before bytes reach the vault. Client-declared MIME/hash/length are insufficient: server SHA-256/length and TASK-038 bounded real PDF parsing must pass. The existing 100 MiB / 300-page development limits remain; source filenames are metadata only.
- Completion first persists a real `validation_job` in the upload record with a distinct stable job ID, tenant/upload/object/version binding, queued/running/ready/failed status, attempt counter and result/error checkpoint. The local runner executes PDF verification synchronously; restart retries resume the same durable job/input. JobAccepted references that real job and its actual version status URL. No synthetic analysis run is created.
- Source promotion is create-only. Accepted upload, immutable DocumentVersion, latest document pointer, audit event and idempotency result commit together. Separate SQLite connections race safely under `BEGIN IMMEDIATE`; latest is selected by fixed upload creation timestamp/version UUID, not completion order. Timestamp comparison parses UTC instants, including the zero-fraction versus fractional-second edge case.
- A same-upload completion retry returns the same version even with a fresh idempotency key. Same route/key with a different body is rejected; accepted bytes and prior versions are never replaced. Idempotency entries expire after 24 hours; accepted upload identity remains durable independently.
- Coordinator-approved local audit adaptation is scoped to the real document before any analysis run exists. `upload_audit` stores append-only hash-linked envelopes with real tenant/document/upload/version/job IDs, authenticated `actor_sub`, source SHA, before/after hashes and server timestamp/action/reason; it stores no filename/company name/PDF body. A real SQLite trigger failure proves atomic rollback and retry without duplicate audit entries.
- API response payloads validate against the existing OpenAPI Document/UploadTicket/JobAccepted/DocumentVersion schemas. Generated OpenAPI includes session-cookie security, role/idempotency metadata, required write headers and standard error envelopes; document reads/creates expose ETags. The local transport is excluded from public OpenAPI.

## Migration and compatibility addendum

Schema 1 now additionally creates `upload_metadata` (component schema version) and `upload_audit`, with database triggers preventing audit updates/deletes and version updates. Unknown component versions fail service construction; unknown record schema versions fail reads. These are additive local tables and do not migrate or alter coordinator-owned registry/rulepack/job/audit tables. Existing v1 API request/response shapes are preserved. Rollback disables the upload writer/router, keeps these tables and source files, and must not downgrade or rewrite an unknown schema.

The audited dependency addition, `python-multipart==0.0.32`, was reviewed, pinned, installed and locked by the coordinator; see `evidence/dependencies-task001.md`. This worker did not modify manifests, the lockfile, shared contracts, composition or Git history.

## Executed verification (final)

| Command | Actual result |
|---|---|
| `uv run pytest tests/acceptance/test_upload.py -q` | exit 0; **13 passed**, 2 upstream deprecation warnings; 1.69s |
| `uv run ruff check apps/api/src/proofops_api/routers/documents.py packages/proofops/application/uploads.py tests/acceptance/test_upload.py` | exit 0; All checks passed |
| `uv run ruff format --check apps/api/src/proofops_api/routers/documents.py packages/proofops/application/uploads.py tests/acceptance/test_upload.py` | exit 0; 3 files already formatted |
| `uv run mypy apps/api/src/proofops_api/routers/documents.py packages/proofops/application/uploads.py` | exit 0; no issues in 2 source files |
| `uv run pytest tests/acceptance/test_upload.py tests/acceptance/test_upload_security.py tests/acceptance/test_auth.py tests/acceptance/test_session_security.py tests/acceptance/test_registry.py tests/integration/test_local_api_composition.py tests/unit -q` | exit 0; **109 passed**, 2 upstream deprecation warnings; 4.34s |
| `uv run python scripts/verify_architecture.py` | exit 0; domain purity, DTO boundary, ports, fail-closed composition and fixed LLM-tag contract checks passed |
| `uv build --package proofops --out-dir /tmp/proofops-task001-build` | exit 0; source distribution and wheel built |
| `uv build --package proofops-api --out-dir /tmp/proofops-task001-build` | exit 0; source distribution and wheel built |

The two warnings are Starlette's existing httpx TestClient deprecation and AnyIO BlockingPortal alias deprecation. Tests exercise real PDF generation/parsing subprocesses, actual multipart form parsing, local file promotion and SQLite transactions; no mocked verifier/storage result is used. The focused suite covers unit/contract behavior, security rejection, same-process and separate-connection races, real storage tampering, audit transaction rollback, API roundtrip and app restart.

Additional RED records: HTTP implementation absent produced 2 failures/4 passes; durable job, schema gate and OpenAPI security additions produced 3 failures/8 passes; fractional-second ordering failed until comparisons used datetime instants; non-ASCII forged ticket failed with TypeError until bytes-based constant-time comparison; audit test failed before the actor/transaction audit implementation. These failures were fixed in implementation, without weakening acceptance assertions. The initial HTTP fixture used the discarded CSRF seed; it was corrected to use the token actually issued by the existing session store, preserving real authorization checks.

## Remaining gates and limits

- **not_run:** AWS S3 versioned object/presign and DynamoDB deployment, AWS mutation, live model calls, cloud recovery/E2E, customer PDF processing, rights/legal/data approvals and production service release. Local `object_version_id` is explicitly synthetic and `s3_version_id` is null; no AWS identity or approval is invented.
- **not_run:** browser UI E2E, since this task does not implement the upload UI. The complete HTTP-to-PDF-to-durable-version path and composed-app restart were exercised in-process through the actual ASGI app.
- This local adapter serializes SQLite writers and keeps up to the configured PDF byte limit in memory. Multiple local runners may redundantly verify the same immutable source, while only one accepted checkpoint/audit commits. Production queue leases, versioned cloud storage, background dispatch and orphan cleanup belong to the future approved runtime; local restart recovery currently resumes when completion is retried.
- No LLM grading/tagging, source-less present, unknown-to-absent conversion, rule changes or benchmark/production accuracy claims were introduced. No commit or push was performed.
