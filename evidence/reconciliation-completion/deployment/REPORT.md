# Deployment readiness — executed evidence

Date: 2026-09-21. Host: Windows 11, `win32`/`amd64`, Python 3.12.13, Java 21.0.2.
Author: Developer B deployment lane (Claude Opus under Orca supervision).

**Final coordinator result:** `readiness-final/readiness.json` supersedes the
worker environment run below. Under Node 22.23.2 and pnpm 10, all 27 local checks
passed (24 deployment + 3 verification), with 4 cloud blockers and 2 cloud
operations not run. The initial environment result remains as history.
The coordinator added the omitted environment documentation, corrected the backup
inventory to include `parser-prepared`, required quiesced writers, distinguished
scratch rehearsal from actual restored-database verification, and added the
public recovery regression in `test_restore_roundtrip.py`. That test passed:
registration, review revision, claim/case/source replay, idempotency and tamper
rejection all use real persistence with explicit synthetic parser/model/reviewer
fixtures. Cleanup now also rejects a changed resolved target. Final integrated
results are in the parent `VERIFICATION.md` and PR CI.

This report records what was **executed**, with commands and outcomes. Nothing
here was deployed. No AWS API call, model invocation, DART collection, network
request, dependency installation, commit or push occurred. No real environment
file was opened and no credential value appears in any artifact produced here.

## Files delivered

| Path | Purpose |
|---|---|
| `scripts/check_reconciliation_readiness.py` | Offline readiness checker; 33 findings across three targets. |
| `tests/reconciliation/test_readiness.py` | 47 tests over the checker, including negative cases. |
| `docs/RECONCILIATION_DEPLOYMENT.md` | Install/run, backup, restore, rollback, and the cloud boundary. |
| `evidence/reconciliation-completion/deployment/readiness-run-1/` | The checker's own output for this host. |

No other file was created or modified. `evaluation/`, the reconciliation
source, the existing contracts and every other agent's files were left alone.

---

## 1. Readiness checker

```
uv run --no-sync python scripts/check_reconciliation_readiness.py \
  --output evidence/reconciliation-completion/deployment/readiness-run-1
```

Exit code **1**. Result: `{"total": 33, "passed": 25, "blocked": 6, "failed": 0, "not_run": 2}`.

| Target | Ready | Passed | Blocked | Failed | Not run |
|---|---|---|---|---|---|
| `local_deployment` | **no** | 22 | 2 | 0 | 0 |
| `local_verification` | **yes** | 3 | 0 | 0 | 0 |
| `cloud_deployment` | **no** | 0 | 4 | 0 | 2 |

Exit 1 is correct for this host: nothing failed, but two local prerequisites
are missing (below). Full findings: `readiness-run-1/readiness.json`; rendered
summary: `readiness-run-1/readiness.md`.

### Blocked on this host — `local_deployment`

| Check | Observed | External input required |
|---|---|---|
| `toolchain.pnpm` | `pnpm` is not on PATH (`not_on_path`). | Install pnpm 10.0.0, the version `.github/workflows/ci.yml` pins. |
| `toolchain.node` | Node **v25.4.0** present; CI pins major **22**. | Node 22 on the deployment host, or an explicit decision to verify on 25. |

Both are host provisioning, not code defects. The checker never installs a
dependency, so it reports and stops. Everything else the local product needs on
this host passed.

### Blocked / not run — `cloud_deployment`

| Check | Observed |
|---|---|
| `cloud.local_only_boundary` | Executed `build_composition` for all three environments: `local` accepted, `staging` **refused**, `production` **refused** (`AdapterRejectedError`). The product cannot run outside local. |
| `repository.cloud_artifacts` | None of `Dockerfile`, `apps/*/Dockerfile`, `docker-compose.yml`, `compose.yaml`, `infra/cdk/cdk.json`, `infra/cdk/bin/app.ts` exists. |
| `configuration.cloud_variables` | 14 of 15 cloud-required variables from `docs/17_ENV_CONFIG.md` are unset. Only `AWS_REGION` carried a value, from the shell. Names are listed; **no value is recorded**. |
| `configuration.live_model_artifacts` | `config/model_bindings.json` and `config/consent_profile.json` do not exist; only `.example` files do. |
| `cloud.staging_gate_inputs` (not_run) | `infra/cdk/staging_gate.py` exists; `evidence/staging/manifest.json` and `approval.json` do not. The gate was **not executed** — there is nothing to verify. |
| `cloud.live_operations` (not_run) | Declared and verified zero: AWS calls, model invocations, outbound network calls, dependency installations, writes outside the output and temp directories. |

**No cloud readiness is claimed.** `cloud_deployment` cannot become ready from
this tool's evidence by construction: four checks block it and the two `not_run`
checks are counted as unattempted, which by itself prevents readiness. The
checker's own tests assert both rules.

Per the user's decision relayed by the coordinator, this task is **deployment
preparation only**. No AWS deployment was developed, attempted or planned here.

---

## 2. What the checker actually executed (not asserted)

### Database, backup and restore — all passed

Performed in a private temporary directory, torn down afterwards:

- Built a real database through `LocalSQLiteRunStore` and
  `LocalReconciliationStore`. `reconciliation_schema` holds exactly version 1.
- `database.additive_only`: compared `sqlite_master` before and after. Fourteen
  `reconciliation_`-prefixed objects added (six tables and eight immutability
  triggers); nothing removed; no existing object altered.
- `database.immutability`: inserted a row into each of the four immutable
  tables and attempted a real `UPDATE` and `DELETE` on each. All eight refused.
- `database.unknown_version_rejected`: planted schema version 2 and reopened.
  Refused with `UNSUPPORTED_RECONCILIATION_SCHEMA`, HTTP 409 — not migrated.
- **Populated the store through the product's own write path.** One published
  fixture bundle (`c1-difference-no-explanation`, via
  `evaluation.reconciliation_fixtures.build_case`) went through the store's
  `_validate_bundle`, `_import_artifacts` and `_append`: real bundle
  validation, a real managed artifact copy with locator and hash proof for two
  sources, and a real revision 1 with its payload digest. The database is not
  an empty schema at backup time.
- `backup.online_copy`: took an online `sqlite3.Connection.backup()` with a
  writer connection still open and copied the artifact tree. Row counts matched
  across all four tables (2 cases, 2 revisions, 3 sources, 1 idempotency row),
  `PRAGMA integrity_check` returned `ok`, the schema version row survived, and
  every artifact digest matched.
- `restore.rehearsal`: restored the backup to a third location, reopened it
  through the real store, and compared it **against the live original** —
  not against the backup it came from. Both copies were read through the
  product's authorised read paths `get_case`, `revision` and `source_content`.
  Result: revision 1 with matching `snapshot_sha256`
  `a20fdf58…94e9b9`, sources `fs-scope` and `sr-scope`, no difference in the
  product reads, the immutable table rows or the artifact digests.

Two negative tests keep this honest. A tampered artifact byte in the backup
makes `source_content` re-hash and reject with the product's own
`SOURCE_UNVERIFIED` (409), and the check reports `failed` rather than crashing.
An earlier draft compared the restore against its own backup and read only
marker SQL; both made the check vacuous and were rewritten after coordinator
review.

`register_case` additionally anchors a draft to a verified run built by the
upload/parse/extract/tag pipeline. Public registration is tested in
`tests/reconciliation/test_product_store.py` with explicit synthetic parser/model
adapters, and public recovery is covered by `test_restore_roundtrip.py`.
The checker itself does not execute public registration.

### Temporary workspace ownership

The rehearsal runs inside a context-managed directory created with
`tempfile.mkdtemp(prefix="reconciliation-readiness-")`. Before removal the path
is resolved and re-checked: it must be a real directory, not a symlink, an
immediate child of the system temporary root, and carry that prefix. Anything
else is left in place with a warning on stderr rather than deleted. Two tests
cover the refusal paths (wrong parent, wrong prefix) and assert a planted file
survives.

### Gate truth

A target is `ready` only when every check scoped to it ran and passed.
`not_run` is not evidence: a target whose checks all declined to run reports
`ready: false` and lists them under `unattempted_checks`. Tests cover the
not_run-only and mixed cases. Finding details carry the exception **type** only
— never the message — so a value can never leak through an error path.

### Application wiring — passed

Assembled the real FastAPI application via `create_app()` against a throwaway
database. `LOCAL_DATABASE_PATH` is redirected **before** the module is imported,
so the repository's `.local/state.sqlite3` is never opened; a test verifies its
mtime is unchanged, and the process environment is restored afterwards. The
served OpenAPI document carries 59 routes including both health endpoints and
the reconciliation routes.

### Contract parity — passed

The reconciliation router serves exactly the seven operations declared in
`contracts/reconciliation/product.openapi.yaml`; neither set has an extra entry.
All eight published examples validate against the strict output schema.

### Rollback surface — passed

One `build_reconciliation_router(...)` mount in `main.py`, one
`LocalReconciliationStore` wiring in `composition.py`, one web feature
directory. No pre-existing table references a `reconciliation_` table, so
disabling the surface leaves the existing G/P/M data readable.

### Configuration — passed

`.env.example` matches every variable and non-empty default in the
`docs/17_ENV_CONFIG.md` table; the profile is `local`/`synthetic` with loopback
origins only; no credential-named variable carries a value. Both documented
loopback ports bound successfully.

Advisory (non-blocking, not my file): `DART_API_KEY` and
`MODEL_ALLOWED_PROCESSING_REGIONS` appear in `.env.example` but are absent from
the `docs/17_ENV_CONFIG.md` table. The checker reports this in the finding
detail; the documentation owner should add the two rows.

---

## 3. Live API smoke test

Started the real application on loopback against a scratch database in the
system temp directory, then stopped it:

```
LOCAL_DATABASE_PATH=<scratch>/state.sqlite3 APP_ENV=local \
uv run --no-sync python -m uvicorn proofops_api.main:app --host 127.0.0.1 --port 8123
```

| Request | Response |
|---|---|
| `GET /v1/health/live` | `200 {"status":"ok","version":"0.0.0","checks":["baseline"]}` |
| `GET /v1/health/ready` | `200 {"status":"not_ready","version":"0.0.0","checks":["baseline:cloud-not-wired"]}` |
| `GET /v1/reconciliation/cases/{uuid}` with no session | `401 {"error":{"code":"AUTH_REQUIRED",...}}` |

The application's own readiness endpoint reports `cloud-not-wired`. The
reconciliation surface refuses an unauthenticated request. The repository
database was not touched; the server was stopped and port 8123 released.

The documented backup one-liner in `docs/RECONCILIATION_DEPLOYMENT.md` was run
verbatim against a scratch database and the restored copy returned the expected
row.

---

## 4. Tests and gates

| Command | Result |
|---|---|
| `pytest tests/reconciliation/test_readiness.py -q` | **47 passed** |
| `pytest tests/reconciliation -q` | **620 passed** (whole directory, including this lane's 47 and other lanes' concurrent additions) |
| `ruff check` on the two new files | passed |
| `ruff format --check` on the two new files | passed |
| `mypy scripts/check_reconciliation_readiness.py` | passed, no issues |
| `python scripts/verify_reconciliation.py --output .local/release-verify-readiness --timeout-seconds 900` | **14 of 15 gates passed; `ruff_format` failed** (run before the final fixes; not rerun, per coordinator) |

### The one release-gate failure is not in this lane

`ruff_format` reports three files:

- `evaluation/reconciliation_benchmark.py` — a new, untracked file belonging to
  the evaluation lane.
- `apps/api/src/proofops_api/routers/reconciliation.py` and
  `tests/reconciliation/test_product_http.py` — both **unmodified relative to
  HEAD** per `git status`, but the working-tree copies contain a block written
  with bare `LF` inside an otherwise `CRLF` file, so `ruff format` wants to
  normalise them.

None of the three is a file this lane owns, and neither of my two files appears
in the list. I did not touch them: fixing another agent's file, or rewriting
line endings across the shared tree, is outside this task's ownership. The
owning lanes should run `ruff format` on their own paths before publication.

The new tests live in `tests/reconciliation`, so the release verifier's
`pytest` gate covers them. That verifier run predates the final round of
coordinator-requested fixes (real fixture import, product read-back, workspace
containment, gate truth, sanitised errors); at the coordinator's instruction it
was **not** rerun here — the master will run it once after integration. The
focused suites, lint, format and mypy in the table above were all rerun after
those fixes.

Not run here, by scope: the real Java parser regression
(`tests/acceptance/test_parsing.py`), the web typecheck/build (pnpm is not
installed on this host), and the browser flow. The checker reports the first two
as inputs rather than executing them, and records `verifier_executed_here: false`.

---

## 5. External inputs still required

Verbatim from `readiness.json` → `external_inputs_required`:

1. Install pnpm 10.0.0 on the deployment host.
2. Node 22 on the deployment host.
3. Real account values for `AGENTCORE_RUNTIME_ARN`, `COGNITO_CLIENT_ID`,
   `COGNITO_DOMAIN`, `COGNITO_USER_POOL_ID`, `CURSOR_SECRET_ARN`,
   `DDB_AUDIT_TABLE`, `DDB_CORE_TABLE`, `KMS_KEY_ARN`, `OPENSEARCH_ENDPOINT`,
   `S3_ARTIFACT_BUCKET`, `S3_QUARANTINE_BUCKET`, `SESSION_SECRET_ARN`,
   `SQS_DLQ_URL`, `SQS_JOB_QUEUE_URL`. None may be invented.
4. An approved `config/model_bindings.json` and `config/consent_profile.json`
   produced by the account owner.
5. Real cloud adapters, an account, approved bindings and a deployment decision.
6. A container definition and an executable IaC entrypoint.

Beyond the checker's scope, and unchanged by this work: document rights
approval, the staging evidence bundle and detached approval described in
`docs/DEPLOYMENT_EVIDENCE.md`, C3 thresholds and account mapping, the open
domain decisions, real policy approval, and held-out accuracy evaluation. Those
are human decisions, not deployment steps, and none was made here.

---

## 6. Limits of this evidence

- Local evidence from one Windows host. Linux and Apple Silicon macOS are
  supported by the checker's platform logic but were not executed here. Intel
  macOS is reported `blocked` as out of scope, matching the delivery decision.
- The backup/restore rehearsal uses a real store and real SQLite, but a
  synthetic case row. It proves the procedure and the schema guards, not the
  durability of any particular production dataset.
- A `passed` local gate means the inspected prerequisite holds on the inspected
  host. It is not a deployment approval, not a performance measurement, and not
  a statement about any cloud environment.
- The checker does not run the test suites it reports on. Run
  `scripts/verify_reconciliation.py` separately for the release gate.
