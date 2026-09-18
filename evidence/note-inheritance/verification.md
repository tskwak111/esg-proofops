# Bound-field note retention — 2026-09-14 KST

The existing inferred and explicit table normalizers omitted notes linked to a
metric, year or boundary cell. They collected only table/value-cell edges.
The numeric checker independently omitted those bound-field targets, allowing
an otherwise verified synthetic comparison to ignore a qualifying condition.

The shared `_observation` now collects each note once from exactly the table,
value and bound-field targets. Sibling years are excluded. It retains original
note blocks and source refs and never approves their quality. The numeric
checker adds bound targets only after validating the value-root/table lineage;
removing observation note text cannot bypass original required edges.
Normalizer identity version3 prevents replacing prior observation identities.
No API/DB migration, domain rule or dependency changed.

Fail-first log `.local/table-note-wave/inheritance-red.log`:5 failures/99 passes.
Focused final:133 passed across table, explicit-binding and numeric acceptance
checks. Cases cover metric/year/boundary inheritance, removed note text and
2024/2025 isolation through both normalizers. Ruff passed; mypy162 files passed;
all4 Python packages built. Document/contracts validator758 passed, separately
from app tests. `git diff --check` passed.

Orca run `run_bd4f467aede6`, task `task_c68bfa2dcd97`, dispatch
`ctx_aaecde39a1ff`: Muse Spark1.3 Free independently reviewed the pre-fix code,
confirmed the omission and identified the sibling-year leakage hazard. The
coordinator implemented and verified the fix. Worker completion was accepted,
release returned external-terminal retention, exact terminal close confirmed
PTY termination, and its delivery was acknowledged. No reclaimable workers.

No model/AWS calls this change. The shared USD10 ledger was not changed.
These are synthetic regression results, not report-level accuracy measurements.
Source-linked extraction proposals still need semantic acceptance and runtime
integration; `check_numeric_consistency` has no app/evaluation caller. Dense
Samsung Life discovery and unsupported title/standalone markers remain open.
The original service-readiness goal is not complete.

Full final application suite: `uv run pytest -q` —1823 passed,2 existing
deprecation warnings,115.88s. Log:
`.local/table-note-wave/pytest-inheritance-final.log`.
