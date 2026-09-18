# Parent context as a separate search route — 2026-09-12

## Finding and bounded implementation

The previous metric-only query `탄소 감축 효과` returned E pages only. The graph
also contains a p97 note explaining that REC/green-premium reductions are deducted
when calculating market-based Scope 2 emissions. The child's parent sentence
contains REC and green-premium terms; the isolated metric does not. Replaying the
existing search on the unchanged full parent retrieves that exact note at rank 16,
as well as p99 renewable electricity methodology and p119 appendix routes.

Added `SectionSearch.search_with_parent` as an opt-in evaluation helper. It checks
scope and both original candidate selections using `selected_targets`, requires
the child to be inside the same source-exact parent, and returns two independently
bounded routes (up to 20 hits each). The parent is explicitly context-only; both
source selections are retained as copies. No hit is promoted, no parent attribute
is inherited, and binding stays undetermined. A failing-first test covers the
recovered data route, preserved child/parent, reversed containment and forged text.

This does not change EvidenceSearchPort, the existing lexical ranking/index
generation, production retrieval packets or their 12-snippet/token limits. The
40-hit review envelope is not a production model packet. No API/DB migration,
new dependency, grade rule or source-quality approval. Rollback removes calls to
the optional helper; existing search and old immutable results remain intact.

## Actual-source verification

Reused the PDF-validated 57-page LG Chem graph and pinned section map, with the
existing second child of the p25 sentence. The parent route retrieves the exact
p97 method note, and source IDs/raw text hashes, candidate quality, parent/child
spans, scope/map/implementation hashes and the note SourceRef are preserved in
`context-retrieval-results.json`. This is a method-search candidate only: it does
not prove the stated 4만 톤 reduction, the correct organizational boundary, year,
Scope 2 attribution or any numeric match. No data/appendix coverage completeness
or human-gold accuracy claim is made.

## Orca review

The runtime became unavailable between status and task creation. `orca open`
restored it (observed app 1.4.200); the failed calls returned no resource IDs.
Run `run_520d5555c517`, task `task_76dc8315879e`, dispatch `ctx_b682285fe91d` used
OpenCode Muse Spark 1.3 Free for read-only review. It reproduced short-fragment
ranking/duplicate crowding and parent rank 82 for the metric-only query. Its
suggested raw-text-hash deduplication was not adopted: identical text at different
locations can be distinct evidence. Its conclusion about rank truncation does
not exclude loss of discriminating REC terms after clause splitting; the
coordinator's full-parent replay directly demonstrated a useful separate route.
The worker completed, was released, its external terminal closed, and delivery
acknowledged. No Codex child agent or new report-model call was used.

## Checks and cost

Six section-pipeline tests pass. Ruff lint/format (234 files), mypy (146 files,
existing untyped-body note), all four Python package builds, architecture and
supply-chain gates pass. Deployed E2E, AWS, vision/source-quality approval and
semantic/numeric binding evaluation: not_run.

No new model calls or budget ledger edits. Last recorded cumulative committed /
reserved cost remains $2.0411683250 of $10, including two unsettled calls.

Final verification commands/results:

- `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`
  — 1,459 passed in 102.30s, two existing Starlette/AnyIO deprecation warnings.
- `PYTHONPATH=. uv run --no-sync python .local/context-retrieval/replay.py`
  — exact p97 method-note retrieval, source hashes, containment and bounds passed.
- `uv run --no-sync ruff check .` / `uv run --no-sync ruff format --check .` — passed.
- `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`
  — passed.
- `uv build --all-packages --out-dir .local/context-retrieval/dist` — passed.
- `uv run --no-sync python scripts/verify_architecture.py` — passed.
- `uv run --no-sync python scripts/check_licenses.py --root . --env ENABLE_LEGACY_PYMUPDF=false`
  — passed, with human rights/deployed-image gates remaining separate.
- `uv run --no-sync python scripts/validate_package.py` — 732/732 documentation
  and contract checks passed, separately from application tests.
