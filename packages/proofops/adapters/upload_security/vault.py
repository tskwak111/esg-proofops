"""Synthetic filesystem vault with atomic, create-only original/derived promotion."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from proofops.application.upload_contracts import (
    PdfLimits,
    QuarantinedPdf,
    UploadRejected,
    VerifiedPdf,
)

from .verification import verify_quarantined_pdf


class LocalUploadVault:
    """Synthetic local adapter: private root, atomic create-only promotion, no AWS calls.

    Use only with a service-owned root; uploaders must never have filesystem access.
    Upload state/CAS and the production versioned S3 adapter remain separate.
    """

    def __init__(self, root: Path):
        self.root = root

    def original_path(self, verified: VerifiedPdf) -> Path:
        source = verified.source
        return self.root / "original" / source.tenant_id / f"{source.document_version_id}.pdf"

    def verify_and_promote(
        self,
        source: QuarantinedPdf,
        limits: PdfLimits,
        *,
        tenant_id: str,
    ) -> VerifiedPdf:
        verified = verify_quarantined_pdf(source, limits, tenant_id=tenant_id)
        target = self.original_path(verified)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with NamedTemporaryFile(dir=target.parent) as staged:
            staged.write(source.content)
            staged.flush()
            os.fsync(staged.fileno())
            os.chmod(staged.name, 0o400)
            try:
                os.link(staged.name, target)  # Atomic create-only; never replace a prior revision.
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != source.content:
                    raise UploadRejected("VERSION_CONFLICT") from None
        for suffix, content in (
            (".display-v2.pdf", verified.display_content),
            (".decrypted.pdf", verified.analysis_content),
        ):
            if content is None:
                continue
            display_target = target.with_suffix(suffix)
            with NamedTemporaryFile(dir=target.parent) as staged:
                staged.write(content)
                staged.flush()
                os.fsync(staged.fileno())
                os.chmod(staged.name, 0o400)
                try:
                    os.link(staged.name, display_target)
                except FileExistsError:
                    if display_target.is_symlink() or display_target.read_bytes() != content:
                        raise UploadRejected("VERSION_CONFLICT") from None
        return verified
