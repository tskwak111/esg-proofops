"""Private child-local reuse of a *completed full* claim-evidence replay.

Only bytes made here enter pickle.loads. Nothing is loaded from a disk cache.
Tag checkpoints, replicas and decisions are still checked by LocalTagStore.
The hosted parent's private-FD handoff and final publication fence are unchanged.
"""

import hashlib
import json
import os
import pickle
import sqlite3
import sys
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path
from zlib import compress, decompress

from proofops.application.ports.jobs import JobMessage
from proofops.application.spg_publication import enabled
from proofops.domain.provenance import canonical_hash

_session: ContextVar["Session | None"] = ContextVar("spg_publication", default=None)
MAX_BYTES = 64 * 1024 * 1024


def _files(root):
    result = {}
    if root.is_symlink():
        raise ValueError("SPG_SYMLINK")
    for file in sorted(root.rglob("*")):
        if file.is_symlink():
            raise ValueError("SPG_SYMLINK")
        if file.is_file():
            with file.open("rb") as stream:
                result[str(file.relative_to(root))] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    return result


def _ocr(ledger, source_sha256):
    # Include all original response bytes and bindings for this exact PDF.
    # C3 reads the full original, whereas the regular run reads a prepared PDF.
    # A correctly bound collection for that other SHA cannot affect this proof.
    if not ledger.exists():
        return None
    if ledger.is_symlink():
        raise ValueError("SPG_SYMLINK")
    digest = hashlib.sha256()
    with closing(sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        excluded = {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='ocr_calls'").fetchone():
            for request, tenant, key, collection in db.execute(
                "SELECT request_id,tenant,cache_key,collection FROM ocr_calls"
            ):
                if collection is None:
                    continue  # Unbound/in-flight rows conservatively invalidate reuse.
                record = json.loads(collection)
                if record["manifest"]["source_sha256"] == source_sha256:
                    continue
                if (
                    record["schema"] != "upstage_ocr_collection_v1"
                    or record["tenant_id"] != tenant
                    or record["request_id"] != request
                    or record["artifact_sha256"]
                    != canonical_hash({k: v for k, v in record.items() if k != "artifact_sha256"})
                    or key
                    != canonical_hash(dict(manifest=record["manifest"], policy=record["policy"]))
                ):
                    raise ValueError("SPG_OCR_BINDING_CHANGED")
                excluded[request] = (tenant, key)
        for table in ("ocr_calls", "ocr_page_cache", "ocr_response_bytes"):
            digest.update(table.encode())
            if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                    request = row[2] if table == "ocr_page_cache" else row[0]
                    if request in excluded:
                        if table == "ocr_page_cache" and row[:2] != excluded[request]:
                            raise ValueError("SPG_OCR_BINDING_CHANGED")
                        continue
                    digest.update(
                        canonical_hash(
                            [
                                {"blob": hashlib.sha256(v).hexdigest()}
                                if isinstance(v, bytes)
                                else v
                                for v in row
                            ]
                        ).encode()
                    )
    return digest.hexdigest()


def _runtime(snapshot):
    import proofops
    from proofops.adapters.local.claim_source_policies import claim_source_reader
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    reader = claim_source_reader(snapshot["claim_source_policy"])
    package = Path(proofops.__file__).parent
    return dict(
        reader=reader.claim_source_policy(),
        runtime=runtime_policy(),
        read_profile=read_profile(),
        python=sys.version,
        platform=sys.platform,
        toolchain=os.environ.get("DEVELOPER_DIR"),
        code={
            str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.rglob("*.py"))
        },
    )


class Session:
    def __init__(self, path, tenant, lease, check_lease):
        self.path, self.tenant, self.lease = Path(path).resolve(), tenant, lease
        self.check_lease = check_lease
        self.key = self.encoded = self.digest = None
        self.hits = self.misses = 0

    def fingerprint(self, claims, tenant, run_id):
        from proofops.adapters.local.run_artifacts import load_run_inputs
        from proofops.application.analysis_profile import publication_policy_for

        if (
            tenant != self.tenant
            or Path(claims.store.path).resolve() != self.path / "state.sqlite3"
        ):
            return None
        snapshot, source, profile = load_run_inputs(
            claims.store, claims.uploads, tenant_id=tenant, run_id=run_id
        )
        policy = snapshot.get("analysis_profile_policy", {})
        if not enabled(policy):
            return None
        if (
            publication_policy_for(
                snapshot["pipeline_profile"], pinned_hash=snapshot["analysis_profile_policy_sha256"]
            )
            != policy
        ):
            return None
        manifest = json.loads((self.path / "pilot.json").read_bytes())
        if (manifest["tenant_id"], manifest["run_id"]) != (tenant, run_id):
            return None
        run = claims.store.jobs.get_run(tenant, run_id)
        jobs = claims.store.jobs
        proofs = {}
        with jobs._transaction() as db:
            for stage in ("parse", "extract"):
                message = JobMessage(**run[stage + "_job"])
                job = jobs._job(db, message)
                ref = job["artifact_ref"]
                payload = jobs._raw(db, tenant, run_id, "artifact", ref["key"])
                if payload is None:
                    return None
                proofs[stage] = (job, hashlib.sha256(payload).hexdigest(), len(payload))
            for kind, record_id, value in db.execute(
                "SELECT kind,record_id,value FROM job_records WHERE tenant_id=? AND run_id=? "
                "AND (kind GLOB 'parser_*' OR kind GLOB 'raster_*') ORDER BY kind,record_id",
                (tenant, run_id),
            ):
                proofs[kind + ":" + record_id] = hashlib.sha256(value).hexdigest()
        # Like the private FD handoff, pin live reader/runtime code. This
        # boundary lookup replaces thousands of nested version queries;
        # it is never a process-global monkeypatch or a persisted approval.
        return canonical_hash(
            dict(
                tenant=tenant,
                run=run_id,
                workspace=str(self.path),
                lease=self.lease,
                pid=os.getpid(),
                snapshot=snapshot,
                source=hashlib.sha256(source.content).hexdigest(),
                head={
                    k: run.get(k)
                    for k in (
                        "parse_job",
                        "extract_job",
                        "claim_snapshot_sha256",
                        "cancellation_requested",
                        "document_version_id",
                    )
                },
                proofs=proofs,
                parser=_files(
                    claims.parser.artifact_root
                    / tenant
                    / source.document_version_id
                    / profile.parse_manifest_id
                ),
                ocr=_ocr(self.path / "upstage.sqlite3", source.sha256),
                runtime=_runtime(snapshot),
            )
        )

    def _key(self, claims, tenant, run_id):
        try:
            return self.fingerprint(claims, tenant, run_id)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
            return None

    def read(self, claims, tenant, run_id, cold):
        self.check_lease()  # Never swallow an expired/replaced hosted lease.
        before = self._key(claims, tenant, run_id)
        if before is not None and before == self.key and self.encoded is not None:
            if hashlib.sha256(self.encoded).hexdigest() == self.digest:
                result, compatibility = pickle.loads(decompress(self.encoded))
                self.check_lease()
                if self._key(claims, tenant, run_id) == before:
                    claims._read_compatibility.set(compatibility)
                    self.hits += 1
                    return result
        self.key = self.encoded = self.digest = None
        self.misses += 1
        result = cold()  # Original complete replay, including every source guard.
        self.check_lease()
        # This is a completed whole-evidence verification, not a raw reader
        # attestation. Its negative/unavailable states stay exactly negative;
        # no source ref is promoted here. A failed full replay never reaches
        # this point. Live runtime changes invalidate the fingerprint too.
        if before is not None:
            encoded = compress(
                pickle.dumps((result, claims.receipt_read_compatibility), protocol=5), level=1
            )
            if len(encoded) <= MAX_BYTES and self._key(claims, tenant, run_id) == before:
                self.key, self.encoded = before, encoded
                self.digest = hashlib.sha256(encoded).hexdigest()
        return result


@contextmanager
def publication_session(path, tenant, lease, check_lease):
    session = Session(path, tenant, lease, check_lease)
    token = _session.set(session)
    try:
        yield session
    finally:
        _session.reset(token)
        session.key = session.encoded = session.digest = None


def read_evidence(claims, tenant, run_id, *, for_extraction, cold):
    session = _session.get()
    if session is None or for_extraction:
        return cold()
    return session.read(claims, tenant, run_id, cold)
