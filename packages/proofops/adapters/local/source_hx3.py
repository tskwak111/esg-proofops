"""Item-local source-read holds for new HX3 receipts; historical readers stay pinned."""

import logging
import re
import subprocess
from functools import wraps
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
from pdfplumber.utils.exceptions import PdfminerException
from pypdf.errors import PdfReadError

from proofops.domain.errors import DomainValidationError


def policy():
    return dict(
        profile="source-item-holds-hx3-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        failure="item-read-unresolved; identity-policy-and-receipt-errors-fatal",
    )


def failure_location(error):
    """Only code metadata, without paths, source lines, locals or exception messages."""
    locations = []
    trace = error.__traceback__
    while trace is not None:
        module = trace.tb_frame.f_globals.get("__name__", "unknown")
        function = trace.tb_frame.f_code.co_name
        if isinstance(module, str) and re.fullmatch(r"[A-Za-z0-9_.]+", module):
            if re.fullmatch(r"[A-Za-z0-9_<>]+", function):
                locations.append(f"{module}.{function}:{trace.tb_lineno}")
        trace = trace.tb_next
    return " > ".join(locations[-3:]) or "unknown"


def hold_read(read):
    @wraps(read)
    def checked(*args, **kwargs):
        try:
            return read(*args, **kwargs)
        except (
            ValueError,
            OSError,
            KeyError,
            TypeError,
            AttributeError,
            PdfminerException,
            PdfReadError,
            pdfium.PdfiumError,
            subprocess.SubprocessError,
        ) as error:
            # Integrity and authorization errors must never become a partial result.
            if isinstance(error, DomainValidationError) or (
                isinstance(error, ValueError)
                and str(error).startswith(("OCR_", "EVIDENCE_SOURCE_", "TENANT_"))
                and str(error) != "OCR_RENDER_LIMIT"
            ):
                raise
            logging.getLogger(__name__).warning(
                "source item unresolved: %s stage=source_verification location=%s",
                type(error).__name__,
                failure_location(error),
            )
            return dict(status="unresolved", reason="source_item_read_unresolved")

    return checked
