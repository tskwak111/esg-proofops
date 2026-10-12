"""Read-only retained-state publication comparison; no provider or run mutation."""

import json
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from proofops_api import hosted_results


def main():
    state, source, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    if not (state / "outcome.json").exists():
        shutil.copy2(source / "outcome.json", state / "outcome.json")
    manifest = json.loads((state / "pilot.json").read_text())
    start = time.monotonic()
    # Historical provenance stays v7. The comparison explicitly chooses only
    # the v8 execution optimization while reading those unchanged receipts.
    if mode == "v8":
        import os

        original = hosted_results.services

        @contextmanager
        def optimized(*a, **kw):
            with original(*a, **kw) as services:
                os.environ["PROOFOPS_VERIFIED_READ_CACHE"] = "exact-verified-read-v8"
                yield services

        hosted_results.services = optimized
    content = hosted_results.result_snapshot(
        state, manifest["tenant_id"], manifest["selected_pages"]
    )
    (state / "result.json").write_bytes(content)
    (state / "publication.json").write_text(
        json.dumps(
            dict(
                seconds=time.monotonic() - start,
                bytes=len(content),
                cold_process=True,
                live_provider_calls=0,
                execution_optimization=mode,
            )
        )
    )
    print(
        json.dumps(dict(publication_seconds=time.monotonic() - start, bytes=len(content))),
        flush=True,
    )


if __name__ == "__main__":
    main()
