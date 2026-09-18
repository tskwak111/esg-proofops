# Local API composition contract

This wires the existing v1 company, runtime-options, preflight and rulepack
activation contracts without changing their public fields or response codes.
Only explicit local composition opens the existing LOCAL_DATABASE_PATH; cloud
composition still rejects local adapters before creating any local state.
Registry and rulepack tables must coexist, preserve prior data and support
reopening. Their component schema and rollback details remain in TASK-045/025
evidence. Rolling back code must preserve the SQLite file and immutable records.

MODEL_ALLOWED_PROCESSING_REGIONS is an additive server configuration variable:
comma-separated approved region identifiers, empty by default. Empty denies
processing readiness. AWS_REGION is never treated as consent or as the model
processing-region allowlist. Rollback may omit the new variable; it cannot
grant previously denied model access. No environment value is filled on behalf
of a human approver. Missing build attestation keeps preflight readiness false.

The initial composed-API integration test failed with company POST returning
404, establishing that standalone router tests alone did not prove app wiring.

Further fail-first checks reproduced active rule packs missing from RuntimeOptions
after successful HTTP activation and document POST returning 404. Composition now
uses the durable RulePack active reader for both option listing and run validation,
and mounts the upload router against the same local database. Local source files
live under `LOCAL_DATABASE_PATH`'s parent directory in `objects/`; no new storage
configuration or cloud identity is invented. App shutdown closes its registry and
upload connections.

Company idempotency now follows the existing tenant/route scope and 24-hour
lifetime, including a retry by another authenticated editor. The v1 stored key
shape stays readable: legacy actor-scoped entries are looked up by tenant/key and
expire from their immutable company creation timestamp. Conflicting legacy
duplicate resources fail closed. No data migration or deletion is needed.

Coordinator verification: 74 registry, RulePack foundation/HTTP and composed-API
checks pass. The integration opens two applications before writing, verifies
cross-instance document/company visibility and activation options, then closes
and reopens the database. Missing approved profiles remain inaccessible. This is
local API verification; product model, AWS, real OIDC and customer corpus tests
remain not_run.

Additional coordinator checks: 28 registry/upload/composition checks and 80
OIDC/auth/browser-security/composition checks pass. Unknown registry schema versions
are now rejected before loading state; a real failing regression established the
previous missing guard. The default OIDC route returns uncached 503 until explicitly
configured. Uvicorn access logging is disabled to avoid logging callback query codes.
