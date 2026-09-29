# C1–C4 reconciliation deployment, backup, restore and rollback

Scope: the **local** C1–C4 review product — a FastAPI process, one SQLite
database, three on-disk artifact trees and a Vite/React bundle. This is the whole
deployable unit today. There is no container image, no cloud stack entrypoint
and no account wiring in this repository, so nothing here describes or claims a
cloud deployment. Operating instructions for the feature itself stay in
[`RECONCILIATION_PRODUCT.md`](RECONCILIATION_PRODUCT.md); the integration
boundary stays in [`RECONCILIATION_HANDOFF.md`](RECONCILIATION_HANDOFF.md); the
separate, unfinished AWS staging evidence gate stays in
[`DEPLOYMENT_EVIDENCE.md`](DEPLOYMENT_EVIDENCE.md).

---

## 1. Readiness check

```powershell
uv run --no-sync python scripts/check_reconciliation_readiness.py --output .local/readiness-1
```

The checker **inspects only**. It performs no network call, no AWS API call, no
model invocation and no dependency installation. It never opens `.env`,
`.env.dart.local` or any other real environment file, and it never prints a
value whose variable name looks like a credential. It writes `readiness.json`
and `readiness.md` into a **new** output directory; an existing path is
rejected so a previous result is never overwritten.

Each finding carries a `status` and a `target`:

| Status | Meaning |
|---|---|
| `passed` | An executed check confirmed the condition. |
| `blocked` | A real prerequisite is missing and must come from outside this repository. `external_input` names it. |
| `failed` | The check ran and found a defect in the tree. |
| `not_run` | Out of this tool's authority — cloud probes, live models, real approvals. Never promoted to a pass. |

A target is `ready` only when **every** check scoped to it ran and passed. An
unattempted check is not evidence, so a target whose checks are all `not_run`
is never ready; `unattempted_checks` lists them.

| Target | Meaning |
|---|---|
| `local_deployment` | Running the local product on this host. |
| `local_verification` | Running the existing release gate and the real Java parser regression. |
| `cloud_deployment` | Reported separately and **never** becomes ready from this tool's evidence. |

Exit code `0` means `local_deployment` and `local_verification` both hold and
nothing failed. Exit `1` means something blocks a local target or a check
failed. Exit `2` means the output directory already exists. A zero exit is not
a deployment approval and says nothing about any cloud environment.

### What it actually executes

- Resolves the host platform. Windows, Linux and Apple Silicon macOS pass;
  Intel macOS is reported `blocked` because it is outside the delivery scope.
- Probes `uv`, `node`, `pnpm` and Java with `--version`, comparing each major
  version against the pins read from `.github/workflows/ci.yml`. Nothing is
  installed and no version is invented in the checker.
- Confirms every product, contract, lockfile and specification path exists.
- Cross-checks `.env.example` against the variable table in
  `docs/17_ENV_CONFIG.md`: missing variables, mismatched defaults, values on
  credential-named variables, non-loopback origins and unset cloud variables.
- Bind-tests the documented loopback ports. No outbound connection is opened.
- Builds a **real** reconciliation database in a private temporary directory,
  imports one published fixture bundle through the store's own write path, then
  backs it up, restores it and compares the restoration against the live
  original through the product's own read API (§3). The temporary directory is
  resolved and re-checked before removal; anything that is not the exact
  directory this tool created under the system temporary root is left in place.
- Assembles the **real** FastAPI application against a throwaway database —
  the database path is redirected before the module is imported, so the
  repository's own `.local` state is never opened — and confirms the served
  OpenAPI document exposes the health and reconciliation routes.
- Compares the routes the reconciliation router serves with
  `contracts/reconciliation/product.openapi.yaml`, and validates all eight
  published examples against the strict output schema.
- Calls `build_composition` for `local`, `staging` and `production` and
  requires the two non-local environments to be refused (§5).

---

## 2. Install and run the local product

Prerequisites, from the CI pins: Python 3.12, `uv`, Node 22, pnpm 10.0.0, and
Java 21 for the real parser regression. Install them on the host; the readiness
checker reports what is missing but never installs anything.

Apple Silicon macOS setup is in
[`RECONCILIATION_PRODUCT.md`](RECONCILIATION_PRODUCT.md). In bash/zsh use
`export PYTHONUTF8=1`; the `uv` and `pnpm` commands below are otherwise identical.
Run the API and web server in separate terminals.

```powershell
uv sync --locked
pnpm install --frozen-lockfile
$env:PYTHONUTF8 = '1'
uv run --no-sync python -m uvicorn proofops_api.main:app --host 127.0.0.1 --port 8000
pnpm --filter proofops-web build      # or: pnpm --filter proofops-web dev
```

`APP_ENV` stays `local` and `MODEL_ADAPTER` stays `synthetic`. The Vite dev
server proxies `/v1`, `/auth`, `/local/uploads` and `/local/sources` to
`API_PUBLIC_BASE_URL`. `$env:PYTHONUTF8 = '1'` is required on Windows for the
Korean fixtures.

Health endpoints, verified against a running process on a scratch database:

| Request | Response |
|---|---|
| `GET /v1/health/live` | `200 {"status":"ok","version":"0.0.0","checks":["baseline"]}` |
| `GET /v1/health/ready` | `200 {"status":"not_ready","version":"0.0.0","checks":["baseline:cloud-not-wired"]}` |
| `GET /v1/reconciliation/cases/{id}` without a session | `401 AUTH_REQUIRED` |

`/v1/health/ready` reports `not_ready` by construction: the application itself
declares that cloud wiring does not exist. Do not read a 200 there as a
readiness signal, and do not wire it to a load balancer as one.

---

## 3. Backup and restore

### What to back up

All durable local state sits beside the database path:

| Path | Contents |
|---|---|
| `LOCAL_DATABASE_PATH` (default `.local/state.sqlite3`) | runs, claims, tags, decisions, exports, audit and the `reconciliation_*` tables |
| `<database parent>/objects` | uploaded original documents |
| `<database parent>/parser-prepared` | parser manifests, prepared sources and verification artifacts required to replay existing claims |
| `<database parent>/reconciliation-artifacts` | immutable reconciliation source copies |

All four are one unit. A database without its artifact trees cannot serve a
source download or re-verify an artifact hash.
Retain the matching release commit, lockfiles and pinned runtime/profile configuration
as well: verification receipts may require the original verifier code hash.

### Procedure

Stop the API and all workers before starting, and keep writers stopped until
all copies finish. SQLite's online backup API snapshots the database, but does
not atomically snapshot the separate artifact trees. The database uses SQLite's
rollback journal (`journal_mode=delete`), not WAL. Use a new backup directory:

```powershell
$src = '.local/state.sqlite3'
$dst = '.local/backup-2026-09-21/state.sqlite3'
New-Item -ItemType Directory (Split-Path $dst) -ErrorAction Stop | Out-Null
uv run --no-sync python -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $src $dst
Copy-Item -Recurse .local/objects .local/backup-2026-09-21/objects
Copy-Item -Recurse .local/parser-prepared .local/backup-2026-09-21/parser-prepared
Copy-Item -Recurse .local/reconciliation-artifacts .local/backup-2026-09-21/reconciliation-artifacts
```

For macOS bash/zsh, with all writers stopped:

```bash
mkdir .local/backup-2026-09-21 &&
uv run --no-sync python -c 'import sqlite3; s=sqlite3.connect(".local/state.sqlite3"); d=sqlite3.connect(".local/backup-2026-09-21/state.sqlite3"); s.backup(d); d.close(); s.close()' &&
cp -R .local/objects .local/parser-prepared .local/reconciliation-artifacts .local/backup-2026-09-21/
```

Check every command succeeds before restarting writers. An artifact directory may
be absent only if that pipeline stage has never produced artifacts; record that
explicitly rather than ignoring a copy failure. Do not copy the database file hot
with `Copy-Item` or `cp` while a writer is active.

### Restore

Restore to a **new** directory, never over a live one, then repoint
`LOCAL_DATABASE_PATH` at it and restart the API:

```powershell
Copy-Item -Recurse .local/backup-2026-09-21 .local/restored-1
$env:LOCAL_DATABASE_PATH = '.local/restored-1/state.sqlite3'
uv run --no-sync python -m uvicorn proofops_api.main:app --host 127.0.0.1 --port 8000
```

Opening the restored database through the real store re-runs the schema guard:
a database whose `reconciliation_schema` version is not the version this code
knows is refused with `UNSUPPORTED_RECONCILIATION_SCHEMA` (HTTP 409) instead of
being migrated in place. Verify the restore before pointing users at it:

```bash
# macOS: first verify this destination does not exist
test ! -e .local/restored-1 && cp -R .local/backup-2026-09-21 .local/restored-1
export LOCAL_DATABASE_PATH=.local/restored-1/state.sqlite3
uv run --no-sync python -m uvicorn proofops_api.main:app --host 127.0.0.1 --port 8000
```

Using an authorized local session, open saved cases and both current and historical
revisions, download their sources, and replay an existing claim from the restored
parser artifacts. Compare IDs, revisions and hashes with the pre-backup record.
`check_reconciliation_readiness.py` always uses its own scratch database: rerunning
it checks the host and rehearsal, **not this particular restored database**.

### What the checker proves about this procedure

`backup.online_copy` and `restore.rehearsal` are not assertions about the
documented steps; they execute them. The checker creates a real database
through `LocalSQLiteRunStore` and `LocalReconciliationStore`, then imports one
published fixture bundle through the store's own `_validate_bundle`,
`_import_artifacts` and `_append` — real bundle validation, a real managed
artifact copy with locator and hash proof, and a real revision 1 with its
payload digest. It takes an online backup with a writer connection still open,
copies the artifact tree, restores that backup to a third location and reopens
it through the real store.

The comparison reads **both** copies through the product's own authorised read
paths — `get_case`, `revision` and `source_content` — and compares the restored
copy **against the live original**, not against the backup the restore came
from, so a corrupted backup cannot verify itself. `source_content` re-hashes
every managed source on read, so a tampered byte surfaces as the product's own
`SOURCE_UNVERIFIED` (409) and the check reports `failed`. Row sets, artifact
digests, `PRAGMA integrity_check` and the schema version row must all agree.

The checker seeds a synthetic case with private storage helpers; it does not
execute public `register_case` or the full verified-claim pipeline.
`tests/reconciliation/test_restore_roundtrip.py` separately exercises public
registration and a review revision, snapshots the databases and all artifact
trees with writers quiesced, and reopens the restored claim/case/revisions/sources.
It also checks idempotency and source tamper rejection while forbidding reads of
the original artifact tree. Its parser, model and reviewer are explicit synthetic
fixtures; this is not live-model, Java-parser or human-approval evidence.

### Retention

Keep the database and all artifact trees together, treat each backup directory as immutable, and
name a new directory per run. Existing reconciliation cases, revisions, sources
and idempotency records are protected by SQLite triggers that abort any
`UPDATE` or `DELETE`; the checker verifies each trigger by attempting both.

---

## 4. Rollback

Rolling back means disconnecting the reconciliation surface while preserving
every record it already wrote. It is not a data deletion and not a migration.

1. **Remove the API surface.** Delete the single
   `app.include_router(build_reconciliation_router(...))` call and its import in
   `apps/api/src/proofops_api/main.py`. The checker verifies there is exactly
   one such mount.
2. **Remove the store wiring.** Drop the `reconciliation=LocalReconciliationStore(...)`
   entry and its field in `apps/api/src/proofops_api/composition.py`.
3. **Remove the web surface.** Drop the `features/reconciliation` route from
   `apps/web/src/App.tsx`; the feature lives entirely under
   `apps/web/src/features/reconciliation`.
4. **Leave the data alone.** Do not drop a `reconciliation_*` table and do not
   delete `reconciliation-artifacts`. The existing G/P/M records do not depend
   on them.
5. **Rebuild and restart.** `pnpm --filter proofops-web build`, then restart the
   API. Re-run the readiness checker into a new output directory.

Re-enabling is the reverse: restore the three edits and restart. The stored
cases reopen at schema version 1 with their revisions intact.

### Why step 4 is safe

`database.additive_only` records the `sqlite_master` contents before and after
the reconciliation store initialises: enabling the feature adds only
`reconciliation_`-prefixed objects, removes nothing and alters no existing
object. `rollback.data_independence` scans the schema SQL and confirms no
pre-existing table references a reconciliation table. Nothing outside the
feature reads its tables, so removing the API and web surface leaves the rest of
the product working and the reconciliation records readable by a later rebuild.

### What rollback does not cover

Reverting to an earlier application version whose `reconciliation_schema`
version differs is **refused**, not migrated. Keep the code version that matches
the stored schema version, or restore a backup taken under that version.

---

## 5. Cloud deployment is out of scope, and the code says so

This is not a caveat added to the prose; it is what the checker measured.

- `build_composition(app_env="staging")` and `build_composition(app_env="production")`
  raise `AdapterRejectedError`. Only `local` builds. The product refuses to run
  outside local until real adapters exist.
- No `Dockerfile`, `docker-compose.yml`, `infra/cdk/cdk.json` or CDK app
  entrypoint exists. `infra/cdk/lib` holds template-building functions that are
  typechecked in CI; they are not a deployable stack, and CI never synthesises
  or deploys them.
- Every cloud-required variable in `docs/17_ENV_CONFIG.md` is unset. The
  checker lists their **names** and never their values.
- `config/model_bindings.json` and `config/consent_profile.json` do not exist;
  only `.example` files do. No approved binding, consent profile or rights
  approval exists in this repository.
- `infra/cdk/staging_gate.py` has no evidence bundle to verify, so it was not
  executed. Its exit 0 would in any case mean "the supplied evidence is
  complete", never "deployment is authorised".

`/v1/health/ready` returning `baseline:cloud-not-wired` is the same statement
from inside the running application.

### External inputs required before any cloud claim

None of these can be produced here, and none may be invented:

1. A real AWS account, region and the cloud variable values listed in
   `docs/17_ENV_CONFIG.md` — bucket names, table names, queue URLs, KMS key
   ARN, OpenSearch endpoint, Cognito identifiers, secret ARNs, AgentCore
   runtime ARN.
2. An approved `config/model_bindings.json` and `config/consent_profile.json`,
   with a real model identifier and processing-region consent.
3. Real cloud adapters for storage, queue, search and models, which do not
   exist in this repository.
4. A container definition and an executable IaC entrypoint.
5. Document rights approval and a human deployment decision.
6. The staging evidence bundle and detached approval described in
   `DEPLOYMENT_EVIDENCE.md`, produced by whoever holds the account.

Items that remain open regardless of infrastructure: C3 thresholds and account
mapping, the open domain decisions, real policy approval and held-out accuracy
evaluation. Those are human decisions, not deployment steps.

---

## 6. Relationship to the existing gates

| Command | What it covers |
|---|---|
| `scripts/check_reconciliation_readiness.py` | Host, configuration, database, backup/restore, rollback surface, application wiring. Runs no test suite. |
| `scripts/verify_reconciliation.py` | The release gate: lint, format, mypy, architecture, the reconciliation and acceptance suites, and the eight synthetic CLI cases. |
| `pytest tests/acceptance/test_parsing.py tests/integration/test_local_tag_runner.py` | The real Java parser and local tagging regression. |
| `pnpm --filter proofops-web typecheck && pnpm --filter proofops-web build` | The web bundle. |
| `infra/cdk/staging_gate.py` | Offline verification of a supplied AWS staging evidence bundle. Not part of local deployment. |

The readiness checker does not replace any of them. It reports whether the
release gate's inputs are present (`verification.release_verifier_inputs`,
`verification.test_inventory`) and records `verifier_executed_here: false`.
Run the gate itself separately.
