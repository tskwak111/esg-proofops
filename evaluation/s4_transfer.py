"""Recover an already completed local S4 run; no model calls or receipt edits."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryFile

from proofops_api.hosted_publication import MAX_BYTES, make_handoff, reuse_handoff
from proofops_api.hosted_results import result_snapshot


def main():
    state = Path(sys.argv[1])
    output = state.parent
    manifest = json.loads((state / "pilot.json").read_text())
    job = dict(tenant_id=manifest["tenant_id"], run_id=manifest["run_id"], fence=1)
    pages = manifest["selected_pages"]
    if len(sys.argv) == 3:
        # This recovery starts in a new process. Perform the required original
        # verification first, then exercise the warm child handoff separately.
        start = time.monotonic()
        result_snapshot(state, job["tenant_id"], pages)
        cold = time.monotonic() - start
        start = time.monotonic()
        packet = make_handoff(state, job, pages)
        if packet is None:
            raise ValueError("S4_RECOVERY_HANDOFF_UNAVAILABLE")
        with os.fdopen(os.dup(int(sys.argv[2])), "wb") as fd:
            fd.write(packet)
        (output / "recovery-child.json").write_text(
            json.dumps(
                dict(
                    recovery_cold_verification_seconds=cold,
                    child_publication_seconds=time.monotonic() - start,
                )
            )
        )
        return
    start = time.monotonic()
    with TemporaryFile() as fd:
        subprocess.run(
            [sys.executable, "-m", "evaluation.s4_transfer", str(state), str(fd.fileno())],
            pass_fds=(fd.fileno(),),
            check=True,
        )
        fd.seek(0)
        packet = fd.read(MAX_BYTES + 1)
    child = json.loads((output / "recovery-child.json").read_text())
    begin = time.monotonic()
    content = reuse_handoff(packet, state, job, pages)
    if content is None:
        raise ValueError("S4_RECOVERY_PARENT_REJECTED")
    published = output / "publication-final"
    shutil.copytree(state, published)
    immutable = published / "result-1.json"
    immutable.write_bytes(content)
    immutable.chmod(0o400)
    parent_seconds = time.monotonic() - begin
    (state / "result.json").write_bytes(content)
    measurement = json.loads((state / "measurement.json").read_text())
    summary = child | dict(
        state=str(state),
        status="completed",
        private_fd=True,
        parent_publication_seconds=parent_seconds,
        parent_cold_replay_calls=0,
        seconds=measurement["seconds"],
        wall_seconds=measurement["seconds"] + time.monotonic() - start,
        packet_bytes=len(packet),
        result_bytes=len(content),
        copied_publication=str(published),
        model_calls_in_recovery=0,
        recovery=True,
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
