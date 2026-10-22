"""Identity/hash checks around isolated inspection of memory or disk snapshots."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from proofops.application.upload_contracts import (
    STRICT_PROFILES,
    PdfLimits,
    QuarantinedPdf,
    UploadRejected,
    VerifiedPdf,
)

from .process import inspected_child

# Keep the historical CLI path in editable and installed package layouts.
CHILD_ENTRYPOINT = Path(__file__).resolve().parents[2] / "application" / "uploads_security.py"


def verify_quarantined_pdf(
    source: QuarantinedPdf,
    limits: PdfLimits,
    *,
    tenant_id: str,
) -> VerifiedPdf:
    """Verify an immutable quarantine snapshot; resource failures never become evidence absence.

    Storage callers must bound object reads by max_bytes before constructing the snapshot.
    On Windows a Job Object limits committed memory, CPU time and child processes.
    On Linux the child has hard address-space/CPU/process limits. macOS uses an RSS
    watchdog (sampled, not a kernel memory sandbox); deployment isolation is separate.
    """
    if tenant_id != source.tenant_id:
        raise UploadRejected("NOT_FOUND")
    from proofops.domain.values import _require_uuid

    try:
        _require_uuid("tenant_id", tenant_id)
        _require_uuid("document_version_id", source.document_version_id)
    except ValueError:
        raise UploadRejected("PDF_INVALID") from None
    if (
        not isinstance(source.object_version_id, str)
        or not 1 <= len(source.object_version_id) <= 1024
        or any(ord(character) < 32 for character in source.object_version_id)
    ):
        raise UploadRejected("PDF_INVALID")
    if not isinstance(source.content, bytes):
        raise UploadRejected("PDF_INVALID")
    if len(source.content) > limits.max_bytes:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    if (
        type(source.expected_size) is not int
        or source.expected_size != len(source.content)
        or sha256(source.content).hexdigest() != source.expected_sha256
    ):
        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", source.content):
        raise UploadRejected("PDF_INVALID")
    with TemporaryDirectory(prefix="proofops-quarantine-") as scratch:
        input_path = Path(scratch) / "source.pdf"
        input_path.write_bytes(source.content)
        input_path.chmod(0o400)
        command = [
            sys.executable,
            "-I",
            str(CHILD_ENTRYPOINT),
            str(input_path),
            json.dumps(asdict(limits)),
        ]
        display_path = Path(scratch) / "display.pdf"
        command.append(str(display_path))
        deadline = monotonic() + limits.timeout_seconds
        with inspected_child(command, limits, deadline=deadline, cwd=scratch) as (process, output):
            if process.returncode:
                raise UploadRejected(
                    "UPLOAD_LIMIT_EXCEEDED" if process.returncode < 0 else "PDF_INVALID"
                )
            result = json.loads(output)
            if result["code"] != "verified":
                raise UploadRejected(result["code"], security_metadata=result.get("security", {}))
            if result["security"]["source_sha256"] != source.expected_sha256:
                raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
            display_content = None
            analysis_content = None
            if limits.policy_profile in STRICT_PROFILES and result.get("security", {}).get(
                "encrypted"
            ):
                with display_path.open("rb") as analysis_file:
                    analysis_content = analysis_file.read(limits.max_bytes + 1)
                if len(analysis_content) > limits.max_bytes:
                    raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                if sha256(analysis_content).hexdigest() != result["security"]["analysis_sha256"]:
                    raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
            if limits.policy_profile == "display-v2":
                with display_path.open("rb") as display_file:
                    display_content = display_file.read(limits.max_bytes + 1)
                if len(display_content) > limits.max_bytes:
                    raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                if sha256(display_content).hexdigest() != result["security"]["display_sha256"]:
                    raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    # Resource telemetry varies per child; keep immutable retry/version metadata stable.
    result.get("security", {}).pop("peak_rss_bytes", None)
    return VerifiedPdf(
        source, result["pages"], display_content, result.get("security", {}), analysis_content
    )


def verify_pdf_file(
    path: Path,
    limits: PdfLimits,
    *,
    expected_size: int,
    expected_sha256: str,
    derived_path: Path | None = None,
    security_metadata: dict | None = None,
) -> int:
    """Strict verification of a service-owned disk snapshot; no whole-file body copy."""
    from hashlib import file_digest

    if limits.policy_profile not in STRICT_PROFILES:
        raise UploadRejected("PDF_INVALID")
    if path.is_symlink() or path.stat().st_size != expected_size:
        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    if expected_size > limits.max_bytes:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    with path.open("rb") as stream:
        if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", stream.read(16)):
            raise UploadRejected("PDF_INVALID")
        stream.seek(0)
        if file_digest(stream, "sha256").hexdigest() != expected_sha256:
            raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    deadline = monotonic() + limits.timeout_seconds
    with inspected_child(
        [
            sys.executable,
            "-I",
            str(CHILD_ENTRYPOINT),
            str(path),
            json.dumps(asdict(limits)),
            *([str(derived_path)] if derived_path is not None else []),
        ],
        limits,
        deadline=deadline,
    ) as (process, output):
        returncode = process.returncode
    if returncode:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED" if returncode < 0 else "PDF_INVALID")
    result = json.loads(output)
    if result["code"] != "verified":
        raise UploadRejected(result["code"], security_metadata=result.get("security", {}))
    if result["security"]["source_sha256"] != expected_sha256:
        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    if security_metadata is not None:
        security_metadata.update(result.get("security", {}))
    return result["pages"]
