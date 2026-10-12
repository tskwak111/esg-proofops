"""Private child result transfer; persisted files can never seed this handoff.

The parent receives these JSON bytes only from its inherited anonymous FD after
successful child exit, while retaining analysis.lock. All workspace bytes and
reader/runtime identities are rechecked before using the child's verified result.
No pickle, source-quality projection or stored cache is imported.
"""

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

from proofops.application.analysis_profile import S4_PUBLICATION_POLICY, VERIFIED_READ_V8_POLICY
from proofops.domain.provenance import canonical_hash

MAX_BYTES = S4_PUBLICATION_POLICY["max_bytes"]


def runtime_identity():
    import proofops
    from proofops.adapters.local import upstage_ocr_profile_v13 as reader
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    package = Path(proofops.__file__).parent
    api = Path(__file__).parent
    return dict(
        reader=reader.claim_source_policy(),
        runtime=runtime_policy(),
        read_profile=read_profile(),
        python=sys.version,
        platform=sys.platform,
        toolchain=os.environ.get("DEVELOPER_DIR"),
        code={
            f"{name}/{path.relative_to(root)}": hashlib.sha256(path.read_bytes()).hexdigest()
            for name, root in (("proofops", package), ("proofops_api", api))
            for path in sorted(root.rglob("*.py"))
        },
    )


def _context(path, job, pages):
    manifest = json.loads((path / "pilot.json").read_bytes())
    if manifest["tenant_id"] != job["tenant_id"]:
        raise ValueError("PUBLICATION_TENANT_MISMATCH")
    with sqlite3.connect((path / "state.sqlite3").resolve().as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(
            db.execute(
                "SELECT payload FROM run_snapshots WHERE run_id=?", (manifest["run_id"],)
            ).fetchone()[0]
        )
    policy = snapshot["analysis_profile_policy"]
    if (
        policy.get("verified_read_cache") != VERIFIED_READ_V8_POLICY
        or policy.get("publication_handoff") != S4_PUBLICATION_POLICY
        or policy.get("source") != "upstage-ocr-page-v13"
    ):
        raise ValueError("PUBLICATION_POLICY_INELIGIBLE")
    return dict(
        workspace=str(path.resolve()),
        tenant_id=job["tenant_id"],
        run_id=job["run_id"],
        fence=job["fence"],
        local_run_id=manifest["run_id"],
        page_map=pages,
        analysis_policy_sha256=canonical_hash(policy),
        execution=S4_PUBLICATION_POLICY,
        reader_runtime=runtime_identity(),
    )


def _file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pins(path):
    pins = {}
    for file in sorted(path.rglob("*")):
        if file.is_symlink():
            raise ValueError("PUBLICATION_SYMLINK_INELIGIBLE")
        if file.is_file():
            pins[str(file.relative_to(path))] = _file_hash(file)
    return pins


def make_handoff(path, job, pages):
    """Called inside the trusted child, after durable analysis and before exit."""
    from proofops_api.hosted_results import result_snapshot

    try:
        context = _context(path, job, pages)
        _pins(path)  # Reject symlinks before any read through the result services.
        content = result_snapshot(path, job["tenant_id"], pages)
        packet = json.dumps(
            dict(
                context=context,
                pins=_pins(path),
                content=content.decode(),
                content_sha256=hashlib.sha256(content).hexdigest(),
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return packet if len(packet) <= MAX_BYTES else None
    except (OSError, ValueError, KeyError, TypeError, IndexError, sqlite3.Error):
        return None  # The parent retains the original guarded cold replay.


def reuse_handoff(packet, path, job, pages):
    """Only the parent's private FD supplies packet; never read it from disk."""
    if not isinstance(packet, bytes) or not packet or len(packet) > MAX_BYTES:
        return None
    try:
        record = json.loads(packet)
        if record["context"] != _context(path, job, pages) or record["pins"] != _pins(path):
            return None
        content = record["content"].encode()
        if hashlib.sha256(content).hexdigest() != record["content_sha256"]:
            return None
        snapshot = json.loads(content)
        if snapshot["tenant_id"] != job["tenant_id"] or snapshot["page_map"] != pages:
            return None
        return content
    except (OSError, ValueError, KeyError, TypeError, IndexError, sqlite3.Error):
        return None
