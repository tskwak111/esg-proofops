"""Content-free worker heartbeat; checks never initialize or mutate SQLite."""

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from proofops_api.hosted_store import RUN_LEASE_SECONDS

HEARTBEAT_MAX_AGE_SECONDS = 30
LEASE_HEARTBEAT_MAX_AGE_SECONDS = 90


class WorkerHeartbeat:
    def __init__(self, root):
        self.path = Path(root) / "worker-heartbeat.json"
        self.record = dict(
            worker_instance=str(uuid4()),
            pid=os.getpid(),
            started_at=time.time(),
            failures=0,
            database_busy=0,
            last_successful_tick_at=None,
            last_error_type=None,
        )

    def write(self, *, state, active=0, error=None):
        from proofops_api.hosted_sqlite import is_busy

        if error is not None:
            self.record["failures"] += 1
            self.record["database_busy"] += int(is_busy(error))
            self.record["last_error_type"] = type(error).__name__
        self.record.update(state=state, active=active, last_loop_at=time.time())
        staged = self.path.with_suffix(f".{self.record['worker_instance']}.tmp")
        with staged.open("w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(self.record, stream)
        os.replace(staged, self.path)


def worker_health(root, *, now=None, previous=None):
    now = time.time() if now is None else now
    try:
        record = json.loads((Path(root) / "worker-heartbeat.json").read_text())
        age = max(0, now - record["last_loop_at"])
        status = (
            "stopped"
            if record["state"] == "stopped"
            else "stale"
            if age > HEARTBEAT_MAX_AGE_SECONDS
            else "degraded"
            if record["state"] in {"initializing", "degraded"}
            else "running"
        )
        result = {
            key: record[key]
            for key in (
                "worker_instance",
                "pid",
                "started_at",
                "last_loop_at",
                "state",
                "active",
                "failures",
                "database_busy",
                "last_successful_tick_at",
                "last_error_type",
            )
        }
        result.update(
            status=status,
            heartbeat_age_seconds=age,
            observation="available",
            restart_detected=bool(
                previous and previous.get("worker_instance") != record["worker_instance"]
            ),
        )
    except FileNotFoundError:
        return dict(status="missing", observation="available", restart_detected=False)
    except (OSError, ValueError, KeyError, TypeError):
        return dict(status="unknown", observation="unavailable", restart_detected=False)
    try:
        # One bounded SELECT, fully consumed and closed before returning/printing.
        with closing(
            sqlite3.connect(
                (Path(root) / "control.sqlite3").as_uri() + "?mode=ro",
                uri=True,
                timeout=0.25,
                isolation_level=None,
            )
        ) as db:
            db.execute("PRAGMA query_only=ON")
            leases = db.execute("SELECT lease_until FROM runs WHERE status='running'").fetchall()
        result["expired_leases"] = sum(until <= now for (until,) in leases)
        result["stalled_lease_heartbeats"] = sum(
            now - (until - RUN_LEASE_SECONDS) > LEASE_HEARTBEAT_MAX_AGE_SECONDS
            for (until,) in leases
        )
        if leases and (result["expired_leases"] or result["stalled_lease_heartbeats"]):
            result["status"] = "degraded"
    except (OSError, ValueError, sqlite3.Error):
        result.update(status="unknown", observation="unavailable")
    return result


def main():
    result = worker_health(Path(os.environ["HOSTED_DATA_DIR"]))
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "running" else 1)


if __name__ == "__main__":
    main()
