"""Compatibility imports and the stable ``python -I <file>`` upload entrypoint.

OS/PDF work lives in adapters.upload_security; contracts are independent of it.
This facade intentionally retains the old application-to-adapter compatibility
edge. The FX6b corpus diagnostic records this entrypoint's byte hash, not hashes
of its transitive implementation modules.
"""

from proofops.adapters.upload_security.child import _inspect, main
from proofops.adapters.upload_security.display import (
    _ACTION_SUBTYPES,
    _DISPLAY_REMOVE,
    _display_reader,
    _inspect_display,
)
from proofops.adapters.upload_security.limits import _windows_limits
from proofops.adapters.upload_security.strict import _inspect_legacy, _inspect_strict
from proofops.adapters.upload_security.vault import LocalUploadVault
from proofops.adapters.upload_security.verification import verify_pdf_file, verify_quarantined_pdf
from proofops.application.upload_contracts import (
    HOSTED_NULL_NAVIGATION_PROFILE,
    STRICT_PROFILES,
    PdfLimits,
    QuarantinedPdf,
    UploadRejected,
    VerifiedPdf,
)

__all__ = [
    "HOSTED_NULL_NAVIGATION_PROFILE",
    "STRICT_PROFILES",
    "UploadRejected",
    "PdfLimits",
    "QuarantinedPdf",
    "VerifiedPdf",
    "verify_quarantined_pdf",
    "verify_pdf_file",
    "LocalUploadVault",
    "_windows_limits",
    "_inspect_legacy",
    "_inspect_strict",
    "_DISPLAY_REMOVE",
    "_ACTION_SUBTYPES",
    "_display_reader",
    "_inspect_display",
    "_inspect",
]

if __name__ == "__main__":
    main()
