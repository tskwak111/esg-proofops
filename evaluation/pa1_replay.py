"""Offline comparison of all result fields and repeated stored-response reads."""

import argparse
import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

from proofops.domain.provenance import canonical_hash


def main():
    from proofops_api import hosted_results

    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.state / "pilot.json").read_text())
    selected = json.loads(args.scope.read_text())["selection"]["pages"]
    original = hosted_results.services
    mode = "disabled"

    @contextmanager
    def services(*a, **k):
        with original(*a, **k) as bindings:
            os.environ["PROOFOPS_VERIFIED_READ_CACHE"] = mode
            yield bindings

    def deny(*a, **k):
        raise AssertionError("PA1_OFFLINE_NO_NETWORK")

    socket.create_connection = deny
    socket.socket.connect = deny
    hosted_results.services = services
    records = []
    baseline = None
    for mode in ("disabled", "exact-verified-read-v1", "exact-verified-read-v1"):
        started = time.monotonic()
        result = hosted_results.read_result(args.state, manifest["tenant_id"], selected)
        if baseline is None:
            baseline = result
        assert result == baseline, "PA1_RESULT_FIELDS_CHANGED"
        records.append(
            dict(
                mode=mode, seconds=time.monotonic() - started, result_sha256=canonical_hash(result)
            )
        )
    claims = baseline["claims"]
    summary = dict(
        reads=records,
        identical_all_fields=True,
        provider_calls=0,
        claims=len(claims),
        verified=sum(c["source_quality"] == "verified" for c in claims),
        provisional=sum(
            (c.get("provisional_grade") or {}).get("display_type") == "numeric" for c in claims
        ),
    )
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
