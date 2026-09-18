# Local parser executor integration — TASK-003/028/035

## Scope and additive storage contract

Local execution uses explicit tenant/run/once, real OpenDataLoader PDF 2.5.7 and
pdfplumber subprocesses with operator-supplied Java 21. Product model and AWS calls
are outside this executor. Approval fixtures are explicitly synthetic.

Before the final storage validation change, the contract is: the existing
`job_records` schema and transaction remain unchanged; a checkpoint with
`schema=local_parser_checkpoint_v1` is accepted only for a leased parse job with
matching input hash, a same-run pending extract successor, completed parse stage,
pending downstream stage, and integer nonnegative coverage. Page totals,
unprocessed pages and full-scope flag must match the immutable run snapshot;
processed plus unreadable accounts for every selected page, while all downstream
counts remain zero and `complete=false`. In the same existing fence transaction,
commit stores checkpoint bytes, enqueues extract and sets `current_stage=extract`,
`coverage`, and `parse_job` (the original message). It never completes the run.
Other checkpoint payloads and generic stages retain their accepted behavior.

No DDL or API schema migration is required: this is an additive internal JSON
payload contract on existing schema version 1. Rollback retains snapshots,
checkpoint/artifact bytes and job records; older readers ignore the added metadata,
but cannot consume the new local parser envelope until the matching reader is
restored. Never delete or rewrite parse revisions to roll back. Prepared filesystem
artifacts are private storage: publication is only the fence-committed checkpoint
pointer, not existence of a directory. Readers do not discover tenants or scan
artifact folders.

## Implementation and verification

Final command results are recorded below after verification.

`ParserProfile.config_snapshot()` contains every executable profile field except
`parse_manifest_id` and `physical_pages`; `config_hash()` uses the existing domain
canonical hash. Root's RunService freezes that actual configuration and hash.
The parser manifest still retains `parser_profile` and its exact invocation hash,
including selected pages and manifest identity, plus additive stable config fields.
No caller can provide only an arbitrary hash as executable configuration.

The runner derives its manifest UUID from run UUID plus the entire frozen input
hash. It verifies uploaded document metadata, document/object identity and original
bytes; consumes only the explicit run's pending parse outbox event; and reuses
`consume_job`, `observe_job`, lease/fence/retry/checkpoint and usage handling.
A finite lease covers the adapter's bounded Java/PDF/parser timeouts. Each local
attempt records zero model calls and whether parsing executed or a prepared
artifact was reused. Existing retry/cancel APIs retain ownership of retries.

`proofops.adapters.local.run_artifacts.load_run_graph(store, uploads, parser,
*, tenant_id, run_id)` is the shared reader for worker/API consumers. It follows
only the committed `parse_job` checkpoint pointer, validates the checkpoint hash,
input identity and manifest SHA, verifies every manifest artifact, reconstructs
validated native candidates, conservatively fuses the graph, and compares the
projection and complete quality envelope. It retains table coordinates, raw
candidates, parser families, conflicts, unlocated/unreadable issues and vision
`not_run`; it never replaces the rich graph with the fixed v1 projection.
Loader verification also checks parser run metadata, installed JAR hash and
parser versions. It does not overwrite an existing parse manifest.

Command shape (requires an existing explicitly approved local run):

```sh
LOCAL_DATABASE_PATH=/path/to/state.sqlite3 \
LOCAL_PARSER_PROFILE_PATH=/path/to/parser-config.json \
uv run --no-sync python -m proofops_worker.main \
  --tenant-id <tenant-uuid> --run-id <run-uuid> --once
```

The config file is exactly the full `ParserProfile.config_snapshot()` JSON.
Java's path is operator supplied; product code has no machine-specific fallback.
Objects are the existing database sibling `objects`, and private preparation is
sibling `parser-prepared`. CLI requires all three explicit arguments, uses the
existing safe runtime formatter, suppresses exception payloads and reports only
a finite delivery status. The one-line telemetry normalization makes internal
`parse` appear as allowlisted `PARSE`; unknown stages still pass through the shared
sanitizer. Registry/upload resources close at command exit.

## Test-first failures actually observed

- Initial `uv run --no-sync pytest tests/integration/test_local_parser_runner.py -q`:
  **3 failed**, specifically missing stable config hashing and verified reload.
- Atomic transition test initially failed with actual `current_stage='parse'`
  where a committed parse plus pending extract required `extract`.
- CLI guard test initially failed because the baseline accepted `--once` without
  tenant/run and exited successfully.
- Rehashed quality-tampering test initially failed because dropping
  `table_vision_not_run` did not raise; reload now recomputes and compares all issues.
- Actual parser telemetry assertion initially observed `UNKNOWN` rather than
  `PARSE`, corrected by the approved stage normalization.
- Unprocessed-selected-page test initially failed because a completed parse
  checkpoint could leave the selected pages unprocessed; commit now checks the
  frozen snapshot's page selection inside its existing transaction.

The full-PDF synthetic fixture repeats text at the top of each page.
OpenDataLoader classifies that text as headers and omits it; the test now checks
the actually extracted table value and explicitly unreadable pages 1 and 3.
This is observed parser behavior, not evidence absence or a full accuracy claim.
The subprocess CLI fixture dates synthetic approvals from its actual UTC clock;
future-dated approval fixtures correctly failed preflight before that fixture fix.

## Executed checks

- `uv run --no-sync pytest tests/integration/test_local_parser_runner.py tests/acceptance/test_jobs.py -q`:
  **43 passed**, including 21 local runner checks. Two existing FastAPI/Starlette
  dependency deprecation warnings; no test was disabled or removed.
- `uv run --no-sync pytest tests/unit tests/contracts tests/integration/test_run_lifecycle.py tests/integration/test_local_api_composition.py tests/acceptance/test_upload.py tests/acceptance/test_cost.py -q`:
  **119 passed** with those same two warnings.
- `uv run --no-sync pytest tests/security -q`: **9 passed**.
- Targeted `uv run --no-sync ruff check` and `ruff format --check` on the eight
  changed source files plus the integration test: **passed**.
- `uv run --no-sync mypy` on the eight changed source files: **success, no issues**.
- `uv run --no-sync python scripts/verify_architecture.py`: **all checks passed**.
- `uv run --no-sync python scripts/validate_package.py`: **697/697 passed**,
  documentation/contracts only, not application tests.
- `uv build --package proofops-worker --offline --out-dir /tmp/proofops-local-parser-build`
  and matching `--package proofops`: **wheel and source distribution built**.
  Build requirements came from the existing cache; no dependency or lock changes.

The CLI integration actually uploads the generated PDF, HTTP-creates a run using
explicit synthetic approvals, launches `python -m proofops_worker.main` in a
separate process, reopens and repeats it, compares checkpoint/manifest/artifact
hashes and loads the rich graph. Crash-before-checkpoint replay forbids another
parse invocation. A separate test lets a new worker commit before the expired
original returns, then proves the old worker cannot replace its checkpoint.
Cancellation before/during execution, wrong tenant, source/config hash mismatch,
corrupt artifacts, lost quality records and invalid atomic coverage all block
publication. Successful local runner tests forbid both BedrockInvoker and the
synthetic product tagger; no product model result or grade is generated.

## Remaining gates

- Parser stage: completed on successful delivery; downstream extraction is a
  durable pending job. Full run completion and all grades remain unproduced.
- Vision cross-check, product LLM, AWS/live provider, cloud telemetry, production
  deployment and real customer/private document gates: **not_run**.
- Browser E2E: **not_run** in this parser worker scope; local HTTP-to-command
  end-to-end integration was executed as above.
- Public ESG parser benchmark and accuracy claims: **not_run**. The test PDF and
  approval records are synthetic, while OpenDataLoader/pdfplumber actually ran.
- No Git commands, commits, push, cloud mutations, new dependencies or subagents.

Final combined regression after the last coverage validation change:

```sh
uv run --no-sync pytest tests/integration/test_local_parser_runner.py tests/acceptance/test_parsing.py tests/acceptance/test_jobs.py tests/acceptance/test_observability.py tests/unit tests/contracts tests/integration/test_run_lifecycle.py tests/integration/test_local_api_composition.py tests/acceptance/test_upload.py tests/acceptance/test_cost.py tests/security -q
```

Exit 0: **197 passed**, two existing dependency deprecation warnings, 28.60 seconds.
The final targeted code commands were:

```sh
uv run --no-sync ruff check apps/worker/src/proofops_worker/{local_runner,main,composition,telemetry}.py packages/proofops/{application/ingest/graph_fusion,adapters/parsing/opendataloader,adapters/local/job_store,adapters/local/run_artifacts}.py tests/integration/test_local_parser_runner.py
uv run --no-sync ruff format --check apps/worker/src/proofops_worker/{local_runner,main,composition,telemetry}.py packages/proofops/{application/ingest/graph_fusion,adapters/parsing/opendataloader,adapters/local/job_store,adapters/local/run_artifacts}.py tests/integration/test_local_parser_runner.py
uv run --no-sync mypy apps/worker/src/proofops_worker/{local_runner,main,composition,telemetry}.py packages/proofops/{application/ingest/graph_fusion,adapters/parsing/opendataloader,adapters/local/job_store,adapters/local/run_artifacts}.py
```
