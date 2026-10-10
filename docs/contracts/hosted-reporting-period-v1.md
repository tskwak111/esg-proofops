# FX7 공개 문서별 보고기간 계약

무료 `POST /v1/documents/{id}/scope-plan`은 PDFium 문자층의 앞/뒤 각각 12쪽에서
보고기간 선언·날짜 범위·월 범위·명시 회계연도를 검색한다. 보고연도는 감지한
중심 기간의 종료 연도다. 명시 회계연도만 있는 경우 달력연도 범위로 제안하며
`basis=fiscal_year_calendar`를 남긴다. 끝 날짜만 있거나 서로 다른 중심 기간이
있으면 채택하지 않는다. 예외·최근 다년도·일부 성과의 기간으로 중심 기간을 넓히지 않는다.

`plan.reporting_period_detection`은 version/status/selected/candidates/exceptions,
원본 SHA-256, 검색한 물리 쪽, 관련 원시 페이지 문자층을 보존한다. 후보와 예외의
`source_ref`에는 테넌트·문서버전·원본/문자층/인용 해시·물리 쪽·code point 기준
end-exclusive 문자 범위·원문을 기록한다. bbox=null이고 verification_state는
inspection_only다. 실제 문자층과 인용 범위를 검증하지만 canonical graph의
검증된 입증 근거로 승격하지 않는다. 숫자·목표연도 전역 차용 규칙은 변경하지 않는다.

계획 wrapper의 `reporting_scope`는 report_year/period_start/period_end와
origin(detected/operator_default/manual), detection_status, warning,
detection_sha256을 가진다. 유일하고 완전한 후보만 채택한다. 미발견·모호 시
운영자 live_config의 기존 세 값을 그대로 스냅샷하고
`보고기간 추정 실패(기본값 사용)`을 표시한다. 운영자 기본값도 없으면 null로
보존하며 사람이 입력하기 전 분석 접수를 REPORTING_SCOPE_REQUIRED/422로 거절한다.

기존 `POST /scope-plan/selection`에 선택적 reporting_scope 객체(세 값만)를 추가한다.
If-Match 필수(없음 428/경합 412), 기존 editor/테넌트 가드를 적용한다. 연도는
1900..2100 정수, 날짜는 ISO 달력 날짜이고 시작≤종료다. 운영자 기본값에 이미 있는
발간연도와 실적기간의 차이를 소급 거절하지 않는다. 수정은 새 scope-NNNNNN.json과
선택 해시를 만들고 불변 감지 제안·예외·기존 revision을 보존한다.
분석 접수는 reporting_scope를 선택 해시에 포함하고 run.options에 고정한다.
worker의 pilot argv와 결과 reporting_scope는 고정값을 사용한다. 이후 계획 수정이나
운영자 설정 변경은 이미 접수한 실행의 기간을 바꾸지 않는다.

DB migration/새 dependency는 없다. FX7 이전 scope/options는 기존 재생 경로로
읽는다. 새 optional 필드를 모르는 구버전으로 rollback할 때 새 FX7 scope/options를
읽는 작업은 먼저 중지하고 이전 revision/배포를 함께 복원한다. 새 산출물을 이전
형식으로 덮어쓰거나 기존 revision을 소급 변경하지 않는다. 업로드 보안/deploy 미변경.
