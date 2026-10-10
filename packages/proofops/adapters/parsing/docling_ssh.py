"""SSH-only CUDA transport; no listening service, passwords or API keys on the GPU host."""

import gzip
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from proofops.adapters.parsing.opendataloader import ParseFailure, _json
from proofops.domain.provenance import canonical_hash

SSH_OPTIONS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=3",
]


def _run(command, timeout):
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ParseFailure("DOCLING_SSH_CONNECTION_OR_TIMEOUT") from None
    if result.returncode:
        # No raw remote stderr in public failures.
        raise ParseFailure("DOCLING_REMOTE_EXECUTION_FAILED")


def fetch_pages(source, profile, selected, artifact_root):
    target = profile.docling_ssh_target
    worker = Path(__file__).with_name("docling_gpu_child.py")
    worker_hash = sha256(worker.read_bytes()).hexdigest()
    identity = dict(
        source=source.sha256,
        pages=list(selected),
        worker_sha256=worker_hash,
        target=target,
        runtime="a100-mig-40gb-v2",
    )
    cache_root = Path(artifact_root).resolve() / "docling-gpu-cache" / source.tenant_id
    cache_root.mkdir(parents=True, exist_ok=True)
    cache = cache_root / (canonical_hash(identity) + ".json.gz")

    def read(path, *, cached=False):
        if path.stat().st_size > profile.max_output_bytes:
            raise ParseFailure("PARSER_OUTPUT_LIMIT")
        with gzip.open(path, "rb") as handle:
            raw = handle.read(profile.max_output_bytes + 1)
        if len(raw) > profile.max_output_bytes:
            raise ParseFailure("PARSER_OUTPUT_LIMIT")
        envelope = json.loads(raw)
        if cached:
            digest = envelope.pop("payload_sha256", None)
            if digest != canonical_hash(envelope):
                raise ParseFailure("DOCLING_REMOTE_CACHE_INTEGRITY_MISMATCH")
        if (
            envelope["source_sha256"] != source.sha256
            or envelope["worker_sha256"] != worker_hash
            or set(map(int, envelope["pages"])) != set(selected)
            or envelope["docling_version"] != "2.137.0"
        ):
            raise ParseFailure("DOCLING_REMOTE_IDENTITY_MISMATCH")
        return envelope

    if cache.exists():
        return read(cache, cached=True)
    user = target.split("@", 1)[0]
    # These paths refer only to this user's existing, tested benchmark runtime.
    home = f"/home/{user}"
    remote = f"{home}/esg-proofops-docling/jobs/{uuid4().hex}"
    with TemporaryDirectory(dir=cache_root, prefix="transfer-") as temporary:
        work = Path(temporary)
        (work / "source.pdf").write_bytes(source.content)
        (work / "request.json").write_bytes(
            _json(
                dict(
                    source_sha256=source.sha256,
                    pages=list(selected),
                    max_output_bytes=profile.max_output_bytes,
                )
            )
        )
        _run(["ssh", *SSH_OPTIONS, target, f"umask 077; mkdir -p {remote}"], 30)
        for path, name in (
            (worker, "worker.py"),
            (work / "source.pdf", "source.pdf"),
            (work / "request.json", "request.json"),
        ):
            _run(["scp", *SSH_OPTIONS, str(path.resolve()), f"{target}:{remote}/{name}"], 120)
        duration = int(profile.timeout_seconds)
        command = (
            f"umask 077; timeout --signal=TERM --kill-after=10 {duration} "
            f"env LD_LIBRARY_PATH={home}/parser-bench/nvlib "
            f"{home}/parser-bench/vd/bin/python {remote}/worker.py {remote}"
        )
        _run(["ssh", *SSH_OPTIONS, target, command], duration + 30)
        output = work / "result.json.gz"
        _run(["scp", *SSH_OPTIONS, f"{target}:{remote}/result.json.gz", str(output)], 120)
        envelope = read(output)
        # Persistent receipt allows diagnosing a disconnected request; do not remove other jobs.
        envelope["remote_job"] = remote
        envelope["payload_sha256"] = canonical_hash(envelope)
        payload = gzip.compress(_json(envelope))
        pending = cache.with_name(uuid4().hex + ".tmp")
        pending.write_bytes(payload)
        pending.replace(cache)
        return envelope
