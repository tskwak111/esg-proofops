# Reconciliation deployment readiness

Generated 2026-09-21T13:42:42.774185+00:00 on win32/amd64, Python 3.12.13.

This report is an inspection. Nothing was deployed, no AWS API or model was
called, no dependency was installed and no credential was read or printed.

## Gates

| Target | Ready | Passed | Blocked | Failed | Not run |
|---|---|---|---|---|---|
| `local_deployment` | no | 22 | 2 | 0 | 0 |
| `local_verification` | yes | 3 | 0 | 0 | 0 |
| `cloud_deployment` | no | 0 | 4 | 0 | 2 |

## Findings

| Check | Target | Status | Summary |
|---|---|---|---|
| `toolchain.ci_pins` | `local_deployment` | **passed** | toolchain versions were taken from the committed CI workflow |
| `platform.supported` | `local_deployment` | **passed** | host platform is inside the supported set |
| `toolchain.python` | `local_deployment` | **passed** | running interpreter satisfies the declared minimum |
| `toolchain.uv` | `local_deployment` | **passed** | uv is available; no comparable CI pin was found |
| `toolchain.node` | `local_deployment` | **blocked** | node major version differs from the CI pin |
| `toolchain.pnpm` | `local_deployment` | **blocked** | pnpm is not available on this host |
| `toolchain.java` | `local_verification` | **passed** | resolved Java major version matches the CI pin |
| `repository.required_paths` | `local_deployment` | **passed** | every required product, contract and configuration file is present |
| `repository.cloud_artifacts` | `cloud_deployment` | **blocked** | no container image or deployable stack entrypoint exists in this repository |
| `configuration.env_contract` | `local_deployment` | **passed** | every documented variable appears in the example with the documented default; 2 example variable(s) are absent from the specification table and need a documentation follow-up |
| `configuration.local_profile` | `local_deployment` | **passed** | the example profile is local, synthetic and loopback-only |
| `configuration.cloud_variables` | `cloud_deployment` | **blocked** | 14 of 15 cloud-required variables are unset, so no cloud target exists |
| `configuration.live_model_artifacts` | `cloud_deployment` | **blocked** | no approved model binding or consent profile exists, only examples |
| `configuration.real_env_files` | `local_deployment` | **passed** | real environment files were detected by existence only and never opened |
| `configuration.example_secrets` | `local_deployment` | **passed** | no credential-named variable carries a value in the committed example |
| `configuration.loopback_ports` | `local_deployment` | **passed** | both documented loopback ports can be bound on this host |
| `database.schema_initializes` | `local_deployment` | **passed** | a real store created the reconciliation schema at the declared version |
| `database.additive_only` | `local_deployment` | **passed** | reconciliation adds only reconciliation_-prefixed objects and changes none |
| `database.immutability` | `local_deployment` | **passed** | every immutable table refused a real update and delete attempt |
| `database.unknown_version_rejected` | `local_deployment` | **passed** | an unknown reconciliation schema version is refused instead of migrated |
| `backup.online_copy` | `local_deployment` | **passed** | an online database backup and artifact copy reproduced every row and byte |
| `restore.rehearsal` | `local_deployment` | **passed** | a restored case reread through get_case, revision and source_content matched the live original byte for byte |
| `rollback.data_independence` | `local_deployment` | **passed** | no existing table depends on a reconciliation table; disabling leaves data readable |
| `application.wiring` | `local_deployment` | **passed** | the real application assembles against a throwaway database and exposes its routes |
| `rollback.surface_is_bounded` | `local_deployment` | **passed** | the surface is one API router mount, one store wiring and one web feature |
| `verification.release_verifier_inputs` | `local_verification` | **passed** | every path and synthetic case the release verifier gates on is present |
| `verification.test_inventory` | `local_verification` | **passed** | every suite the release gate runs is present; execution is a separate command |
| `contract.route_parity` | `local_deployment` | **passed** | every served route is declared in the contract fragment and vice versa |
| `contract.examples_validate` | `local_deployment` | **passed** | every published example validates against the strict output schema |
| `frontend.build_inputs` | `local_deployment` | **passed** | the web workspace has its scripts, lockfile and installed dependencies |
| `cloud.local_only_boundary` | `cloud_deployment` | **blocked** | the product refuses staging and production by design; it is local-only today |
| `cloud.staging_gate_inputs` | `cloud_deployment` | **not_run** | the staging evidence gate has no bundle to verify and was not executed |
| `cloud.live_operations` | `cloud_deployment` | **not_run** | no AWS call, model invocation, deployment or DART collection was attempted |

## External inputs still required

- A container definition and an executable IaC entrypoint; the current product ships as a local process only.
- An approved config/model_bindings.json and config/consent_profile.json produced by the account owner.
- Install pnpm 10.0.0 on the deployment host; this tool never installs dependencies.
- Real account values for: AGENTCORE_RUNTIME_ARN, COGNITO_CLIENT_ID, COGNITO_DOMAIN, COGNITO_USER_POOL_ID, CURSOR_SECRET_ARN, DDB_AUDIT_TABLE, DDB_CORE_TABLE, KMS_KEY_ARN, OPENSEARCH_ENDPOINT, S3_ARTIFACT_BUCKET, S3_QUARANTINE_BUCKET, SESSION_SECRET_ARN, SQS_DLQ_URL, SQS_JOB_QUEUE_URL. None may be invented here.
- Real cloud adapters, an account, approved bindings and a deployment decision. No part of that exists in this repository.
- node 22 on the deployment host.
