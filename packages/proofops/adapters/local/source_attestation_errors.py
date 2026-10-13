"""Fixed source-confirmation failure codes shared by parser and extraction workers."""


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
