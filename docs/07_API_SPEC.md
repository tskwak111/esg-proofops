# 07 · API 명세

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 정본과 공통 계약
`contracts/openapi.yaml`이 요청/응답 필드와 enum 의 기계 판독 계약이다. 앱을 구현한 뒤 실제 FastAPI OpenAPI 와 diff 검사를 한다. 이 문서의 경로는 실행된 서버가 아니라 구현 대상이다. 각 DTO 는 별도 표시된 map 외에 `additionalProperties=false`; LLM·사용자가 전달한 label/grade 필드는 요청에서 거부한다.

인증은 서버 세션 cookie, 변경/서명 URL 발급 POST 는 `X-CSRF-Token`+Origin 검사, 본문 생성은 Idempotency-Key 를 요구한다. viewer 는 editor/reviewer/admin 에 포함되지만 editor 와 reviewer 는 상하 관계가 아니라 서로 다른 권한이다. admin 은 두 권한을 포함한다. `x-minimum-role`은 이 role capability 집합을 뜻한다. 모든 ID 는 UUID, 시간은 UTC RFC3339, money/value 는 decimal string 이다.

공통 조회 제한은 120회/분/사용자, 변경 10회/분/사용자, live-model preflight 2회/분/tenant, source view/download 발급 60회/분/사용자다. tenant 동시 실행은2다. 제한 값은 운영 정책 version 을 올려 바꿀 수 있다. 429에는 Retry-After 를 반환한다. pagination 50 기본/100 최대, 서명 cursor15분; 정렬 순서 created_at,id 또는 claim page,source order 를 server 가 고정한다.

## 2. Endpoint 목록
| Method/Path | 입력 → 출력 | 성공 | 권한 | 멱등키 |
|---|---|---|---|---|
| `GET /v1/session` | 없음 → Session | 200 | all | 없음/읽기 |
| `POST /v1/session/tenant` | TenantSelect → Session | 200 | all | 없음/읽기 |
| `POST /v1/auth/logout` | 없음 → 없음 | 204 | all | 없음/읽기 |
| `GET /v1/documents` | 없음 → DocumentPage | 200 | viewer | 없음/읽기 |
| `POST /v1/documents` | DocumentCreate → Document | 201 | editor | 필수 |
| `GET /v1/documents/{document_id}` | 없음 → Document | 200 | viewer | 없음/읽기 |
| `POST /v1/documents/{document_id}/versions` | VersionCreate → UploadTicket | 201 | editor | 필수 |
| `GET /v1/documents/{document_id}/versions` | 없음 → DocumentVersionPage | 200 | viewer | 없음/읽기 |
| `POST /v1/uploads/{upload_id}/complete` | UploadComplete → JobAccepted | 202 | editor | 필수 |
| `GET /v1/versions/{version_id}` | 없음 → DocumentVersion | 200 | viewer | 없음/읽기 |
| `GET /v1/runs` | 없음 → RunPage | 200 | viewer | 없음/읽기 |
| `POST /v1/runs` | RunCreate → Run | 202 | editor | 필수 |
| `GET /v1/runs/{run_id}` | 없음 → Run | 200 | viewer | 없음/읽기 |
| `POST /v1/runs/{run_id}/cancel` | ActionReason → Run | 202 | editor | 필수 |
| `POST /v1/runs/{run_id}/retry` | ActionReason → Run | 202 | editor | 필수 |
| `POST /v1/runs/{run_id}/rescores` | RescoreCreate → JobAccepted | 202 | reviewer | 필수 |
| `GET /v1/runs/{run_id}/rescores/{rescore_id}` | 없음 → JobAccepted | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/claims` | 없음 → ClaimSummaryPage | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/claims/{claim_id}` | 없음 → ClaimDetail | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/sources/{source_id}` | 없음 → SourceRef | 200 | viewer | 없음/읽기 |
| `POST /v1/runs/{run_id}/sources/{source_id}/view` | 없음 → Download | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/quality` | 없음 → QualityIssuePage | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/observations` | 없음 → ObservationPage | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/assurance` | 없음 → AssuranceMatchPage | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/safe-harbor` | 없음 → SafeHarborRecordPage | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/summary` | 없음 → Summary | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/audit` | 없음 → AuditEventPage | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/cost` | 없음 → Cost | 200 | viewer | 없음/읽기 |
| `GET /v1/runs/{run_id}/reviews` | 없음 → ReviewPage | 200 | reviewer | 없음/읽기 |
| `POST /v1/reviews/{review_id}/resolve` | ReviewResolve → ReviewResolution | 200 | reviewer | 필수 |
| `POST /v1/runs/{run_id}/exports` | ExportCreate → Export | 202 | viewer | 필수 |
| `GET /v1/exports/{export_id}` | 없음 → Export | 200 | viewer | 없음/읽기 |
| `POST /v1/exports/{export_id}/download` | 없음 → Download | 200 | viewer | 없음/읽기 |
| `POST /v1/runs/{run_id}/comparisons` | ComparisonCreate → JobAccepted | 202 | editor | 필수 |
| `GET /v1/comparisons/{comparison_id}` | 없음 → Comparison | 200 | viewer | 없음/읽기 |
| `GET /v1/rule-packs` | 없음 → RulePackPage | 200 | viewer | 없음/읽기 |
| `POST /v1/rule-packs/{rule_pack_id}/activate` | ActionReason → RulePack | 200 | admin | 필수 |
| `POST /v1/preflight` | PreflightRequest → Preflight | 200 | admin | 필수 |
| `GET /v1/evaluations/{evaluation_id}` | 없음 → Evaluation | 200 | admin | 없음/읽기 |
| `POST /v1/documents/{document_id}/deletion-requests` | ActionReason → DeletionRequest | 202 | admin | 필수 |
| `GET /v1/health/live` | 없음 → Health | 200 | public | 없음/읽기 |
| `GET /v1/health/ready` | 없음 → Health | 200 | internal | 없음/읽기 |

## 3. 중요 요청 예시
```http
POST /v1/runs
Idempotency-Key: 1c49f41e-6466-4aee-b18a-9b756ad7c1a8
X-CSRF-Token: <session-issued-token>
Content-Type: application/json
```
```json
{"document_version_id":"11111111-1111-4111-8111-111111111111","mode":"disclosure","scope":"full","rule_pack_id":"22222222-2222-4222-8222-222222222222","consent_profile_id":"33333333-3333-4333-8333-333333333333","runtime_binding_id":"44444444-4444-4444-8444-444444444444"}
```
`full`에는 selected_pages 를 보내지 않는다. `declared_subset`에는 중복 없이 정렬된1-based page 목록이 필요하다. API 는 문서 page_count 와 대조하고 범위를 벗어나면422, subset 이면 모든 출력 상단에 제한 범위를 표시한다. readiness 가 실패하면409 CONFIG_GATE_BLOCKED 이며 가짜 run 완료를 반환하지 않는다.

```json
{"error":{"code":"STALE_REVIEW_REVISION","message":"다른 검토자가 먼저 변경했습니다. 최신 근거를 다시 확인하세요.","request_id":"55555555-5555-4555-8555-555555555555","retryable":false,"details":{"current_revision":3}}}
```
에러 body 에 원문 PDF 내용, S3 내부 경로, 토큰, stack trace 를 넣지 않는다. 같은 idempotency 키+동일 body 는 기존 status/body 재생, 다른 body 는409다. 처리 중 재요청은202와 기존 resource id 를 반환한다.

## 4. 검토 API 의 추가 규칙
`POST /reviews/{id}/resolve`는 `If-Match: "2"`, base_tag_revision, track, elements, reason 이 필수다. revision 및 base tag 가 최신인지 검사하고 evidence_refs 를 다시 검증한다. `state=present`에는 검증된 근거가 하나 이상 필요하다. absent 는 검색 coverage 가 충족되어야 하고 unknown 을 임의 absent 로 바꿀 수 없다. 각 요소 변경 사유는 최상위 reason 과 변경 전후 artifact 에 함께 남긴다. 새 태깅에서 규칙이 해결되지 않으면 human_confirmed 태깅이더라도 decision_status 는 blocked_rule_gap 일 수 있다.

## 5. 파일·긴 작업·보고서 계약
업로드 POST ticket 은 10분, 발급된 PDF/view 및 export download URL 은 5분이다. complete 는 사용자 checksum 을 신뢰하지 않고 실제 S3 object 를 검증하는 job 을 만든다. status_url 로 poll 하고 version ready 전에 run 을 허용하지 않는다. API 는 임의 외부 URL 가져오기 기능을 제공하지 않는다.

리포트 생성은202 이후 GET export 로 poll 한다. allow_partial=false 이고 미분석/미확정 항목이 있으면409 REPORT_NOT_FINALIZABLE. allow_partial=true 면 범위·미판정·규칙 gap 을 표시한 검토용 export 를 만든다. ready 일 때만 download 를 발급하며 manifest hash 와 스냅샷 epoch 를 반환한다.

## 6. 비즈니스 API 밖의 관리 경로
Cognito 로그인 시작/콜백은 BFF 의 `GET /auth/login`, `GET /auth/callback` redirect 경로다. state/nonce/PKCE 검증 필수, return_to 는 동일 origin allowlist 다. Cognito 사용자·tenant seed, RulePack 콘텐츠 업로드/검증, evaluation 실행은 P0 관리 CLI 로만 제공한다. web 에서 직접 arbitrary rule YAML 을 실행시키지 않는다. `/v1/health/ready`는 내부 ALB/운영 접근만 허용하며 공개 health 응답은 의존성 세부를 감춘다.


## 7. 기업·선택 옵션 Endpoint 보완
| Method/Path | Request → Response | 성공 | 권한 |
|---|---|---|---|
| GET /v1/companies | 없음 → CompanyPage |200|viewer|
| POST /v1/companies | CompanyCreate → Company |201|editor, CSRF/Idempotency 필수|
| GET /v1/runtime-options | 없음 → RuntimeOptions |200|viewer|

CompanyCreate 는 legal_name(1–200), aliases, nullable registration_identifier 다. 같은 이름을 같은 법인으로 자동 병합하지 않는다. RuntimeOptions 는 해당 tenant 의 비밀 없는 rights/consent/runtime/rulepack 선택값과 활성 mode 만 반환한다. 정확한 DTO 와 오류는 OpenAPI 정본을 따른다.
