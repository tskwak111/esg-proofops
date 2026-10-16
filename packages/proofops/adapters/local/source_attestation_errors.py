"""Fixed source-confirmation failure codes shared by parser and extraction workers."""

import re

_OCR_ACQUISITION_CODES = frozenset(
    {
        "OCR_PENDING_OR_FAILED",
        "OCR_BUDGET_EXHAUSTED",
        "OCR_RESPONSE_TOO_LARGE",
        "UPSTAGE_OCR_REQUEST_FAILED",
        "UPSTAGE_OCR_TIMEOUT",
        "UPSTAGE_OCR_INVALID_RESPONSE",
    }
)


def ocr_acquisition_failure_code(error):
    """Return a fixed, safe OCR acquisition code; reject identity/integrity errors."""
    if not isinstance(error, ValueError):
        return None
    code = str(error)
    for prefix in (
        "OCR_PAGE_ACQUISITION_FAILED:",
        "OCR_COLLECTION_FAILED_RESERVATION_RETAINED:",
    ):
        if code.startswith(prefix):
            code = code[len(prefix) :]
            break
    if code in _OCR_ACQUISITION_CODES:
        return code
    if re.fullmatch(r"UPSTAGE_HTTP_[1-5][0-9]{2}", code):
        return code
    return None


def source_failure_code(error):
    from pypdf.errors import PdfReadError

    if isinstance(error, PdfReadError):
        return "PARSER_PDF_INVALID"
    if not isinstance(error, ValueError):
        return None
    code = str(error)
    if code in {
        "BUDGET_EXHAUSTED",
        "H2_BUDGET_EXHAUSTED",
        "H2_CUMULATIVE_BUDGET_EXHAUSTED",
        "H3_BUDGET_EXHAUSTED",
        "H3_CUMULATIVE_BUDGET_EXHAUSTED",
        "H4_BUDGET_EXHAUSTED",
        "H4_CUMULATIVE_BUDGET_EXHAUSTED",
        "H5_BUDGET_EXHAUSTED",
        "H5_CUMULATIVE_BUDGET_EXHAUSTED",
        "R108_FINALS_BUDGET_EXHAUSTED",
        "R108_FINALS_CUMULATIVE_BUDGET_EXHAUSTED",
    }:
        return "BUDGET_EXHAUSTED"
    if code.startswith(
        (
            "OCR_COLLECTION_FAILED_RESERVATION_RETAINED:",
            "OCR_PENDING_OR_FAILED",
            "OCR_BUDGET_EXHAUSTED",
        )
    ):
        return "SOURCE_ATTESTATION_UNAVAILABLE"
    if code in {"OCR_TABLE_RECEIPT_MISMATCH", "EVIDENCE_SOURCE_RECEIPT_MISMATCH"}:
        return "SOURCE_ATTESTATION_REPLAY_MISMATCH"
    if code == "OCR_GEOMETRY_UNSUPPORTED":
        return "SOURCE_ATTESTATION_GEOMETRY_UNSUPPORTED"
    if code == "OCR_RENDER_LIMIT":
        return "SOURCE_ATTESTATION_RENDER_LIMIT"
    return None
