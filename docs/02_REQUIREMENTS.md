# 02 · ID 기반 요구사항

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 계약 관리
기계 판독 정본은 `contracts/requirement_catalog.json`이다. 아래 요구사항은 각기 Task 와 Acceptance Test 에 연결된다. P1도 범위에서 삭제된 것이 아니며 기능 플래그·전용 규칙팩 준비 후 활성화한다.

### FR-001 · PDF 업로드·버전 고정 (P0)

PDF 바이트 SHA-256, S3 version_id, 기업·보고기간·문서 유형을 고정한다.

화면: `/documents/new`. API: `POST /v1/documents; POST /v1/documents/{document_id}/versions`. 저장 엔터티: `DocumentVersion`. 구현: TASK-001. 검증: AT-001 / `tests/acceptance/test_upload.py`.

**수용 기준:** 위조 MIME·초과 크기는 거부하고 동일 업로드 완료 재호출은 같은 버전을 반환한다.

### FR-002 · 페이지·좌표·원문 위치 (P0)

물리 페이지·인쇄 페이지·원시 좌표·표준 좌표·문자 오프셋을 분리한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/sources/{source_id}`. 저장 엔터티: `SourceArtifact`. 구현: TASK-002. 검증: AT-002 / `tests/acceptance/test_provenance.py`.

**수용 기준:** 회전·CropBox·한국어 조합 문자 fixture 의 원문 영역 왕복이 일치한다.

### FR-003 · 파싱·충돌 관리 (P0)

OpenDataLoader 기본, 표 보조 파서, 표 비전 교차확인을 실행한다.

화면: `/runs/:runId/quality`. API: `GET /v1/runs/{run_id}/quality`. 저장 엔터티: `ParseManifest`. 구현: TASK-003. 검증: AT-003 / `tests/acceptance/test_parsing.py`.

**수용 기준:** 수치가 다른 후보를 덮어쓰지 않고 conflict 를 보존한다.

### FR-004 · 표 정규화 (P0)

지표·Scope·사업장·기간·방법·단위·값을 행열/각주에 연결한다.

화면: `/runs/:runId/quality`. API: `GET /v1/runs/{run_id}/observations`. 저장 엔터티: `Observation`. 구현: TASK-004. 검증: AT-004 / `tests/acceptance/test_tables.py`.

**수용 기준:** 서로 다른 연도·조직·시장기반/위치기반을 하나의 값으로 병합하지 않는다.

### FR-005 · 코드 수치 검산 (P0)

Decimal 기반 합계·증감률·본문/표 비교를 수행한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/claims/{claim_id}`. 저장 엔터티: `CheckResult`. 구현: TASK-005. 검증: AT-005 / `tests/acceptance/test_numeric.py`.

**수용 기준:** 반올림 범위는 인정하고 0 분모·없는 값은 not_computable 로 기록한다.

### FR-006 · GRI Index 경로 (P0)

GRI 코드와 인쇄 페이지를 물리 페이지 후보로 매핑한다.

화면: `/runs/:runId/quality`. API: `GET /v1/runs/{run_id}/quality`. 저장 엔터티: `IndexEntry`. 구현: TASK-006. 검증: AT-006 / `tests/acceptance/test_gri.py`.

**수용 기준:** 페이지를 찾지 못한 것은 mismatch 확정 대신 unresolved 로 남긴다.

### FR-007 · 보증의견서와 범위 매칭 (P0)

수준·기관·기준·대상 지표·기간·경계·제외를 구조화한다.

화면: `/runs/:runId/assurance`. API: `GET /v1/runs/{run_id}/assurance`. 저장 엔터티: `AssuranceStatement`. 구현: TASK-007. 검증: AT-007 / `tests/acceptance/test_assurance.py`.

**수용 기준:** 기관명만 같은 별도 연도/사업장의 주장을 covered 로 만들지 않는다.

### FR-008 · 클레임 전수 추출 (P0)

환경 영역의 원자 주장을 추출하고 비주장 제외 사유도 남긴다.

화면: `/runs/:runId/claims`. API: `GET /v1/runs/{run_id}/claims`. 저장 엔터티: `Claim`. 구현: TASK-008. 검증: AT-008 / `tests/acceptance/test_claims.py`.

**수용 기준:** 성과+목표 복합문장을 분리하고 full 모드에서 topic quota 로 잘라내지 않는다.

### FR-009 · 트랙·주제 독립 태깅 (P0)

goal/performance/management 를 문장 성격으로 결정한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/claims/{claim_id}`. 저장 엔터티: `TagRevision`. 구현: TASK-009. 검증: AT-009 / `tests/acceptance/test_tracks.py`.

**수용 기준:** 공급망 토픽의 미래 목표를 management 로 강제하지 않는다.

### FR-010 · 동일 packet 태깅 3회 (P0)

고정 evidence packet 에 replicate_id 1·2·3으로 세 번 실행한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/claims/{claim_id}`. 저장 엔터티: `TagRun`. 구현: TASK-010. 검증: AT-010 / `tests/acceptance/test_tagging.py`.

**수용 기준:** 서로 다른 replicate 의 raw cache 재사용을 차단한다.

### FR-011 · 동일 문서 근거 검색 (P0)

GRI→섹션→어휘/벡터 검색을 하되 허용 근거 범위를 검증한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/claims/{claim_id}`. 저장 엔터티: `EvidencePacket`. 구현: TASK-011. 검증: AT-011 / `tests/acceptance/test_retrieval.py`.

**수용 기준:** 다른 문서의 숫자 또는 같은 문서 먼 페이지 목표연도를 직접근거로 인정하지 않는다.

### FR-012 · 인용 실재·정규화 검증 (P0)

source_id·범위·quote·해시·오프셋을 코드로 확인한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/sources/{source_id}`. 저장 엔터티: `EvidenceRef`. 구현: TASK-012. 검증: AT-012 / `tests/acceptance/test_citations.py`.

**수용 기준:** 발명된 인용은 무효이며 느슨한 fuzzy 매치만으로 확정하지 않는다.

### FR-013 · 주장 귀속 검증 (P0)

지표·기업·사업장·Scope·기간과 표 행열 귀속을 검증한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/claims/{claim_id}`. 저장 엔터티: `EvidenceBinding`. 구현: TASK-013. 검증: AT-013 / `tests/acceptance/test_binding.py`.

**수용 기준:** 같은 페이지의 다른 제품 비율을 해당 제품 근거로 인정하지 않는다.

### FR-014 · 일반 사다리·라벨 (P0)

v2.0 사다리를 순수 함수로 계산하고 G/P/M 결손을 분리한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/claims/{claim_id}`. 저장 엔터티: `DecisionRevision`. 구현: TASK-014. 검증: AT-014 / `tests/acceptance/test_rules.py`.

**수용 기준:** 성과 E3는 방법과 covered 보증이 모두 있어야 하며 같은 입력의 결과 해시가 같다.

### FR-015 · 최상급·제품·범주형 특칙 (P0)

원문의 최상급 AND 부재, 제품 비율 직접연결, 범주형 인증 규칙을 구현한다.

화면: `/runs/:runId/claims/:claimId`. API: `GET /v1/runs/{run_id}/claims/{claim_id}`. 저장 엔터티: `DecisionRevision`. 구현: TASK-015. 검증: AT-015 / `tests/acceptance/test_exceptions.py`.

**수용 기준:** 비교와 외부검증 둘 다 없을 때만 최상급 E0 강제 규칙을 발동한다.

### FR-016 · 세이프하버 기록 경로 (P0)

범주별 가정·방법·출처·한계 체크리스트를 독립 저장한다.

화면: `/runs/:runId/safe-harbor`. API: `GET /v1/runs/{run_id}/safe-harbor`. 저장 엔터티: `SafeHarborRecord`. 구현: TASK-016. 검증: AT-016 / `tests/acceptance/test_safe_harbor.py`.

**수용 기준:** 승인된 등급 매핑이 없으면 숫자 부재로 E0를 부여하지 않고 rule gap 을 표시한다.

### FR-017 · 산업 적용·결측 (P0)

버전 고정 산업 mapping 으로 적용성·필수성을 분리한다.

화면: `/runs/:runId/summary`. API: `GET /v1/runs/{run_id}/summary`. 저장 엔터티: `Applicability`. 구현: TASK-017. 검증: AT-017 / `tests/acceptance/test_industry.py`.

**수용 기준:** 알 수 없는 산업을 임의로 not_applicable 처리하지 않는다.

### FR-018 · 유예·기준 효력 (P0)

승인된 기간·기업 조건으로 필수/참고 검토 축을 계산한다.

화면: `/runs/:runId/summary`. API: `GET /v1/runs/{run_id}/summary`. 저장 엔터티: `Applicability`. 구현: TASK-018. 검증: AT-018 / `tests/acceptance/test_regulatory.py`.

**수용 기준:** 효력 미확인 설정은 법정 위반이나 면책 확정 문구를 만들지 않는다.

### FR-019 · 인간 태깅 검토 (P0)

검토자는 근거·요소·트랙을 수정하고 규칙엔진이 재채점한다.

화면: `/runs/:runId/reviews`. API: `POST /v1/reviews/{review_id}/resolve`. 저장 엔터티: `Review`. 구현: TASK-019. 검증: AT-019 / `tests/acceptance/test_reviews.py`.

**수용 기준:** If-Match 충돌은 412, label 직접 수정 입력은 422다.

### FR-020 · 버전별 재채점 (P0)

파싱·태깅 재사용 가능성을 검사하고 새 결정 revision 을 만든다.

화면: `/runs/:runId`. API: `POST /v1/runs/{run_id}/rescores`. 저장 엔터티: `Rescore`. 구현: TASK-020. 검증: AT-020 / `tests/acceptance/test_rescore.py`.

**수용 기준:** 요소 ontology 가 바뀌면 재태깅 필요를 알리고 오래된 요소를 새 정답처럼 쓰지 않는다.

### FR-021 · 감사 리포트·수정 제안 (P0)

결손·근거 위치·버전·검토·보증·세이프하버를 출력한다.

화면: `/runs/:runId/report`. API: `POST /v1/runs/{run_id}/exports`. 저장 엔터티: `ExportSnapshot`. 구현: TASK-021. 검증: AT-021 / `tests/acceptance/test_report.py`.

**수용 기준:** 수정 제안은 없는 숫자를 채우지 않으며 미완료 건과 미확인 조항을 숨기지 않는다.

### FR-022 · 감사 이력 (P0)

변경 전후 해시·행위자·revision·사유를 append-only 로 저장한다.

화면: `/runs/:runId/audit`. API: `GET /v1/runs/{run_id}/audit`. 저장 엔터티: `AuditEvent`. 구현: TASK-022. 검증: AT-022 / `tests/acceptance/test_audit.py`.

**수용 기준:** 현재 결과를 바꿔도 기존 export snapshot 과 감사 이벤트는 바뀌지 않는다.

### FR-023 · 다년도 비교 (P1)

같은 기업의 전년 버전이 있을 때 목표 변경·삭제 후보를 산출한다.

화면: `/runs/:runId/comparison`. API: `POST /v1/runs/{run_id}/comparisons`. 저장 엔터티: `Comparison`. 구현: TASK-023. 검증: AT-023 / `tests/acceptance/test_comparison.py`.

**수용 기준:** 전년 문서 미제공 시 not_run 이며 이전 문서 근거로 올해 등급을 올리지 않는다.

### FR-024 · 광고 검토 별도 모드 (P1)

광고 전용 승인 규칙팩만 해당 모드에 적용한다.

화면: `/documents/new`. API: `POST /v1/runs`. 저장 엔터티: `Run`. 구현: TASK-024. 검증: AT-024 / `tests/acceptance/test_advertising.py`.

**수용 기준:** 공시 모드에 표시광고 규칙을 라벨 입력으로 주입하지 않는다.

### FR-025 · 규칙팩 검증·활성화 (P0)

버전·발효일·근거검증 상태·hash·승인자를 검증한다.

화면: `/settings/rules`. API: `POST /v1/rule-packs/{rule_pack_id}/activate`. 저장 엔터티: `RulePack`. 구현: TASK-025. 검증: AT-025 / `tests/acceptance/test_rulepacks.py`.

**수용 기준:** 활성화는 새 run 기본값만 바꾸며 실행 중인 규칙 스냅샷은 바꾸지 않는다.

### FR-026 · 대시보드·상태 분리 (P0)

결손·검토·등급·분모·적용제외·미처리 비율을 함께 표시한다.

화면: `/runs/:runId/summary`. API: `GET /v1/runs/{run_id}/summary`. 저장 엔터티: `Summary`. 구현: TASK-026. 검증: AT-026 / `tests/acceptance/test_dashboard.py`.

**수용 기준:** E 분포 분모에 미판정·읽기실패를 숨겨 넣지 않는다.

### FR-027 · 전수성·부분 완료 (P0)

전체/처리/제외/실패/미분석 페이지·청크·주장 수를 보존한다.

화면: `/runs/:runId`. API: `GET /v1/runs/{run_id}`. 저장 엔터티: `Run`. 구현: TASK-027. 검증: AT-027 / `tests/acceptance/test_coverage.py`.

**수용 기준:** 예산으로 중단된 작업은 completed 가 아닌 partial 이며 완전 검토 배지를 표시하지 않는다.

### FR-028 · 내구 작업·재시도·취소 (P0)

SQS 중복 전달·워커 재시작에 견디는 lease/fencing/checkpoint 를 구현한다.

화면: `/runs/:runId`. API: `POST /v1/runs/{run_id}/cancel; POST /v1/runs/{run_id}/retry`. 저장 엔터티: `StageJob`. 구현: TASK-028. 검증: AT-028 / `tests/acceptance/test_jobs.py`.

**수용 기준:** 죽은 워커의 늦은 결과가 새 시도의 결과를 덮지 않는다.

### FR-029 · 모델·외부전송 사전 점검 (P0)

모델 ID·리전·권한·스키마·image·token·동의 프로필을 확인한다.

화면: `/settings/runtime`. API: `POST /v1/preflight`. 저장 엔터티: `RuntimeBinding`. 구현: TASK-029. 검증: AT-029 / `tests/acceptance/test_preflight.py`.

**수용 기준:** 허용되지 않은 리전 fallback 으로 문서를 전송하지 않는다.

### FR-030 · 원가·토큰 예산 (P0)

호출별 모델·토큰·지연·재시도·캐시·단가 스냅샷을 기록한다.

화면: `/runs/:runId/cost`. API: `GET /v1/runs/{run_id}/cost`. 저장 엔터티: `UsageLedger`. 구현: TASK-030. 검증: AT-030 / `tests/acceptance/test_cost.py`.

**수용 기준:** 단가 미설정은 unknown_cost 이며 0원으로 표시하지 않는다.

### FR-031 · 스냅샷 export·다운로드 (P0)

JSON·CSV·HTML 감사 꾸러미와 manifest 를 만든다.

화면: `/runs/:runId/report`. API: `GET /v1/exports/{export_id}; POST /v1/exports/{export_id}/download`. 저장 엔터티: `ExportSnapshot`. 구현: TASK-031. 검증: AT-031 / `tests/acceptance/test_exports.py`.

**수용 기준:** export 중 review 변경이 발생하면 revision 을 섞지 않고 snapshot 생성만 재시도한다.

### FR-032 · 데이터셋·평가 분리 (P0)

silver/fewshot/validation/holdout 를 회사 단위 분리한다.

화면: `/settings/evaluation`. API: `GET /v1/evaluations/{evaluation_id}`. 저장 엔터티: `Evaluation`. 구현: TASK-032. 검증: AT-032 / `tests/acceptance/test_evaluation.py`.

**수용 기준:** 검토 확정 데이터를 holdout 에 자동 추가하지 않는다.

### NFR-001 · 재현성과 실행 식별 (P0)

동일 확정 입력·규칙·엔진으로 decision semantic hash 가 같아야 한다.

화면: `/runs/:runId/audit`. API: `GET /v1/runs/{run_id}/audit`. 저장 엔터티: `RunManifest`. 구현: TASK-033. 검증: AT-033 / `tests/acceptance/test_reproducibility.py`.

**수용 기준:** 시간·행위자는 semantic hash 에서 제외하고 provenance hash 에는 별도로 남긴다.

### NFR-002 · 가용성·지연 목표 (P0)

조회 p95 1초, 요청 수락 p95 2초를 초기 부하 시험 목표로 둔다.

화면: `/runs/:runId`. API: `GET /v1/health/ready`. 저장 엔터티: `Health`. 구현: TASK-034. 검증: AT-034 / `tests/acceptance/test_slo.py`.

**수용 기준:** 미측정 수치를 달성 실적으로 표시하지 않고 계정·파일럿 수치를 기록한다.

### NFR-003 · 관측성과 비밀 제거 (P0)

trace_id 와 stage 오류·호출 지표를 남기고 문서 본문은 로그에서 제외한다.

화면: `/runs/:runId/cost`. API: `GET /v1/runs/{run_id}/cost`. 저장 엔터티: `Trace`. 구현: TASK-035. 검증: AT-035 / `tests/acceptance/test_observability.py`.

**수용 기준:** fixture 의 API key·본문 문자열이 로그 수집 결과에 없음을 검사한다.

### NFR-004 · 계약 호환·접근성 (P0)

API schema version 과 keyboard 접근·비색상 상태 구분을 제공한다.

화면: `/runs/:runId/reviews`. API: `GET /v1/runs/{run_id}/claims`. 저장 엔터티: `SchemaVersion`. 구현: TASK-036. 검증: AT-036 / `tests/acceptance/test_accessibility.py`.

**수용 기준:** 키보드로 근거 열기·태깅 수정·확정 취소가 가능하다.

### SEC-001 · 인증·역할·테넌트 (P0)

Cognito+서버 세션과 tenant membership 으로 읽기/검토/관리 권한을 검사한다.

화면: `/login`. API: `GET /v1/session; POST /v1/session/tenant`. 저장 엔터티: `Membership`. 구현: TASK-037. 검증: AT-037 / `tests/acceptance/test_auth.py`.

**수용 기준:** 테넌트 A 사용자가 B id 를 요청하면 존재 여부를 숨기는 404를 반환한다.

### SEC-002 · 업로드 격리 (P0)

업로드를 격리 prefix 에서 검증 후 원본 vault 로 복사한다.

화면: `/documents/new`. API: `POST /v1/uploads/{upload_id}/complete`. 저장 엔터티: `Upload`. 구현: TASK-038. 검증: AT-038 / `tests/acceptance/test_upload_security.py`.

**수용 기준:** PDF 악성 링크·내장 액션을 실행하지 않고 초과 리소스 PDF 를 중단한다.

### SEC-003 · 외부통신·prompt injection (P0)

PDF 문구를 데이터로만 취급하고 도구/모델/URL 을 서버 allowlist 로 제한한다.

화면: `/settings/runtime`. API: `POST /v1/preflight`. 저장 엔터티: `ConsentProfile`. 구현: TASK-039. 검증: AT-039 / `tests/acceptance/test_injection.py`.

**수용 기준:** PDF 의 다른 문서 조회·URL 전송·label 지정 지시가 권한을 바꾸지 않는다.

### SEC-004 · 삭제·보존·복구 (P0)

원본·파생물·검색·캐시·리뷰·메모리의 범위를 삭제 작업 manifest 로 추적한다.

화면: `/documents/:documentId`. API: `POST /v1/documents/{document_id}/deletion-requests`. 저장 엔터티: `DeletionRequest`. 구현: TASK-040. 검증: AT-040 / `tests/acceptance/test_retention.py`.

**수용 기준:** 법적 보존 설정과 실제 삭제 완료 상태를 분리하고 TTL 만으로 삭제 완료 처리하지 않는다.

### SEC-005 · 브라우저 세션 보호 (P0)

HttpOnly/Secure cookie, CSRF, Origin 검사, CSP 를 사용한다.

화면: `/login`. API: `POST /v1/auth/logout`. 저장 엔터티: `Session`. 구현: TASK-041. 검증: AT-041 / `tests/acceptance/test_session_security.py`.

**수용 기준:** CSRF 없는 변경 요청403, 토큰은 localStorage 와 URL 에 저장되지 않는다.

### SEC-006 · 비밀·라이선스·공급망 (P0)

의존성 잠금·SBOM·secret scan·라이선스/데이터 권리 gate 를 둔다.

화면: `/settings/runtime`. API: `POST /v1/preflight`. 저장 엔터티: `LicenseInventory`. 구현: TASK-042. 검증: AT-042 / `tests/acceptance/test_supply_chain.py`.

**수용 기준:** PyMuPDF 사용 승인이 없는 공개 배포에 해당 adapter 가 포함되지 않는다.


### FR-033 · 기업·실행 옵션 레지스트리 (P0)

기업을 생성·조회하고 tenant 에 승인된 rights/consent/runtime/rulepack 선택값을 제공한다. 화면 `/documents/new`, API `GET /v1/companies`, `POST /v1/companies`, `GET /v1/runtime-options`, 엔터티 Company. TASK-045/AT-045에 연결한다. 존재하지 않는 company_id, 미승인/타 tenant 옵션으로 문서·run 을 생성하면 거부한다.
