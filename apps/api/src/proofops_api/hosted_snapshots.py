"""Read persisted pilot metadata and snapshots without initializing local services.

Callers retain their own tenant, source, symlink and publication-policy checks.
The text loader preserves the existing result reader's decoding behavior.
"""

import json
import sqlite3
from pathlib import Path


def pilot_bytes(path: Path) -> dict:
    return json.loads((path / "pilot.json").read_bytes())


def pilot_text(path: Path) -> dict:
    return json.loads((path / "pilot.json").read_text())


def tenant_snapshot(db: sqlite3.Connection, tenant: str, run: str) -> dict:
    return json.loads(
        db.execute(
            "SELECT payload FROM run_snapshots WHERE tenant_id=? AND run_id=?",
            (tenant, run),
        ).fetchone()[0]
    )
