# 21 · 수용 기준

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 기능별 Given / When / Then
모든시나리오는권한있는동일 tenant 와승인된 source 를기본전제로한다. 실제 gold 정답이필요한 AI 동작은합성 fixture 계약검증과실제 PDF 평가를분리한다.

### AT-001 · FR-001 PDF 업로드·버전 고정

**Given:** DocumentVersion 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/documents; POST /v1/documents/{document_id}/versions` 또는해당 Task 의순수함수를호출한다.

**Then:** 위조 MIME·초과 크기는 거부하고 동일 업로드 완료 재호출은 같은 버전을 반환한다.

검증경로: `tests/acceptance/test_upload.py`. 연결 Task: TASK-001.

### AT-002 · FR-002 페이지·좌표·원문 위치

**Given:** SourceArtifact 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/sources/{source_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 회전·CropBox·한국어 조합 문자 fixture 의 원문 영역 왕복이 일치한다.

검증경로: `tests/acceptance/test_provenance.py`. 연결 Task: TASK-002.

### AT-003 · FR-003 파싱·충돌 관리

**Given:** ParseManifest 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/quality` 또는해당 Task 의순수함수를호출한다.

**Then:** 수치가 다른 후보를 덮어쓰지 않고 conflict 를 보존한다.

검증경로: `tests/acceptance/test_parsing.py`. 연결 Task: TASK-003.

### AT-004 · FR-004 표 정규화

**Given:** Observation 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/observations` 또는해당 Task 의순수함수를호출한다.

**Then:** 서로 다른 연도·조직·시장기반/위치기반을 하나의 값으로 병합하지 않는다.

검증경로: `tests/acceptance/test_tables.py`. 연결 Task: TASK-004.

### AT-005 · FR-005 코드 수치 검산

**Given:** CheckResult 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims/{claim_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 반올림 범위는 인정하고 0 분모·없는 값은 not_computable 로 기록한다.

검증경로: `tests/acceptance/test_numeric.py`. 연결 Task: TASK-005.

### AT-006 · FR-006 GRI Index 경로

**Given:** IndexEntry 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/quality` 또는해당 Task 의순수함수를호출한다.

**Then:** 페이지를 찾지 못한 것은 mismatch 확정 대신 unresolved 로 남긴다.

검증경로: `tests/acceptance/test_gri.py`. 연결 Task: TASK-006.

### AT-007 · FR-007 보증의견서와 범위 매칭

**Given:** AssuranceStatement 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/assurance` 또는해당 Task 의순수함수를호출한다.

**Then:** 기관명만 같은 별도 연도/사업장의 주장을 covered 로 만들지 않는다.

검증경로: `tests/acceptance/test_assurance.py`. 연결 Task: TASK-007.

### AT-008 · FR-008 클레임 전수 추출

**Given:** Claim 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims` 또는해당 Task 의순수함수를호출한다.

**Then:** 성과+목표 복합문장을 분리하고 full 모드에서 topic quota 로 잘라내지 않는다.

검증경로: `tests/acceptance/test_claims.py`. 연결 Task: TASK-008.

### AT-009 · FR-009 트랙·주제 독립 태깅

**Given:** TagRevision 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims/{claim_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 공급망 토픽의 미래 목표를 management 로 강제하지 않는다.

검증경로: `tests/acceptance/test_tracks.py`. 연결 Task: TASK-009.

### AT-010 · FR-010 동일 packet 태깅 3회

**Given:** TagRun 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims/{claim_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 서로 다른 replicate 의 raw cache 재사용을 차단한다.

검증경로: `tests/acceptance/test_tagging.py`. 연결 Task: TASK-010.

### AT-011 · FR-011 동일 문서 근거 검색

**Given:** EvidencePacket 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims/{claim_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 다른 문서의 숫자 또는 같은 문서 먼 페이지 목표연도를 직접근거로 인정하지 않는다.

검증경로: `tests/acceptance/test_retrieval.py`. 연결 Task: TASK-011.

### AT-012 · FR-012 인용 실재·정규화 검증

**Given:** EvidenceRef 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/sources/{source_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 발명된 인용은 무효이며 느슨한 fuzzy 매치만으로 확정하지 않는다.

검증경로: `tests/acceptance/test_citations.py`. 연결 Task: TASK-012.

### AT-013 · FR-013 주장 귀속 검증

**Given:** EvidenceBinding 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims/{claim_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 같은 페이지의 다른 제품 비율을 해당 제품 근거로 인정하지 않는다.

검증경로: `tests/acceptance/test_binding.py`. 연결 Task: TASK-013.

### AT-014 · FR-014 일반 사다리·라벨

**Given:** DecisionRevision 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims/{claim_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 성과 E3는 방법과 covered 보증이 모두 있어야 하며 같은 입력의 결과 해시가 같다.

검증경로: `tests/acceptance/test_rules.py`. 연결 Task: TASK-014.

### AT-015 · FR-015 최상급·제품·범주형 특칙

**Given:** DecisionRevision 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims/{claim_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 비교와 외부검증 둘 다 없을 때만 최상급 E0 강제 규칙을 발동한다.

검증경로: `tests/acceptance/test_exceptions.py`. 연결 Task: TASK-015.

### AT-016 · FR-016 세이프하버 기록 경로

**Given:** SafeHarborRecord 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/safe-harbor` 또는해당 Task 의순수함수를호출한다.

**Then:** 승인된 등급 매핑이 없으면 숫자 부재로 E0를 부여하지 않고 rule gap 을 표시한다.

검증경로: `tests/acceptance/test_safe_harbor.py`. 연결 Task: TASK-016.

### AT-017 · FR-017 산업 적용·결측

**Given:** Applicability 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/summary` 또는해당 Task 의순수함수를호출한다.

**Then:** 알 수 없는 산업을 임의로 not_applicable 처리하지 않는다.

검증경로: `tests/acceptance/test_industry.py`. 연결 Task: TASK-017.

### AT-018 · FR-018 유예·기준 효력

**Given:** Applicability 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/summary` 또는해당 Task 의순수함수를호출한다.

**Then:** 효력 미확인 설정은 법정 위반이나 면책 확정 문구를 만들지 않는다.

검증경로: `tests/acceptance/test_regulatory.py`. 연결 Task: TASK-018.

### AT-019 · FR-019 인간 태깅 검토

**Given:** Review 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/reviews/{review_id}/resolve` 또는해당 Task 의순수함수를호출한다.

**Then:** If-Match 충돌은 412, label 직접 수정 입력은 422다.

검증경로: `tests/acceptance/test_reviews.py`. 연결 Task: TASK-019.

### AT-020 · FR-020 버전별 재채점

**Given:** Rescore 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/runs/{run_id}/rescores` 또는해당 Task 의순수함수를호출한다.

**Then:** 요소 ontology 가 바뀌면 재태깅 필요를 알리고 오래된 요소를 새 정답처럼 쓰지 않는다.

검증경로: `tests/acceptance/test_rescore.py`. 연결 Task: TASK-020.

### AT-021 · FR-021 감사 리포트·수정 제안

**Given:** ExportSnapshot 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/runs/{run_id}/exports` 또는해당 Task 의순수함수를호출한다.

**Then:** 수정 제안은 없는 숫자를 채우지 않으며 미완료 건과 미확인 조항을 숨기지 않는다.

검증경로: `tests/acceptance/test_report.py`. 연결 Task: TASK-021.

### AT-022 · FR-022 감사 이력

**Given:** AuditEvent 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/audit` 또는해당 Task 의순수함수를호출한다.

**Then:** 현재 결과를 바꿔도 기존 export snapshot 과 감사 이벤트는 바뀌지 않는다.

검증경로: `tests/acceptance/test_audit.py`. 연결 Task: TASK-022.

### AT-023 · FR-023 다년도 비교

**Given:** Comparison 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/runs/{run_id}/comparisons` 또는해당 Task 의순수함수를호출한다.

**Then:** 전년 문서 미제공 시 not_run 이며 이전 문서 근거로 올해 등급을 올리지 않는다.

검증경로: `tests/acceptance/test_comparison.py`. 연결 Task: TASK-023.

### AT-024 · FR-024 광고 검토 별도 모드

**Given:** Run 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/runs` 또는해당 Task 의순수함수를호출한다.

**Then:** 공시 모드에 표시광고 규칙을 라벨 입력으로 주입하지 않는다.

검증경로: `tests/acceptance/test_advertising.py`. 연결 Task: TASK-024.

### AT-025 · FR-025 규칙팩 검증·활성화

**Given:** RulePack 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/rule-packs/{rule_pack_id}/activate` 또는해당 Task 의순수함수를호출한다.

**Then:** 활성화는 새 run 기본값만 바꾸며 실행 중인 규칙 스냅샷은 바꾸지 않는다.

검증경로: `tests/acceptance/test_rulepacks.py`. 연결 Task: TASK-025.

### AT-026 · FR-026 대시보드·상태 분리

**Given:** Summary 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/summary` 또는해당 Task 의순수함수를호출한다.

**Then:** E 분포 분모에 미판정·읽기실패를 숨겨 넣지 않는다.

검증경로: `tests/acceptance/test_dashboard.py`. 연결 Task: TASK-026.

### AT-027 · FR-027 전수성·부분 완료

**Given:** Run 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 예산으로 중단된 작업은 completed 가 아닌 partial 이며 완전 검토 배지를 표시하지 않는다.

검증경로: `tests/acceptance/test_coverage.py`. 연결 Task: TASK-027.

### AT-028 · FR-028 내구 작업·재시도·취소

**Given:** StageJob 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/runs/{run_id}/cancel; POST /v1/runs/{run_id}/retry` 또는해당 Task 의순수함수를호출한다.

**Then:** 죽은 워커의 늦은 결과가 새 시도의 결과를 덮지 않는다.

검증경로: `tests/acceptance/test_jobs.py`. 연결 Task: TASK-028.

### AT-029 · FR-029 모델·외부전송 사전 점검

**Given:** RuntimeBinding 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/preflight` 또는해당 Task 의순수함수를호출한다.

**Then:** 허용되지 않은 리전 fallback 으로 문서를 전송하지 않는다.

검증경로: `tests/acceptance/test_preflight.py`. 연결 Task: TASK-029.

### AT-030 · FR-030 원가·토큰 예산

**Given:** UsageLedger 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/cost` 또는해당 Task 의순수함수를호출한다.

**Then:** 단가 미설정은 unknown_cost 이며 0원으로 표시하지 않는다.

검증경로: `tests/acceptance/test_cost.py`. 연결 Task: TASK-030.

### AT-031 · FR-031 스냅샷 export·다운로드

**Given:** ExportSnapshot 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/exports/{export_id}; POST /v1/exports/{export_id}/download` 또는해당 Task 의순수함수를호출한다.

**Then:** export 중 review 변경이 발생하면 revision 을 섞지 않고 snapshot 생성만 재시도한다.

검증경로: `tests/acceptance/test_exports.py`. 연결 Task: TASK-031.

### AT-032 · FR-032 데이터셋·평가 분리

**Given:** Evaluation 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/evaluations/{evaluation_id}` 또는해당 Task 의순수함수를호출한다.

**Then:** 검토 확정 데이터를 holdout 에 자동 추가하지 않는다.

검증경로: `tests/acceptance/test_evaluation.py`. 연결 Task: TASK-032.

### AT-033 · NFR-001 재현성과 실행 식별

**Given:** RunManifest 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/audit` 또는해당 Task 의순수함수를호출한다.

**Then:** 시간·행위자는 semantic hash 에서 제외하고 provenance hash 에는 별도로 남긴다.

검증경로: `tests/acceptance/test_reproducibility.py`. 연결 Task: TASK-033.

### AT-034 · NFR-002 가용성·지연 목표

**Given:** Health 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/health/ready` 또는해당 Task 의순수함수를호출한다.

**Then:** 미측정 수치를 달성 실적으로 표시하지 않고 계정·파일럿 수치를 기록한다.

검증경로: `tests/acceptance/test_slo.py`. 연결 Task: TASK-034.

### AT-035 · NFR-003 관측성과 비밀 제거

**Given:** Trace 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/cost` 또는해당 Task 의순수함수를호출한다.

**Then:** fixture 의 API key·본문 문자열이 로그 수집 결과에 없음을 검사한다.

검증경로: `tests/acceptance/test_observability.py`. 연결 Task: TASK-035.

### AT-036 · NFR-004 계약 호환·접근성

**Given:** SchemaVersion 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/runs/{run_id}/claims` 또는해당 Task 의순수함수를호출한다.

**Then:** 키보드로 근거 열기·태깅 수정·확정 취소가 가능하다.

검증경로: `tests/acceptance/test_accessibility.py`. 연결 Task: TASK-036.

### AT-037 · SEC-001 인증·역할·테넌트

**Given:** Membership 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `GET /v1/session; POST /v1/session/tenant` 또는해당 Task 의순수함수를호출한다.

**Then:** 테넌트 A 사용자가 B id 를 요청하면 존재 여부를 숨기는 404를 반환한다.

검증경로: `tests/acceptance/test_auth.py`. 연결 Task: TASK-037.

### AT-038 · SEC-002 업로드 격리

**Given:** Upload 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/uploads/{upload_id}/complete` 또는해당 Task 의순수함수를호출한다.

**Then:** PDF 악성 링크·내장 액션을 실행하지 않고 초과 리소스 PDF 를 중단한다.

검증경로: `tests/acceptance/test_upload_security.py`. 연결 Task: TASK-038.

### AT-039 · SEC-003 외부통신·prompt injection

**Given:** ConsentProfile 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/preflight` 또는해당 Task 의순수함수를호출한다.

**Then:** PDF 의 다른 문서 조회·URL 전송·label 지정 지시가 권한을 바꾸지 않는다.

검증경로: `tests/acceptance/test_injection.py`. 연결 Task: TASK-039.

### AT-040 · SEC-004 삭제·보존·복구

**Given:** DeletionRequest 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/documents/{document_id}/deletion-requests` 또는해당 Task 의순수함수를호출한다.

**Then:** 법적 보존 설정과 실제 삭제 완료 상태를 분리하고 TTL 만으로 삭제 완료 처리하지 않는다.

검증경로: `tests/acceptance/test_retention.py`. 연결 Task: TASK-040.

### AT-041 · SEC-005 브라우저 세션 보호

**Given:** Session 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/auth/logout` 또는해당 Task 의순수함수를호출한다.

**Then:** CSRF 없는 변경 요청403, 토큰은 localStorage 와 URL 에 저장되지 않는다.

검증경로: `tests/acceptance/test_session_security.py`. 연결 Task: TASK-041.

### AT-042 · SEC-006 비밀·라이선스·공급망

**Given:** LicenseInventory 와관련정상 fixture 및경계/오류 fixture 가준비되고필요한계정/권한 gate 가명시돼있다.

**When:** `POST /v1/preflight` 또는해당 Task 의순수함수를호출한다.

**Then:** PyMuPDF 사용 승인이 없는 공개 배포에 해당 adapter 가 포함되지 않는다.

검증경로: `tests/acceptance/test_supply_chain.py`. 연결 Task: TASK-042.

## 공통 HTTP/UX 수용 시나리오
Given session 없음, When protectedAPI, Then401로그인유도. Given 다른 tenant 자원, Then404이고메타데이터를유출하지않는다. Given loading, Then 버튼중복제출비활성/idempotency 유지. Given 빈목록, Then0개와미처리상태를구분한다. Given provider timeout, Thenretry 후 partial/review 이지 E0가아니다. Given 중복 POST, Then 같은 resource_id 이고중복결과/감사를만들지않는다. Given 동시 review, Then 한명성공/한명412이고 draft 보존. Given stale signedURL, Then 권한재확인후1회재발급. Given rulegap, Then 없던조항/E 기준을창작하지않는다.


### AT-045 · FR-033 기업·실행 옵션

Given tenant A 와 B 에 별도 Company/Profile 이 있다. When A 사용자가 companies/runtime-options 를 조회한다. Then A 의 옵션만 보인다. When B 의 company/profile ID 로 A 문서를 생성한다. Then404 또는 권한검증 오류이고 문서가 생성되지 않는다. When A editor 가 새 기업명을 등록한다. Then201로 UUID 를 얻고 업로드 화면에서 선택할 수 있다.
