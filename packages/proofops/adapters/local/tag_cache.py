"""File-backed local synthetic cache client; uses existing immutable cache semantics."""

from pathlib import Path

from proofops.adapters.cache.aws import StoredCacheObject
from proofops.adapters.local.sqlite_busy import connection


class SQLiteImmutableCacheClient:
    kind = "local-synthetic-only"

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("durable cache requires a file")
        with connection(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS local_tag_cache_v1 (
                key TEXT PRIMARY KEY, payload BLOB NOT NULL, sha256 TEXT NOT NULL)""")

    def put_if_absent(self, key: str, value: StoredCacheObject) -> bool:
        with connection(self.path) as db:
            return (
                db.execute(
                    "INSERT OR IGNORE INTO local_tag_cache_v1 VALUES (?, ?, ?)",
                    (key, value.payload, value.payload_sha256),
                ).rowcount
                == 1
            )

    def get(self, key: str) -> StoredCacheObject | None:
        with connection(self.path, readonly=True) as db:
            row = db.execute(
                "SELECT payload, sha256 FROM local_tag_cache_v1 WHERE key=?", (key,)
            ).fetchone()
            return StoredCacheObject(*row) if row else None

    def delete(self, key: str) -> None:
        with connection(self.path) as db:
            db.execute("DELETE FROM local_tag_cache_v1 WHERE key=?", (key,))
