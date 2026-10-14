"""Local scope input gate matching hosted byte limits and encrypted-PDF inspection."""

from contextlib import contextmanager
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory

from proofops.application.input_failures import HOSTED_MAX_UPLOAD_BYTES
from proofops.application.uploads_security import (
    HOSTED_NULL_NAVIGATION_PROFILE,
    PdfLimits,
    verify_pdf_file,
)
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader

MAX_UPLOAD_BYTES = HOSTED_MAX_UPLOAD_BYTES
POLICY = {
    "profile": "hosted-compatible-scope-input-hx5-v1",
    "max_bytes": MAX_UPLOAD_BYTES,
    "encrypted": "existing-hosted-ingest-gate; immutable-original-and-verified-derivative",
}


@contextmanager
def scope_input(pdf: Path):
    size = pdf.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("local scope study limit: 150 MiB")
    with pdf.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    reader = PdfReader(pdf)
    metadata: dict = {}
    with TemporaryDirectory(prefix="proofops-scope-input-") as scratch:
        analysis = pdf
        if reader.is_encrypted:
            analysis = Path(scratch) / "decrypted.pdf"
            verify_pdf_file(
                pdf,
                PdfLimits(
                    policy_profile=HOSTED_NULL_NAVIGATION_PROFILE,
                    max_bytes=MAX_UPLOAD_BYTES,
                    max_decoded_bytes=512 * 1024 * 1024,
                ),
                expected_size=size,
                expected_sha256=digest,
                derived_path=analysis,
                security_metadata=metadata,
            )
        yield analysis, digest, metadata
        with pdf.open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("source changed during scope inspection")


def bind_original(result, pdf, digest, metadata, *, hash_field):
    result.update(
        source_path=str(pdf.resolve()),
        source_sha256=digest,
        input_policy_sha256=canonical_hash(POLICY),
    )
    if metadata:
        result["input_security"] = metadata
    result[hash_field] = canonical_hash({k: v for k, v in result.items() if k != hash_field})
    return result
