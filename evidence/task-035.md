# TASK-035 observability evidence

## Scope and design before implementation

The coordinator approved `packages/proofops/application/telemetry.py` as the single
shared sanitizer/sink, reused by the assigned API ASGI and worker operation hooks.
No new dependency, storage schema, public API contract or domain change is needed.
Main/composition remains coordinator-owned. Prior job/usage/audit files are not edited.

Only bounded enums, IDs/hashes from explicit server context, and non-negative
numeric counters survive. Untrusted event dictionaries cannot override server
identity; arbitrary messages, nested values, exception repr/tracebacks, auth
headers, URLs/query strings and payloads are never serialized. Opaque provider
request identifiers and tenant IDs are keyed hashes. Logs, metric observations
and trace observations are JSON lines sent to a real local logging handler.

Tests first cover collected secret/body absence, actual ASGI request lifecycle,
real worker operation wrapping, a subprocess logging configuration and trace
propagation, including malicious field values and exceptions. Uvicorn raw access
logging must be disabled and runtime/error handlers must use the safe formatter;
root wiring and cloud exporters remain separate integration gates.

## Implemented and reviewed

- Shared immutable server TraceContext validates UUIDs, nonzero W3C trace/span IDs
  and SHA256 values; event data cannot override it. Tenant/provider identifiers
  use a keyed SHA256 HMAC. No new dependencies or canonical audit/billing changes.
- Telemetry sanitizes before passing records to its private, non-propagating real
  logging handler. JSON log/trace observations retain allowed lifecycle IDs,
  attempt/fence, enum codes, model hashes, bounded tokens and duration. Metric
  observations allow only bounded operational counters with env/stage/error_code
  dimensions. Unknown/malformed/freeform/nested values are dropped, never coerced
  with str/repr. Invalid token counts remain null, not invented zero usage.
- ASGI middleware records status/duration, emits server request/trace headers,
  ignores incoming correlation headers and never reads/logs URLs, queries, auth,
  bodies or exceptions. Verified server routes may enrich the immutable context
  through dataclasses.replace after authorization. current_request_id() uses a
  ContextVar with token reset in a nested finally; 12 concurrent async/threadpool
  requests preserve unique header/body/log correlation.
- Worker hook validates tenant/run/job against the lease, preserves the exact
  operation payload, usage and original StageFailure, and emits only sanitized
  observations. Queue propagation contains exactly traceparent and run_id. The
  real local SQLite job repository supplies the tested lease, without mocking
  repository transitions or substituting model results.
- Runtime formatter never formats third-party record msg/args/extra/stack or
  exception text. Review found and regression-tested two real Python logging
  escape paths: handler-less critical access logs reach lastResort, and ordinary
  StreamHandler failures dump original records. Explicit NullHandler and shared
  quiet error handling close both paths, including captured subprocess stderr.

All content/keys in acceptance tests are explicitly synthetic. The API cost route
inside the acceptance fixture is a synthetic route used to exercise actual ASGI
middleware; its response is not evidence of cloud cost integration. The independent
local composition integration and existing cost acceptance tests are also run.

## Exact verification commands and results

RED runs before each corresponding implementation:

1. `uv run --no-sync pytest tests/acceptance/test_observability.py -q`
   — exit 2: missing proofops.application.telemetry during collection (initial
   seven acceptance tests); after first implementation: 7 passed.
2. Same command — exit 1: 4 failed, 8 passed (critical access logger leaked through
   lastResort; None request/trace/span identities were accepted); after guards:
   12 passed.
3. Same command — exit 1: 2 failed, 12 passed (operational metric observations and
   authorized context enrichment missing); after implementation: 14 passed.
4. Same command — exit 1: 1 failed, 14 passed (current_request_id missing); after
   ContextVar implementation: 15 passed.
5. Same command — exit 1: 1 failed, 15 passed (runtime stream failure printed
   original API key/body record); after shared quiet handler: 16 passed.

Final acceptance/security check:

```sh
uv run pytest tests/acceptance/test_observability.py -q
```

Exit 0: **16 passed**, 2 existing Starlette/httpx and anyio deprecation warnings.
Includes actual captured logging, ASGI success/failure, concurrent threadpool and
async requests, real leased worker callback, and three isolated subprocess checks.

```sh
uv run --no-sync ruff check packages/proofops/application/telemetry.py apps/api/src/proofops_api/telemetry.py apps/worker/src/proofops_worker/telemetry.py tests/acceptance/test_observability.py
uv run --no-sync ruff format --check packages/proofops/application/telemetry.py apps/api/src/proofops_api/telemetry.py apps/worker/src/proofops_worker/telemetry.py tests/acceptance/test_observability.py
uv run --no-sync mypy --follow-imports=silent packages/proofops/application/telemetry.py apps/api/src/proofops_api/telemetry.py apps/worker/src/proofops_worker/telemetry.py tests/acceptance/test_observability.py
```

All exit 0: all lint checks passed, 4 files formatted, no type issues in 4 files.
Earlier lint runs found import ordering, line length, lambda assignment and union
syntax errors, corrected with targeted edits and `ruff check --fix` / `ruff format`.
The first 3-source-file mypy run found numeric narrowing errors; corrected before
final type validation. No checks or tests were removed/weakened.

```sh
uv run --no-sync pytest tests/acceptance/test_cost.py tests/acceptance/test_jobs.py tests/acceptance/test_preflight.py tests/contracts tests/unit -q
uv run --no-sync pytest tests/integration/test_local_api_composition.py -q
uv run --no-sync python scripts/verify_architecture.py
uv run --no-sync python scripts/validate_package.py
```

All exit 0: **155 passed** regression/unit/contract tests; **1 passed** local API
composition integration (also rerun after ContextVar); architecture all checks
passed; **697/697** documentation/contract checks passed. Both pytest commands
report the same 2 existing dependency deprecation warnings. Package validation is
only documentation/contract checking, not application validation.

```sh
uv build --package proofops --out-dir /tmp/proofops-task035-build
uv build --package proofops-api --out-dir /tmp/proofops-task035-build
uv build --package proofops-worker --out-dir /tmp/proofops-task035-build
```

All exit 0: wheel and source distributions produced for each package. API build
rerun after the final ContextVar/runtime-handler changes. No repository package,
lockfile, shared contract or dependency edits were required.

## Composition handoff and remaining gates

Coordinator owns main/composition/auth changes, confirmed through Orca; worker
only edited the three assigned files, approved shared module, and this evidence.
API wiring is `app.add_middleware(TelemetryMiddleware, telemetry=emitter)` with
`Telemetry(service="api", env="local", stream=sys.stdout, hash_key=<32+ private bytes>)`.
The local composition may generate an ephemeral key without requiring a new env
secret; stable cross-process tenant correlation needs a managed stable key at the
operational integration gate. Never pass a request token as the hashing key.

Uvicorn must use **both** `access_log=False` and
`log_config=proofops_api.telemetry.logging_config(env="local")`. Existing runtime
handlers are disabled by that config, access logging uses NullHandler, and runtime
messages are reduced to structured code/level only. Do not add a raw StreamHandler
or prompt-capturing exporter afterward. Auth error envelopes should use
`current_request_id() or str(uuid4())`; root owns this central auth integration.

Use `observe_job(telemetry, lease, operation, context=worker_context(lease, propagated))`
as the consumer operation wrapper. Operation completion is not checkpoint commit:
lease fencing/publication still belongs to the repository/consumer. Attach model
hashes only from verified binding/call metadata using the immutable context; usage
ledger records remain separate from observability. Application call sites must
supply documented operational counters; this module does not invent measurements.

- CloudWatch/X-Ray/OTLP exporter ingestion, SLOs/alarms/dashboards, AgentCore prompt
  capture preflight, real AWS/model runs: **not_run** (outside authorization).
- Production-wide composition and browser E2E: **not_run in this worker scope**;
  coordinator integrates root entry points. Local ASGI/worker paths are executed.
- Human data/rights/legal gates and private customer processing: **blocked/not_run**.
- Existing log/trace observations are JSON lines, not a claim of exported cloud
  spans or production monitoring coverage. No source-content artifact viewer,
  audit storage, cost revisions, domain decisions, or prior revisions changed.
- No commit or push performed.

## Coordinator integration verification

The real local API now installs the middleware and safe Uvicorn configuration.
Auth error envelopes use the same server ContextVar request ID as headers/logs.
A coordinator regression first failed for an explicit HTTP 503 logged as `OK`;
the shared ASGI status observer now records generic `UNKNOWN` for error responses
without an exception, preserving status without reading potentially sensitive bodies.

`uv run --no-sync pytest -q tests/acceptance/test_observability.py tests/acceptance/test_parsing.py tests/integration/test_local_api_composition.py`
exited 0: **26 passed**, two existing dependency deprecation warnings.
Targeted Ruff checks passed. Mypy over the three telemetry modules, API main/auth,
parser, graph fusion and parser port exited 0 with no issues in **8 source files**.
The private HMAC key is ephemeral per local process; stable cross-process tenant
correlation and cloud exporters remain external operational integration work.
