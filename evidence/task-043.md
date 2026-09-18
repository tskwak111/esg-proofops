# TASK-043 Evidence — Legacy characterization and selective migration

Date: 2026-09-09

## Scope and outcome

- Frozen source: `tskwak111/esg-evidence-audit` at `70da628a401b89b5ea2c08ee4243523ce99acb50`.
- Snapshot SHA-256 checks cover `run_signature.py`, `graph_ensemble.py`, `document_graph.py`, and `parser_adapters.py`.
- R-01 through R-05 are characterized in `tests/unit/test_legacy_characterization.py`: a local model shim executes the SHA-verified frozen `graph_ensemble.py` and `parser_adapters.py` A1/B1/B2 dangling alias, non-overlapping duplicate text, and zero-bbox paths; ProofOps blocks scorer/policy/gold imports and requires valid replicate IDs. No upstream pipeline was executed.
- No legacy source was copied into `packages/proofops`: the source has no recorded explicit repository license or reuse approval. The selected migration is deliberately empty.

## Commands and results

| Command | Result |
|---|---|
| `uv run pytest tests/unit/test_legacy_characterization.py -q` | passed — 15 passed |
| Temporary copy without `legacy_reference/snapshot`: selected snapshot-dependent tests | passed — 7 skipped, 8 deselected; the shared ignored snapshot was not renamed or changed |
| `uv run ruff check tests/unit/test_legacy_characterization.py` | passed — `All checks passed!` |
| `uv run mypy tests/unit/test_legacy_characterization.py` | passed — `Success: no issues found in 1 source file` |
| `uv run python scripts/validate_package.py` | passed — 695/695 contract/document checks; not an application test |
| `uv run pytest tests/unit/test_legacy_characterization.py tests/contracts/test_package_contracts.py -q` | passed — 44 passed, 1 Starlette deprecation warning |

## Not run

- Upstream legacy runtime tests: not_run. No upstream pipeline was run; the read-only snapshot has no upstream test suite or installable package. Snapshot-dependent checks skip only if the ignored local snapshot is absent.
- Real model calls, AWS mutation, customer data, legal/rights approval, and PDF benchmark: not_run; none were attempted.
