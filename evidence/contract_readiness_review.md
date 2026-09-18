# 계약 준비도 검토 — TASK-000 및 다음 독립 wave (002/025/037/042/043)

> 범위: read-only 검토. 도메인 확장/미정 gap 해소 없음. 승인된 설계에 대한 추가 승인 요청 없음.
> 대상 문서: AGENTS.md, 00/26/27/28/31/19, `contracts/task_catalog.json`, `contracts/task_execution_order.json`, `contracts/requirement_catalog.json`, `contracts/jsonschema/*`, `config/*`, `fixtures/*`, `evidence/legacy_inspection.json`.
> 표기: **[계약]** = 문서에 명시된 요구사항 자체의 충돌. **[해석]** = 검토자의 추론(계약 문언이 완전하지 않아 구현 중 재확인 필요).

## 1. [계약] CRITICAL — `SourceRef` JSON Schema가 27장 §4/§5 필수 필드를 정의하지 않음
`docs/27_PARSING_AND_PROVENANCE.md` §4는 `SourceRef`가 `artifact_hash`, `quote_hash`를 갖도록 요구하고, §5는 `source_quality: verified/unverified/conflicted/unreadable/unlocated` 5값 enum을 요구한다. 그러나 `contracts/jsonschema/api_models.schema.json`의 `SourceRef` (라인 646–730)에는 `artifact_hash`, `quote_hash` 필드가 없고, 대신 `location_quality: located/unlocated/unreadable` (3값)만 있다. `document_graph.schema.json`도 이 5값 enum을 정의하지 않는다. 전체 저장소에서 `source_quality`/`artifact_hash`/`quote_hash` 문자열은 0건 검색됐다(grep 확인).
**영향:** TASK-002(`canonicalize_source_ref`)가 어느 스키마를 정본으로 구현해야 하는지 결정할 수 없다. `verified` 상태 하나만 봐도 스키마상 `location_quality=located`가 27장의 `verified`(출처 확인 상태)와 `conflicted`(같은 위치, 값 충돌) 구분을 표현할 수 없어 numeric-check(TASK-005)·binding(TASK-013) 쪽 conflict 보존 요구와 충돌한다.
**권장:** `packages/proofops/domain/documents.py`/`SourceRef` 구현 전, `api_models.schema.json`에 `source_quality`(5값) 필드를 추가하거나 문서 27장을 스키마와 일치시키는 정정을 코디네이터가 먼저 확정해야 한다. 임의로 한쪽을 골라 구현하지 않는다.

## 2. [계약] CRITICAL — TASK-043 breakdown 본문이 TASK-003 텍스트로 오염됨
`docs/20_TASK_BREAKDOWN.md`의 TASK-043(기존 코드 characterization) "구현 내용" 문장이 "OpenDataLoader 기본, 표 보조 파서, 표 비전 교차확인을 실행한다"로 되어 있다 — 이는 TASK-003 항목의 문장과 동일(라인 비교 확인)하며 TASK-043의 실제 목적(legacy characterization, R-01~R-05 이식 위험 처리, `evidence/legacy_inspection.json` 갱신)과 무관하다. `task_catalog.json`의 TASK-043 acceptance("A1/B1/B2 dangling-edge 사례...")는 올바르게 26장과 일치하므로 catalog는 정본으로 사용 가능하나, breakdown 문서만 오염되어 있다.
**영향:** TASK-043을 breakdown 문서만 보고 시작하는 워커는 파싱 엔진 작업으로 착각해 26장의 R-01(dangling edge)·R-03(bbox 영점 금지) 이식 계약을 놓칠 위험이 크다.
**권장:** `docs/20_TASK_BREAKDOWN.md`의 TASK-043 "구현 내용" 한 문장만 26장 요약("R-01~R-05 이식 위험 규정을 특성화 테스트로 고정하고 evidence/reuse_ledger.json 갱신")으로 교체. `task_catalog.json`은 이미 올바르므로 그대로 유지.

## 3. [계약] IMPORTANT — `rule_pack_manifest.yaml`의 `status: draft`가 TASK-025 활성화 계약과 불일치
`docs/28_RULE_ENGINE_CONTRACT.md` §6과 `contracts/storage_entities.json`의 `RulePack.status` enum은 `draft|validated|active|retired`다. `config/rule_pack_manifest.yaml`은 `status: draft`이고 `unresolved_gap_ids`에 GAP-001~010 전부가 나열되어 있다. TASK-025 acceptance는 "버전·발효일·근거검증 상태·hash·승인자를 검증"이지만, `activate_rulepack`이 `unresolved_gap_ids`가 비지 않은 draft pack에 대해 무엇을 반환해야 하는지(활성화 거부 vs 부분 활성화 vs validated 상태로만 전환) 28장·31장 어디에도 명시가 없다.
**영향:** TASK-025 최소구현이 "GAP 미해결 pack은 활성화 자체를 차단"으로 갈지 "활성화는 되지만 관련 claim만 blocked_rule_gap"으로 갈지 워커마다 다르게 구현할 수 있다. 31장 "차단의 단위"는 claim/element 단위 차단을 말하지만 이것이 rule pack의 `activate` API 응답에도 적용되는지는 [해석] 영역이다.
**권장:** TASK-025 구현 전 `activate_rulepack`의 반환 계약에 "unresolved_gap_ids가 있어도 pack 자체는 active 상태로 전환 가능하며, 개별 claim 판정만 gate된다"는 문장을 28장 또는 task_catalog acceptance에 명시적으로 추가.

## 4. [계약] IMPORTANT — TASK-037 SEC-001 acceptance와 storage 스키마의 세션 발급 시점 불일치
`contracts/storage_entities.json`의 `Session` 엔티티는 `active_tenant_id:UUID?`(nullable)이며, SEC-001 acceptance는 "테넌트 A 사용자가 B id를 요청하면 404"만 규정한다. 그러나 `POST /v1/session/tenant`가 성공하기 전, 즉 `active_tenant_id`가 아직 null인 세션 상태에서 테넌트 스코프 API(`/v1/runs/*`, `/v1/documents/*` 등)를 호출했을 때의 동작(401 vs 403 vs tenant 미선택 오류코드)이 07장 API_SPEC/openapi.yaml 어디에도 명시되지 않는다.
**영향:** `authorize`/`select_tenant` 함수 계약(`session + membership + capability → AuthContext`)만으로는 "tenant 미선택 상태"가 유효한 AuthContext인지 에러인지 판단할 수 없다. TASK-001/003 등 후속 API가 이 상태를 다르게 처리하면 회귀 테스트가 어긋난다.
**권장:** TASK-037 구현 전 "tenant 미선택으로 테넌트 스코프 자원 접근 시 4xx 코드"를 명시적으로 확정(예: 07장에 표 추가). 최소구현 단계에서 워커가 임의 코드를 고르지 않도록.

## 5. [계약] IMPORTANT — TASK-042 acceptance가 라이선스 게이트 실패 시 `POST /v1/preflight` 응답 형태를 정의하지 않음
TASK-042 연결 API는 `POST /v1/preflight`이나, acceptance는 "PyMuPDF 사용 승인이 없는 공개 배포에 해당 adapter가 포함되지 않는다"로 배포 단위(빌드/패키징) 검증이지 런타임 API 응답이 아니다. TASK-029(모델·외부전송 사전 점검)도 같은 `POST /v1/preflight` 엔드포인트를 사용한다(SEC-006 acceptance는 배포 시점 검증, FR-029는 런타임 요청 검증). openapi.yaml에 두 관심사가 하나의 엔드포인트로 병합되어 있는지, 아니면 preflight 응답에 라이선스 게이트 결과와 모델/리전 바인딩 결과가 함께 포함되는 스키마가 있는지 확인이 필요하다.
**영향:** TASK-042 워커가 `verify_supply_chain`을 순수 빌드타임 스크립트(`scripts/check_licenses.py`)로만 구현하면 `/v1/preflight` API 연결점이 비게 되고, TASK-029와 TASK-042가 동일 엔드포인트 응답 스키마를 두 번 따로 정의해 충돌할 위험이 있다.
**권장:** `contracts/openapi.yaml`의 `/v1/preflight` 응답 스키마에 supply-chain/license 게이트 필드가 포함되어 있는지 확인 후, 없으면 TASK-042/029 두 Task의 파일 소유 경계(누가 `check_runtime_binding`을 확장하는지)를 명시.

## 6. [해석] IMPORTANT — TASK-000 "production fake adapter 거부" acceptance에 검증 트리거가 명시되지 않음
TASK-000 acceptance: "최소 domain/import/DTO와 local profile이 실행되고 production fake adapter를 거부한다." `contracts/environment_variables.json`은 `APP_ENV=production`시 무엇을 거부해야 하는지 나열하지 않고(`MODEL_ADAPTER: production은 bedrock만`만 명시), 어떤 adapter들이 "fake"로 분류되는지(로컬 sqlite/filesystem adapter 전체? MODEL_ADAPTER=synthetic만?) 05장/17장 어디에도 목록이 없다.
**영향:** `tests/contracts/test_package_contracts.py`의 실패 테스트를 먼저 작성해야 하는 TASK-000 워커가 "거부 대상 fake adapter 집합"을 임의로 정의하게 된다. 이는 사소한 선택이 아니라 이후 모든 Task의 production gate 동작을 좌우한다.
**권장:** 최소한 "APP_ENV=production일 때 adapters/local/* 및 MODEL_ADAPTER=synthetic은 기동 실패로 거부"라는 한 줄을 05장 또는 17장에 명시. (이것은 임의 도메인 확장이 아니라 이미 존재하는 "production은 fake adapter 거부" 문장의 최소 실행 정의이므로 GAP 등록 대상은 아님.)

## 7. [계약] IMPORTANT — TASK-002 의존성 실행순서와 TASK-038(업로드 격리) 선행관계가 순환 근접
`task_execution_order.json`은 TASK-002를 TASK-037 앞에 배치하고, TASK-038(선행: TASK-000, TASK-002)은 TASK-002 이후에 온다. 그러나 TASK-001(선행: TASK-000, TASK-037, TASK-038, TASK-041, TASK-045)이 지정 실행순서에서 TASK-002/025/037/042/043보다 훨씬 뒤(순서 15번째)에 오는 것은 `task_catalog.json`과 일치한다. 다만 TASK-038의 "선행"에 TASK-037(인증)이 없어, 업로드 격리 검증(`verify_quarantined_pdf`)이 인증 컨텍스트 없이 호출 가능한 순수 함수로 설계된 것인지, 아니면 실행 순서상 TASK-037이 먼저 끝나므로 암묵적으로 auth가 있다고 가정하는지 불명확하다.
**영향:** 이번 wave(002/025/037/042/043)가 끝난 뒤 TASK-038 워커가 `verify_quarantined_pdf`에 tenant/actor 파라미터를 넣을지 여부를 결정할 때 참조할 명시 계약이 없다.
**권장:** 이는 다음 wave 이슈이므로 차단 사유는 아니나, TASK-038 시작 전 `packages/proofops/application/uploads_security.py` 인터페이스 시그니처에 tenant 파라미터 포함 여부를 명시하도록 task_catalog `interfaces` 필드 보강 권장.

## 8. [계약] 참고 — TASK-025/031 `RulePack` 상태와 `ApprovedProfile` 테이블의 승인 기록 연결 미명시
`contracts/storage_entities.json`의 `RulePack`에는 `approved_by`/`approved_at`이 있고, 별도로 `ApprovedProfile(kind: rights|consent|runtime)` 테이블이 있다. `RulePack`이 `ApprovedProfile`의 `kind` 목록에 포함되지 않아 규칙팩 승인이 두 테이블 중 어디를 정본으로 쓰는지 28장/31장에 명시가 없다(31장 "승인 이력"은 gap_id별 승인만 규정하고 RulePack 활성화 승인과의 관계는 다루지 않음).
**영향:** TASK-025 `activate_rulepack` 구현이 `ApprovedProfile`을 참조해야 하는지 `RulePack.approved_by`만으로 충분한지 판단 불가. 낮은 우선도이나 TASK-025 인터페이스 초안 작성 시 재확인 필요.
**권장:** TASK-025 구현자가 착수 시 `RulePack.approved_by`만을 승인 정본으로 사용하고 `ApprovedProfile.kind`에 `rulepack`을 추가할지는 별도 확인 후 진행.

---

## 요약
CRITICAL 2건(#1 SourceRef 스키마 필드 누락, #2 TASK-043 breakdown 본문 오염)은 착수 전 반드시 해결해야 한다. IMPORTANT 5건(#3–#7)은 해당 Task의 최소구현 인터페이스 설계 단계에서 임의 선택이 계약 위반으로 굳어지는 것을 막기 위한 명확화 요청이다. 참고 1건(#8)은 차단 사유가 아니다. 도메인 임계값·조항·gap 해제는 검토 대상에서 제외했다(31장 원칙 준수).
