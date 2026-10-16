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

from proofops.application.analysis_profile import (
    I18_PUBLICATION_POLICY,
    RG1_PUBLICATION_POLICY,
    S3_VERIFIED_READ_V13_POLICY,
    S4_PUBLICATION_POLICY,
    VERIFIED_READ_V8_POLICY,
    VERIFIED_READ_V9_POLICY,
    VERIFIED_READ_V10_POLICY,
    VERIFIED_READ_V11_POLICY,
    VERIFIED_READ_V12_POLICY,
)
from proofops.application.rb4_memory import PUBLICATION_POLICY as RB4_PUBLICATION_POLICY
from proofops.application.rb4_memory import publication_enabled as rb4_publication_enabled
from proofops.domain.provenance import canonical_hash

MAX_BYTES = S4_PUBLICATION_POLICY["max_bytes"]


def runtime_identity(profile="upstage-ocr-page-v13", policy=None):
    import proofops
    from proofops.adapters.local.claim_source_policies import page_ocr_profile

    reader = page_ocr_profile(profile, policy=policy)
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
    eligible = (
        policy.get("verified_read_cache"),
        policy.get("publication_handoff"),
        policy.get("source"),
    )
    registered = False
    if eligible[:2] in (
        (VERIFIED_READ_V10_POLICY, I18_PUBLICATION_POLICY),
        (VERIFIED_READ_V11_POLICY, I18_PUBLICATION_POLICY),
        (VERIFIED_READ_V12_POLICY, I18_PUBLICATION_POLICY),
        (S3_VERIFIED_READ_V13_POLICY, I18_PUBLICATION_POLICY),
    ):
        from proofops.adapters.local.claim_source_policies import page_ocr_profile
        from proofops.application.analysis_profile import V2_PROFILE, policy_for

        try:
            registered = policy_for(V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy
            reader = page_ocr_profile(policy["source"], policy=snapshot["claim_source_policy"])
            registered = registered and reader.PROFILE == policy["source"]
        except (ValueError, KeyError):
            registered = False
    if not registered and eligible not in (
        (VERIFIED_READ_V8_POLICY, S4_PUBLICATION_POLICY, "upstage-ocr-page-v13"),
        (VERIFIED_READ_V9_POLICY, RG1_PUBLICATION_POLICY, "upstage-ocr-page-v17"),
    ):
        raise ValueError("PUBLICATION_POLICY_INELIGIBLE")
    context = dict(
        workspace=str(path.resolve()),
        tenant_id=job["tenant_id"],
        run_id=job["run_id"],
        fence=job["fence"],
        local_run_id=manifest["run_id"],
        page_map=pages,
        analysis_policy_sha256=canonical_hash(policy),
        execution=policy["publication_handoff"],
        reader_runtime=runtime_identity(policy["source"], snapshot.get("claim_source_policy")),
    )
    if rb4_publication_enabled(policy):
        context["rb4_publication_digest"] = RB4_PUBLICATION_POLICY
    return context


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


def _authoritative_state(path, *, stream_records=False):
    # Result reads may populate only derived evidence-search caches. Pin all
    # durable run/checkpoint/tag/review records around the actual verification.
    digest = hashlib.sha256()

    def row_hash(row):
        return canonical_hash(
            [
                dict(sqlite_type="blob", sha256=hashlib.sha256(value).hexdigest())
                if isinstance(value, bytes)
                else value
                for value in row
            ]
        ).encode()

    with sqlite3.connect((path / "state.sqlite3").resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        for row in db.execute("SELECT run_id,payload FROM run_snapshots ORDER BY run_id"):
            digest.update(row_hash(row))
        digest.update(b"job_records")
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='job_records'").fetchone():
            if stream_records:
                # Sorting the BLOB values spills whole checkpoint histories to
                # SQLite temp storage. Keep the original table-scan/tie order,
                # sort only small keys, and hash every complete value in turn.
                keys = db.execute(
                    "SELECT rowid,kind,record_id FROM job_records NOT INDEXED "
                    "WHERE kind NOT IN ('document_evidence_search','element_evidence_search') "
                    "ORDER BY kind,record_id,rowid"
                )
                for rowid, kind, record_id in keys:
                    value = db.execute(
                        "SELECT value FROM job_records WHERE rowid=?", (rowid,)
                    ).fetchone()[0]
                    digest.update(row_hash((kind, record_id, value)))
            else:
                for row in db.execute(
                    "SELECT kind,record_id,value FROM job_records "
                    "WHERE kind NOT IN ('document_evidence_search','element_evidence_search') "
                    "ORDER BY kind,record_id"
                ):
                    digest.update(row_hash(row))
    return digest.hexdigest()


def make_handoff(path, job, pages):
    """Called inside the trusted child, after durable analysis and before exit."""
    from proofops_api.hosted_results import result_snapshot

    try:
        context = _context(path, job, pages)
        stream_records = context.get("rb4_publication_digest") == RB4_PUBLICATION_POLICY
        before = _pins(path)  # Reject symlinks before any source read.
        durable = _authoritative_state(path, stream_records=stream_records)
        content = result_snapshot(path, job["tenant_id"], pages)
        after = _pins(path)

        # SQLite readers can add derived searches, but source/graph/receipt
        # files and every authoritative record must remain byte-identical.
        def without_db(pins):
            return {
                k: v
                for k, v in pins.items()
                if k not in {"state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm"}
            }

        snapshot = json.loads(content)
        if (
            without_db(before) != without_db(after)
            or durable != _authoritative_state(path, stream_records=stream_records)
            or context != _context(path, job, pages)
            or any(after.get(k) != v for k, v in snapshot["source_hashes"].items())
        ):
            return None
        packet = json.dumps(
            dict(
                context=context,
                pins=after,
                content=content.decode(),
                content_sha256=hashlib.sha256(content).hexdigest(),
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return packet if len(packet) <= MAX_BYTES else None
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, sqlite3.Error):
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
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, sqlite3.Error):
        return None
