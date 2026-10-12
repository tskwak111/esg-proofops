"""Exercise the actual private child FD protocol, then the guarded parent reuse."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryFile

from proofops_api.hosted_publication import MAX_BYTES, reuse_handoff


def main():
    root, out, case = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    start = time.monotonic()
    with TemporaryFile() as publication:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "evaluation.s4_live",
                str(root),
                str(out),
                case,
                str(publication.fileno()),
            ],
            pass_fds=(publication.fileno(),),
            check=True,
        )
        publication.seek(0)
        packet = publication.read(MAX_BYTES + 1)
    state = out / case
    manifest = json.loads((state / "pilot.json").read_text())
    job = dict(tenant_id=manifest["tenant_id"], run_id=manifest["run_id"], fence=1)
    begin = time.monotonic()
    content = reuse_handoff(packet, state, job, manifest["selected_pages"])
    if content is None:
        raise ValueError("S4_PARENT_BYTE_PIN_REJECTED")
    # Include the publisher's actual file operations in the boundary timing.
    # HostedStore's fenced DB/revision integration is covered separately.
    published = out / "publication-final"
    shutil.copytree(state, published)
    immutable = published / "result-1.json"
    immutable.write_bytes(content)
    immutable.chmod(0o400)
    parent_seconds = time.monotonic() - begin
    (state / "result.json").write_bytes(content)
    summary = json.loads((out / "child-timing.json").read_text()) | dict(
        parent_publication_seconds=parent_seconds,
        wall_seconds=time.monotonic() - start,
        packet_bytes=len(packet),
        result_bytes=len(content),
        private_fd=True,
        parent_cold_replay_calls=0,
        copied_publication=str(published),
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
