"""Free AS1 inspection in a resource-bounded child, no provider transport."""

import json
import resource
import sys
from pathlib import Path


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    from evaluation.report_scope import inspect

    plan = inspect(Path(sys.argv[1]))
    plan["source_path"] = "original.pdf"
    # Path is private operational metadata; hash the sanitized proposal actually stored.
    from proofops.domain.provenance import canonical_hash

    plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    Path(sys.argv[2]).write_text(json.dumps(plan, ensure_ascii=False))


if __name__ == "__main__":
    main()
