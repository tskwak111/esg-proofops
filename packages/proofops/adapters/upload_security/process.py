"""Shared parent watchdog and child cleanup; no PDF parsing in the parent."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic

from proofops.application.upload_contracts import (
    PdfLimits,
    UploadRejected,
)


@contextmanager
def inspected_child(
    command: list[str],
    limits: PdfLimits,
    *,
    deadline: float,
    cwd: str | None = None,
) -> Iterator[tuple[subprocess.Popen[bytes], bytes]]:
    """Wait with the platform watchdog, then kill/reap on every exit path.

    The caller keeps its original deadline start and decides whether to inspect
    metadata before or after cleanup. The child never inherits application env.
    """
    with subprocess.Popen(
        command,
        shell=False,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        start_new_session=True,
    ) as process:
        try:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                try:
                    output, _ = process.communicate(timeout=min(0.02, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if sys.platform == "darwin":
                        # ponytail: sampled macOS RSS; Linux hard limits for production.
                        rss = subprocess.run(
                            ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                            capture_output=True,
                            timeout=1,
                            check=False,
                        ).stdout.strip()
                        if rss and int(rss) * 1024 > limits.memory_bytes:
                            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
            yield process, output
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
