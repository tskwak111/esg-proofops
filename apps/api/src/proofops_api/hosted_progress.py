"""Coalesce advisory claim counters; never batch fences or money reservations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from proofops_api.hosted_store import HostedStore

import threading
import time


class ClaimProgress:
    def __init__(self, store: HostedStore, job: dict[str, Any]) -> None:
        self.store, self.job = store, job
        self._lock = threading.Lock()
        self._processed: set[str] = set()
        self._stages: dict[str, set[str]] = {
            stage: set() for stage in ("preliminary", "relation", "elements")
        }
        self._total = 0
        self._dirty = False
        self._last_write = float("-inf")

    def claim(self, claim_id: str, total: int) -> None:
        with self._lock:
            first = not self._processed
            self._processed.add(claim_id)
            self._update(total, force=first)

    def stage(self, claim_id: str, total: int, stage: str) -> None:
        with self._lock:
            self._stages[stage].add(claim_id)
            self._update(total)

    def _update(self, total: int, *, force: bool = False) -> None:
        self._total = max(self._total, total)
        self._dirty = True
        if force or time.monotonic() - self._last_write >= 1:
            self._flush()

    def _flush(self) -> None:
        if not self._dirty:
            return
        self.store.update_progress(
            self.job,
            "tag",
            75,
            claims_extracted=self._total,
            claims_processed=len(self._processed),
            claim_stage_counts={stage: len(claims) for stage, claims in self._stages.items()},
        )
        self._last_write = time.monotonic()
        self._dirty = False

    def flush(self) -> None:
        # Also flush after a partial tag result, before result publication.
        with self._lock:
            self._flush()
