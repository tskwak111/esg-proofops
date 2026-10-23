"""Private child handoff and fenced immutable hosted publication."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, cast

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

from proofops_api.hosted_contracts import (
    HostedError,
    digest,
)
from proofops_api.hosted_snapshots import pilot_bytes

if TYPE_CHECKING:
    from proofops_api.hosted_store import HostedStore


MAX_BYTES = cast(int, S4_PUBLICATION_POLICY["max_bytes"])


def runtime_identity(
    profile: str = "upstage-ocr-page-v13", policy: dict[str, Any] | None = None
) -> dict[str, Any]:
    import proofops
    from proofops.adapters.local.claim_source_policies import page_ocr_profile

    # External API is untyped and outside this work package.
    reader = page_ocr_profile(profile, policy=policy)  # type: ignore[no-untyped-call]
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    package = Path(proofops.__file__).parent
    api = Path(__file__).parent
    return dict(
        reader=reader.claim_source_policy(),
        runtime=runtime_policy(),
        # External API is untyped and outside this work package.
        read_profile=read_profile(),  # type: ignore[no-untyped-call]
        python=sys.version,
        platform=sys.platform,
        toolchain=os.environ.get("DEVELOPER_DIR"),
        code={
            f"{name}/{path.relative_to(root)}": hashlib.sha256(path.read_bytes()).hexdigest()
            for name, root in (("proofops", package), ("proofops_api", api))
            for path in sorted(root.rglob("*.py"))
        },
    )


def _context(path: Path, job: dict[str, Any], pages: list[int]) -> dict[str, Any]:
    manifest = pilot_bytes(path)
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
            # External API is untyped and outside this work package.
            registered = policy_for(V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy  # type: ignore[no-untyped-call]
            # External API is untyped and outside this work package.
            reader = page_ocr_profile(policy["source"], policy=snapshot["claim_source_policy"])  # type: ignore[no-untyped-call]
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
    # External API is untyped and outside this work package.
    if rb4_publication_enabled(policy):  # type: ignore[no-untyped-call]
        context["rb4_publication_digest"] = RB4_PUBLICATION_POLICY
    return context


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for file in sorted(path.rglob("*")):
        if file.is_symlink():
            raise ValueError("PUBLICATION_SYMLINK_INELIGIBLE")
        if file.is_file():
            pins[str(file.relative_to(path))] = _file_hash(file)
    return pins


def _authoritative_state(path: Path, *, stream_records: bool = False) -> str:
    # Result reads may populate only derived evidence-search caches. Pin all
    # durable run/checkpoint/tag/review records around the actual verification.
    digest = hashlib.sha256()

    def row_hash(row: tuple[object, ...]) -> bytes:
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


def make_handoff(path: Path, job: dict[str, Any], pages: list[int]) -> bytes | None:
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
        def without_db(pins: dict[str, str]) -> dict[str, str]:
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


def reuse_handoff(
    packet: bytes | None, path: Path, job: dict[str, Any], pages: list[int]
) -> bytes | None:
    """Only the parent's private FD supplies packet; never read it from disk."""
    if not isinstance(packet, bytes) or not packet or len(packet) > MAX_BYTES:
        return None
    try:
        record = json.loads(packet)
        if record["context"] != _context(path, job, pages) or record["pins"] != _pins(path):
            return None
        content: bytes = record["content"].encode()
        if hashlib.sha256(content).hexdigest() != record["content_sha256"]:
            return None
        snapshot = json.loads(content)
        if snapshot["tenant_id"] != job["tenant_id"] or snapshot["page_map"] != pages:
            return None
        return content
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, sqlite3.Error):
        return None


def publish_analysis(
    store: HostedStore,
    job: dict[str, Any],
    source: Path,
    status: str,
    error: str | None,
    *,
    publication_handoff: bytes | None = None,
) -> None:
    from proofops_api.hosted_results import result_snapshot

    if status not in {"completed", "partial_blocked"}:
        raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
    store.update_progress(job, "result", 95)
    # The worker owns analysis.lock while validating its private workspace.
    # Replay must never hold the control writer or run on a GET request.
    from proofops_api.hosted_publication import reuse_handoff

    pages = json.loads(job["pages"])
    content = reuse_handoff(publication_handoff, source, job, pages)
    if content is None:
        content = result_snapshot(source, job["tenant_id"], pages)
    # Stage potentially large receipts outside the writer; the final fence
    # and same-filesystem rename publish them together with the DB anchor.
    with TemporaryDirectory(prefix="proofops-publication-", dir=store.root) as scratch:
        staged = Path(scratch) / "artifacts"
        shutil.copytree(source, staged)
        # Initial publication is create-only. Flush the snapshot with the
        # receipts before acquiring either DB writer; install its anchor
        # only after rechecking the current run/document/fence.
        snapshot = staged / "result-1.json"
        store._write(snapshot, content)
        snapshot.chmod(0o400)
        snapshot_hash = digest(content)
        with store.transaction(operation="publish") as db:
            store._fenced(db, job, time.time())
            if db.execute(
                "SELECT 1 FROM result_snapshots WHERE run_id=?", (job["run_id"],)
            ).fetchone():
                raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
            target = (
                store.document_dir(job["tenant_id"], job["document_id"])
                / "analysis"
                / job["run_id"]
            )
            target.parent.mkdir(mode=0o700, exist_ok=True)
            os.rename(staged, target)
            db.execute(
                "INSERT INTO result_snapshots VALUES (?,1,?)", (job["run_id"], snapshot_hash)
            )
            db.execute(
                "INSERT OR REPLACE INTO run_progress VALUES (?, 'result',100,1)",
                (job["run_id"],),
            )
            db.execute(
                "UPDATE runs SET status=?,error_code=?,lease_until=0 WHERE run_id=?",
                (status, error, job["run_id"]),
            )
            store._settle_envelope(db, job["run_id"])


def _publish_snapshot(
    store: HostedStore, db: sqlite3.Connection, run: str, path: Path, content: bytes
) -> None:
    revision = db.execute(
        "SELECT coalesce(max(revision),0)+1 FROM result_snapshots WHERE run_id=?", (run,)
    ).fetchone()[0]
    target = path / f"result-{revision}.json"
    store._write(target, content)
    target.chmod(0o400)
    db.execute("INSERT INTO result_snapshots VALUES (?,?,?)", (run, revision, digest(content)))


def _result(store: HostedStore, db: sqlite3.Connection | None, row: sqlite3.Row) -> dict[str, Any]:
    path = store.document_dir(row["tenant_id"], row["document_id"]) / "analysis" / row["run_id"]
    if db is None:
        with store.transaction(readonly=True) as connection:
            anchor = connection.execute(
                "SELECT revision,sha256 FROM result_snapshots WHERE run_id=? "
                "ORDER BY revision DESC LIMIT 1",
                (row["run_id"],),
            ).fetchone()
    else:
        anchor = db.execute(
            "SELECT revision,sha256 FROM result_snapshots WHERE run_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (row["run_id"],),
        ).fetchone()
    try:
        if anchor is None:
            raise ValueError("snapshot not published")
        content = (path / f"result-{anchor['revision']}.json").read_bytes()
        if digest(content) != anchor["sha256"]:
            raise ValueError("snapshot hash mismatch")
        snapshot = json.loads(content)
        if snapshot["tenant_id"] != row["tenant_id"] or snapshot["page_map"] != json.loads(
            row["pages"]
        ):
            raise ValueError("snapshot scope mismatch")
        for relative, expected in snapshot["source_hashes"].items():
            if digest((path / relative).read_bytes()) != expected:
                raise ValueError("source hash mismatch")
        from proofops.application.pipeline_failures import public_reason_details

        result: dict[str, Any] = snapshot["result"]
        if result.get("reuse", {}).get("reused"):
            from proofops_api.hosted_reuse import verify_copy

            verify_copy(store, row, result)
        if result.get("hold_reasons"):
            # External API is untyped and outside this work package.
            return result | dict(hold_reason_details=public_reason_details(result["hold_reasons"]))  # type: ignore[no-untyped-call]
        return result
    except (OSError, ValueError, KeyError, TypeError):
        raise HostedError("RESULT_INTEGRITY_UNAVAILABLE", 409) from None


def get_result(store: HostedStore, tenant: str, run: str) -> dict[str, Any]:
    result = store.get_run(tenant, run)
    if result["result_url"] is None:
        raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
    return cast(dict[str, Any], result["result"])


def resolve_review(
    store: HostedStore,
    auth: Any,
    run: str,
    review: str,
    body: dict[str, Any],
    if_match: str | None,
    key: str,
) -> dict[str, Any]:
    from proofops_api.hosted_results import resolve_review, result_snapshot

    if not auth.has_capability("reviewer"):
        raise HostedError("FORBIDDEN", 403)
    with store.transaction() as db:
        row = store._run(db, auth.tenant_id, run)
        if row["status"] not in {"completed", "partial_blocked"}:
            raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
        if db.execute("SELECT 1 FROM rc1_reuse_audit WHERE run_id=?", (run,)).fetchone():
            raise HostedError("REUSED_RESULT_READ_ONLY", 409)
        path = store.document_dir(auth.tenant_id, row["document_id"]) / "analysis" / run
        # Shared payload lease lets GETs continue reading the prior immutable
        # snapshot while one review at a time publishes a validated revision.
        lock = (path.parent.parent / "analysis.lock").open("a+b")
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    try:
        with (path / "review.lock").open("a+b") as review_lock:
            os.fchmod(review_lock.fileno(), 0o600)
            fcntl.flock(review_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            resolved = resolve_review(path, auth, review, body, if_match, key)
            content = result_snapshot(path, auth.tenant_id, json.loads(row["pages"]))
            with store.transaction() as db:
                store._run(db, auth.tenant_id, run)
                store._publish_snapshot(db, run, path, content)
            return resolved
    finally:
        lock.close()
