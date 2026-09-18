# Source-bound metric components — 2026-09-10

Added `separate_metric_quantity` to the existing evaluation helper. It first runs
`validate_semantics`, then reuses `quantity_candidates` to recognize exactly one
prefix quantity and unit followed by `의` plus whitespace and a nonempty remainder.
It adds literal quantity/unit/metric SourceRefs as `local_candidate` components;
the original model-proposed metric and every other dimension remain unchanged.
There is no implicit conversion to CO2e, Decimal normalization, binding acceptance,
source-quality revision, production inference integration or grade change.

## Actual archived report response

Replayed the previously recorded few-shot response against the pinned LG Chem
p24 graph and packet. The original metric proposal `약 3만 톤의 온실가스` remains
intact. New components are quantity `약 3만`, unit `톤`, metric `온실가스`, each
with its own exact original character range, page, coordinates and hashes.
The source remains unverified, entity/boundary unknown, binding undetermined.
This demonstrates local literal splitting for one case, not successful general
semantic extraction or a confirmed emissions evidence link.

`evidence/metric-split-results.json` records parent request/prompt/model/packet
identity, replica, tenant/document/source identity and local splitter rule hash.
No new product model call occurred. Ledger unchanged: 98 calls, $2.039563535
committed/reserved of $10, including two earlier unsettled calls.

## Scope and limits

Unsupported or ambiguous phrases receive an unresolved component result while
retaining the original tags. Guards cover multiple amounts, rate units such as
톤/년, percentage points, inequalities such as 이상, missing separators, empty
remainders and nested genitives. This deliberately narrow syntax does not claim
to parse arbitrary Korean morphology, infer metric meaning, or solve unknown
entity/boundary attribution. New syntax requires separate source-bound examples.

## Verification and review

Failing-first tests, including a separately failing nested-genitive regression,
then all 19 focused dimension tests passed. Original proposals/unknown states and
each component source slice are asserted. Archived real p24 replay also passed.
Ruff lint/format passed (234 files); mypy passed (146 source files); four-package
build, architecture and supply-chain checks passed. Production E2E/AWS not_run.

Orca run `run_2416b99008f8`, task `task_f7146b494b90`, dispatch `ctx_2ad0e8ad0885`:
OpenCode Muse Spark 1.3 Free reviewed edge cases read-only. Coordinator accepted
the concrete nested-genitive case and implemented its failing-first guard; no
semantic policy, GAP interpretation or acceptance rule was adopted from review.
Completion `msg_47986c794d8f` was accepted; worker-release reported external_terminal,
so the exact coordinator-created terminal was closed and delivery acknowledged.
Reclaimable worker enumeration returned empty. No Codex worker was used.

Final full suite:
`PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`
— 1,450 passed in 105.34s, two existing Starlette/AnyIO deprecation warnings.
`uv run --no-sync python scripts/validate_package.py` — 721/721 documentation and
contract checks passed, separately from application tests.
