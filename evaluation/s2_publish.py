"""Cold hosted result validation in a separate local process, no server writes."""

import argparse
import cProfile
import json
import time
from pathlib import Path

from proofops_api.hosted_results import result_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    state = args.state
    output = args.output or state
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((state / "pilot.json").read_text())
    started = time.monotonic()
    if args.profile:
        profiler = cProfile.Profile()
        content = profiler.runcall(
            result_snapshot, state, manifest["tenant_id"], manifest["selected_pages"]
        )
        profiler.dump_stats(str(args.profile))
    else:
        content = result_snapshot(state, manifest["tenant_id"], manifest["selected_pages"])
    (output / "publication.json").write_text(
        json.dumps(
            dict(
                seconds=time.monotonic() - started,
                result_bytes=len(content),
                cold_process=True,
                profiled=bool(args.profile),
            )
        )
    )
    (output / "result.json").write_bytes(content)


if __name__ == "__main__":
    main()
