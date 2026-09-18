# Local runtime configuration evidence

Date: 2026-09-09

`proofops_api.local_runtime.load_local_runtime(env)` returns exact `RunService`
kwargs only. All four local configuration/mode inputs blank return `{}`; a parser
profile alone returns parser kwargs and leaves the RunService gate closed.

`LOCAL_RUN_SETTINGS_PATH` is a regular-file, duplicate-key-rejecting JSON document
limited to 64 KiB. It requires absolute `build_root` and typed `budget_limits`;
it may contain a synthetic `ExtractionProfile` only with
`LOCAL_EXTRACTION_MODE=local_synthetic`, and typed `TaggingSettings` only with both
extraction configuration and `LOCAL_TAGGING_MODE=local_synthetic`. The loader has no
`proofops_agent` import. It recomputes `build_result` with `verify_supply_chain` and
rejects caller-provided fields such as `build_result.ready`.

Verification run:

```text
uv run --no-sync pytest tests/integration/test_local_runtime_config.py -q
12 passed in 0.05s

uv run --no-sync ruff check apps/api/src/proofops_api/local_runtime.py tests/integration/test_local_runtime_config.py
All checks passed!

uv run --no-sync mypy apps/api/src/proofops_api/local_runtime.py
Success: no issues found in 1 source file
```

Not run: API composition wiring and full application suite; those remain root-owned
and are outside this scoped loader change.

Coordinator integration: two focused checks first failed because the read was
unbounded and composed RunService ignored configuration. After bounded reads
and composition/preflight wiring, `uv run pytest tests/integration/test_local_runtime_config.py tests/integration/test_local_api_composition.py -q` passed **15 tests**.
The same real failed supply-chain result is exposed through preflight; no fake
ready result was injected. Scoped Ruff and mypy on the loader/composition/main
passed. Live models/AWS/human approvals remain not_run.
