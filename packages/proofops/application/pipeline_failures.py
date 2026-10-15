"""Safe public explanations of pipeline stops; no evidence or grade inference."""

MESSAGES = {
    "TIME_BUDGET": (
        "분석 시간 한도로 새 처리를 중단했습니다. 완료된 결과와 미처리 주장을 구분해 "
        "보존했으며, 미처리 주장은 판정 보류입니다. 원문의 근거 부재를 뜻하지 않습니다."
    ),
    "PARSER_FAILED": (
        "문서 파싱에 실패해 분석을 중단했습니다. 처리되지 않은 원문은 판정하지 않았습니다. "
        "운영자의 파싱 확인이 필요합니다."
    ),
    "PARSER_MEMORY_LIMIT": (
        "PDF 파싱이 메모리 한도에 도달했습니다. 선택 " "쪽을 줄여 새 분석을 접수해 주세요."
    ),
    "PARSER_JAVA_HEAP_EXHAUSTED": (
        "PDF 파싱이 메모리 한도에 도달했습니다. 선택 " "쪽을 줄여 새 분석을 접수해 주세요."
    ),
    "PARSER_MEMORY_WATCHDOG_UNAVAILABLE": (
        "서버의 파싱 자원 감시가 준비되지 않았습니다. " "운영자 확인이 필요합니다."
    ),
    "PARSER_PDF_INVALID": (
        "PDF 내부 구조를 읽지 못했습니다. " "PDF 뷰어에서 다시 저장한 파일로 업로드해 " "주세요."
    ),
    "PARSER_NATIVE_TEXT_UNREADABLE": (
        "PDF의 보조 텍스트 파서가 파일 구조를 읽지 못했습니다. "
        "원문과 처리 중 남긴 후보는 보존하며 확인되지 않은 내용은 판정하지 않았습니다."
    ),
    "PARSER_GEOMETRY_INVALID": (
        "PDF의 원문 좌표를 검증하지 못했습니다. 해당 " "원문은 판정하지 않았습니다."
    ),
    "CLAIM_PAGES_UNREADABLE": (
        "선택한 주장 쪽을 읽지 못했습니다. 다른 쪽 또는 " "다시 저장한 PDF로 접수해 주세요."
    ),
    "CLAIM_PAGE_PARSE_FAILURE": (
        "일부 주장 쪽을 읽지 못했습니다. 처리된 주장만 " "표시하며 누락 쪽은 판정하지 않았습니다."
    ),
    "CLAIM_SOURCE_EXTRACTION_FAILURE": (
        "일부 원문에서 주장을 추출하지 못했습니다. 처리된 " "주장만 표시합니다."
    ),
    "SOURCE_ATTESTATION_UNAVAILABLE": (
        "원문 대조를 완료하지 못했습니다. 해당 주장은 " "보류하며 운영자 확인이 필요합니다."
    ),
    "SOURCE_ATTESTATION_REPLAY_MISMATCH": (
        "원문 대조 기록의 재검증이 일치하지 않습니다. "
        "기존 기록을 보존하고 해당 주장을 보류했습니다."
    ),
    "SOURCE_ATTESTATION_GEOMETRY_UNSUPPORTED": (
        "이 PDF의 회전·좌표 형식을 원문 대조기가 " "지원하지 않아 해당 주장을 보류했습니다."
    ),
    "SOURCE_ATTESTATION_RENDER_LIMIT": (
        "PDF 쪽의 이미지 크기가 원문 대조 한도를 초과했습니다. "
        "해당 원문은 판정하지 않았으며 운영자의 쪽 크기 확인이 필요합니다."
    ),
    "EXTRACTION_INPUT_INVALID": (
        "주장 추출 입력을 검증하지 못했습니다. 원문·처리 "
        "기록은 보존하며 운영자 확인이 필요합니다."
    ),
    "PROBE_REQUEST_TOO_LARGE": (
        "선택한 원문의 모델 요청이 크기 한도를 "
        "초과했습니다. 선택 쪽을 줄여 새 분석을 접수해 "
        "주세요."
    ),
    "PDF_PASSWORD_REQUIRED": (
        "암호화된 PDF를 처리하지 못했습니다. 열기 " "암호를 해제한 PDF로 다시 업로드해 주세요."
    ),
    "PDF_INVALID": (
        "PDF 보안 검사를 완료하지 못했습니다. PDF " "뷰어에서 다시 저장한 파일로 업로드해 주세요."
    ),
    "UPLOAD_LIMIT_EXCEEDED": (
        "PDF가 서버의 파일 크기·페이지 수 또는 내부 "
        "처리 한도를 초과했습니다. 업로드 안내의 한도를 "
        "확인해 주세요."
    ),
    "NO_EXTRACTABLE_CLAIM_BLOCKS": (
        "선택 범위에 읽을 수 있는 주장 블록이 없습니다. " "다른 쪽을 선택해 주세요."
    ),
    "NO_ELIGIBLE_CLAIM_BLOCKS": (
        "선택 범위에 주장 추출 대상 블록이 없습니다. " "다른 쪽을 선택해 주세요."
    ),
    "NO_CLAIMS_IN_PROCESSED_BLOCKS": (
        "처리한 선택 범위에서 환경 주장을 추출하지 "
        "못했습니다. 보고서 전체의 근거 부재를 뜻하지 "
        "않습니다."
    ),
}
PUBLIC_CODES = frozenset(MESSAGES) | {"BUDGET_EXHAUSTED", "ACCOUNTING_UNAVAILABLE"}


def public_reason_details(codes):
    """Display metadata only: do not rewrite historical result/decision bytes."""
    return [
        dict(
            code=code,
            message=MESSAGES.get(code)
            or "처리를 완료하지 못해 판정을 보류했습니다. 운영자의 처리 기록 확인이 필요합니다.",
        )
        for code in codes
    ]
