"""Bounded provider error decoding; never retain response bodies or credentials."""

import json
import re

MESSAGES = {
    "PROVIDER_CREDIT_EXHAUSTED": "분석 API 크레딧이 부족합니다. 운영자의 충전 확인이 필요합니다.",
    "PROVIDER_AUTH_FAILED": "분석 API 인증에 실패했습니다. 운영자의 키 확인이 필요합니다.",
    "PROVIDER_ACCESS_DENIED": "분석 API 사용 권한이 거부되었습니다. 운영자 확인이 필요합니다.",
    "PROVIDER_RATE_LIMITED": (
        "분석 API 요청 한도에 도달했습니다. 운영자 확인 후 다시 접수해 주세요."
    ),
    "PROVIDER_UNAVAILABLE": "분석 API에 일시적인 서버 오류가 발생했습니다.",
}


def provider_error_code(provider, raw):
    if raw in MESSAGES:
        return raw
    if provider == "openai" and raw == "OPENAI_INSUFFICIENT_QUOTA":
        return "PROVIDER_CREDIT_EXHAUSTED"
    if provider.startswith("upstage") and raw == "UPSTAGE_API_KEY_IS_NOT_ALLOWED":
        return "PROVIDER_CREDIT_EXHAUSTED"
    prefix = "UPSTAGE" if provider.startswith("upstage") else provider.upper()
    match = re.fullmatch(prefix + r"_HTTP_(\d{3})", raw)
    if not match:
        return None
    status = int(match[1])
    if status == 401:
        return "PROVIDER_AUTH_FAILED"
    if status == 402:
        return "PROVIDER_CREDIT_EXHAUSTED"
    if status == 403:
        return "PROVIDER_ACCESS_DENIED"
    if status == 429:
        return "PROVIDER_RATE_LIMITED"
    return "PROVIDER_UNAVAILABLE" if 500 <= status <= 599 else None


def upstage_http_error(response):
    raw = response.read(4097)
    code = None
    if len(raw) <= 4096:
        try:
            data = json.loads(raw)
            error = data.get("error", data)
            code = error.get("code") if isinstance(error, dict) else None
        except (ValueError, TypeError, AttributeError):
            pass
    if response.status == 403 and code == "api_key_is_not_allowed":
        return ValueError("UPSTAGE_API_KEY_IS_NOT_ALLOWED")
    return ValueError(f"UPSTAGE_HTTP_{response.status}")
