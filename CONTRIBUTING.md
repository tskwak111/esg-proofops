# Development tests

Set up this checkout with `uv sync --frozen` and `pnpm install --frozen-lockfile`.
Run `pnpm build` before the full suite: release/UI checks inspect the built web
assets. Python tests use offline transports and temporary stores. Do not supply
production keys or invoke live provider probes for this workflow.

During development, run the relevant tests, then the core bundle when the change
crosses module boundaries:

```sh
scripts/test_core.sh -q --durations=20
scripts/test_core.sh -q tests/integration/test_cf6_confirmation.py
```

Core means `not legacy_pin and not slow`. This is a development feedback bundle;
it does not replace the full integration run. Before integration, run every test:

```sh
scripts/test_full.sh -q --durations=30
```

A plain `uv run pytest` collects and runs the complete suite. The markers do not
add a default filter or skip. Serialize resource-intensive runs on a shared host.

`tests/suite_markers.json` is an explicit, reviewed catalog. `legacy_pin` identifies
historical/experimental policy identity and reproduction cases. Mixed modules use
function selectors; for example I9's current operator defaults and I26's current
hosted wire checks stay in core. I31's current v29d composition/resume tests remain
in core, including their historical compatibility assertions. `slow` identifies
expensive cold integration, native/external-process and repeated replay workloads,
using recorded I31 timings as evidence, not dynamic timing-based deselection.
A function selector covers all parameters. Newly added tests default to core.

The catalog's `core_safety` groups list the retained false-confirmation,
unknown/absent, source verification, tenant/authorization, budget, lease, RC1 and
wire checks. The collection hook refuses a legacy/slow mark on any listed safety
case. Tests and assertions are retained in full. Update the catalog deliberately
when a test is renamed; `tests/test_suite_markers.py` checks selectors and safety
membership. Historical source-reader reproductions and expensive redundant full
pipelines remain mandatory in the full bundle.

Inspect collection without running tests:

```sh
scripts/test_full.sh --collect-only -q
scripts/test_core.sh --collect-only -q
uv run pytest --collect-only -q -m legacy_pin
uv run pytest --collect-only -q -m slow
```
