"""Shared parser errors, canonical JSON and output accounting.

This leaf module is also used by H6/SPP/RB2 without importing orchestration.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol


class UpstageProbe(Protocol):
    def parse_async(self, payload: bytes, *, request_id: str, mode: str) -> dict[str, Any]: ...


PageResult = tuple[dict[str, Any], bool]
PageCall = Callable[[Sequence[int], str], PageResult]


class ProcessLimits(Protocol):
    """Resource ceilings shared by parser and source-preview subprocesses."""

    @property
    def timeout_seconds(self) -> float: ...

    @property
    def memory_bytes(self) -> int: ...

    @property
    def max_output_bytes(self) -> int: ...


class ParseFailure(ValueError):
    """Public code plus a private, retained stderr artifact when a child fails."""

    stderr_path: Path | None = None


def _json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _output_bytes(work: Path) -> int:
    import stat

    total = 0
    for path in work.iterdir():
        if path.name == "source.pdf":
            continue
        try:
            metadata = path.stat()
        except FileNotFoundError:
            # The JVM can remove a temporary PDF between enumeration and stat.
            # A removed file consumes no output bytes; other I/O failures remain
            # errors rather than silently disabling the limit.
            continue
        if stat.S_ISREG(metadata.st_mode):
            total += metadata.st_size
    return total
