# 13 · 오류·재시도 정책

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 분류
| Code | HTTP / job 결과 | 재시도 | 사용자 동작 |
|---|---|---|---|
| AUTH_REQUIRED / SESSION_EXPIRED | 401 | 자동 모델 retry 없음 | 재로그인 |
| FORBIDDEN / CSRF_INVALID | 403 | 없음 | 권한/세션 확인 |
| RESOURCE_NOT_FOUND | 404 | 없음 | 잘못된 URL 또는 권한 없는 자원 |
| IDEMPOTENCY_CONFLICT | 409 | 새 작업을 의도한 경우 새 key | 기존 요청 확인 |
| STALE_REVIEW_REVISION | 412 | 자동 merge 금지 | 최신 태깅과 draft 비교 |
| VALIDATION_ERROR | 422 | 없음 | 필드별 오류 수정 |
| PDF_INVALID / PDF_PASSWORD_REQUIRED | 422 또는 upload rejected | 없음 | 유효·비암호 원본 업로드 |
| UPLOAD_LIMIT_EXCEEDED | 422 | 없음 | 제한 이하 파일 또는 명시 범위 |
| PARSE_TIMEOUT / PARSE_RESOURCE_LIMIT | partial/failed | 같은 설정1회까지만 | 원문/선택영역 검토 |
| PARSE_CONFLICT / SOURCE_UNREADABLE | blocked_evidence | 승인 fallback1회 | 검토 큐 |
| CITATION_INVALID / BINDING_UNCERTAIN | needs_review | schema repair 로 사실 고치기 금지 | 원문 확인 |
| LLM_SCHEMA_INVALID | needs_review | repair 최대1회 | 실패 후 사람 검토 |
| LLM_TRUNCATED | partial/review | chunk 재분할1회 | 미분석 영역 표시 |
| MODEL_THROTTLED / PROVIDER_5XX | 503 또는 job retry | 최대3회 | 진행중 재시도 표시 |
| MODEL_UNAVAILABLE / REGION_DENIED | 409/503 | 임의 provider 대체 금지 | preflight 수정 |
| BUDGET_EXHAUSTED | 429 또는 partial | 자동 증액 금지 | 관리자 예산 변경 후 재개 |
| RULE_GAP / BASIS_UNVERIFIED | decision blocked 또는 근거 경고 | 없음 | 기준 담당자 검증 |
| RETAG_REQUIRED | rescore409 | rules-only 반복 금지 | 새 태깅 실행 |
| EXPORT_SNAPSHOT_BUSY | job retry | 최대3회 후 지연 재예약 | 최신 상태 안정 후 export |
| REPORT_NOT_FINALIZABLE | 409 | 없음 | review 해결 또는 partial 동의 |
| LEASE_LOST | job 폐기 | 새 worker 만 진행 | 중복 실행을 사용자 오류로 표시하지 않음 |
| DEPENDENCY_UNAVAILABLE | 503 | 회로 차단 기준 | 상태페이지/재시도 |

## 2. 시간·backoff·회로 차단
모델 connect timeout10초/read120초; 기본 backoff2,4,8초에 full jitter, provider Retry-After 가 있으면 상한60초 안에서 우선한다. 최대3회는 최초 호출 이후 retry3회가 아니라 **총3attempt**로 통일한다. 같은 replica 의 repair 는 별도 reason 에 기록하며 최대1회다. 호출별 총 attempt budget 과 token budget 을 함께 검사한다.

provider/region 별 최근20회 중 transient 실패10회 이상이면60초 open, half-open1회 성공시 close. 모델 schema/citation 실패는 provider outage 지표와 분리한다. DDB transaction conflict 는 짧은 jitter 최대5회, 사용자 review CAS 실패는 재시도하지 않고412다. SQS receive5회 초과는 DLQ, coordinator 는 관련 run 을 partial/failed 로 표시하고 원인·resume 가능 stage 를 남긴다.

## 3. 저하 동작
OpenSearch 장애는 local/section exact 조회가 가능하더라도 전역 검색 완료로 표시하지 않는다. evidence search 는 unknown coverage, 모델 실패는 inferred absence 가 아니다. 표 vision 장애는 표 비교 not_run 이고 critical evidence 는 자동 확정하지 않는다. 비용 단가 조회 실패는 금액 unknown 이며 tokens 는 계속 기록한다. audit transaction 실패는 결과 변경을 함께 실패시켜 감사 없는 확정을 만들지 않는다.

## 4. 응답과 로그
07장 Error envelope 를 사용하며 request_id/trace_id 를 연결한다. backend 는 domain exception→HTTP mapping 을 한 middleware 에서 수행한다. 사용자에는 할 수 있는 조치가 포함된 한국어 문구를 표시한다. raw traceback, prompt, PDF quote, AWS access details 는 응답에 포함하지 않는다. 구조화 로그는 error_code·stage·attempt·fence·provider_request_id·지연/토큰만 포함한다.
