# 20 · Codex 작업 분해

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 작업 크기와 완료 기준
각 Task 는 하나의 독립적인 결과와 검증단위를 가진다. 아래명세의파일은목표경로다. 앱미구현상태에서테스트가존재한다고가정하지않고, Task 시작시 해당테스트를작성한다. 모든 Task 의공통 DoD 는실제 lint/type/test/build 결과·문서갱신·보안/도메인 변경없음이다. 테스트가없는구현은완료가아니다.

### TASK-000 · 계약 우선 bootstrap (P0)

**목적/요구사항:** 전체 계약 기반.

**생성/수정 파일:** `pyproject.toml`, `package.json`, `apps/`, `packages/`, `contracts/`, `tests/contracts/test_package_contracts.py`.

**입출력/함수:** `package schema validation + local synthetic composition root`.

**선행:** 없음.

**검증:** `python scripts/validate_package.py; uv run pytest tests/contracts/test_package_contracts.py`.

**반드시 단언할 결과:** 최소 domain/import/DTO 와 local profile 이실행되고 production fake adapter 를거부한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-001 · PDF 업로드·버전 고정 (P0)

**목적/요구사항:** FR-001.

**생성/수정 파일:** `apps/api/src/proofops_api/routers/documents.py`, `packages/proofops/application/uploads.py`, `tests/acceptance/test_upload.py`.

**입출력/함수:** `create_document / initiate_upload / complete_upload :: VersionCreate + verified object → immutable DocumentVersion`.

**선행:** TASK-000, TASK-037, TASK-038, TASK-041.

**구현 내용:** PDF 바이트 SHA-256, S3 version_id, 기업·보고기간·문서 유형을 고정한다.

**연결 API:** `POST /v1/documents; POST /v1/documents/{document_id}/versions`.

**검증:** `uv run pytest tests/acceptance/test_upload.py -q`.

**반드시 단언할 결과:** 위조 MIME·초과 크기는 거부하고 동일 업로드 완료 재호출은 같은 버전을 반환한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-002 · 페이지·좌표·원문 위치 (P0)

**목적/요구사항:** FR-002.

**생성/수정 파일:** `packages/proofops/domain/documents.py`, `packages/proofops/application/ingest/geometry.py`, `tests/acceptance/test_provenance.py`.

**입출력/함수:** `canonicalize_source_ref :: NativeSource + PageGeometry → SourceRef`.

**선행:** TASK-000.

**구현 내용:** 물리 페이지·인쇄 페이지·원시 좌표·표준 좌표·문자 오프셋을 분리한다.

**연결 API:** `GET /v1/runs/{run_id}/sources/{source_id}`.

**검증:** `uv run pytest tests/acceptance/test_provenance.py -q`.

**반드시 단언할 결과:** 회전·CropBox·한국어 조합 문자 fixture 의 원문 영역 왕복이 일치한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-003 · 파싱·충돌 관리 (P0)

**목적/요구사항:** FR-003.

**생성/수정 파일:** `packages/proofops/adapters/parsing/opendataloader.py`, `packages/proofops/application/ingest/graph_fusion.py`, `tests/acceptance/test_parsing.py`.

**입출력/함수:** `parse / fuse_candidates :: SourceArtifact + ParserProfile → CanonicalDocumentGraph`.

**선행:** TASK-001, TASK-002, TASK-042, TASK-043.

**구현 내용:** OpenDataLoader 기본, 표 보조 파서, 표 비전 교차확인을 실행한다.

**연결 API:** `GET /v1/runs/{run_id}/quality`.

**검증:** `uv run pytest tests/acceptance/test_parsing.py -q`.

**반드시 단언할 결과:** 수치가 다른 후보를 덮어쓰지 않고 conflict 를 보존한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-004 · 표 정규화 (P0)

**목적/요구사항:** FR-004.

**생성/수정 파일:** `packages/proofops/application/ingest/normalize.py`, `tests/acceptance/test_tables.py`.

**입출력/함수:** `normalize_tables :: CanonicalDocumentGraph → Observation[] + conflict records`.

**선행:** TASK-003.

**구현 내용:** 지표·Scope·사업장·기간·방법·단위·값을 행열/각주에 연결한다.

**연결 API:** `GET /v1/runs/{run_id}/observations`.

**검증:** `uv run pytest tests/acceptance/test_tables.py -q`.

**반드시 단언할 결과:** 서로 다른 연도·조직·시장기반/위치기반을 하나의 값으로 병합하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-005 · 코드 수치 검산 (P0)

**목적/요구사항:** FR-005.

**생성/수정 파일:** `packages/proofops/domain/numeric.py`, `tests/acceptance/test_numeric.py`.

**입출력/함수:** `check_numeric_consistency :: Observation[] + claim bindings → CheckResult[]`.

**선행:** TASK-004.

**구현 내용:** Decimal 기반 합계·증감률·본문/표 비교를 수행한다.

**연결 API:** `GET /v1/runs/{run_id}/claims/{claim_id}`.

**검증:** `uv run pytest tests/acceptance/test_numeric.py -q`.

**반드시 단언할 결과:** 반올림 범위는 인정하고 0 분모·없는 값은 not_computable 로 기록한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-006 · GRI Index 경로 (P0)

**목적/요구사항:** FR-006.

**생성/수정 파일:** `packages/proofops/application/ingest/gri.py`, `tests/acceptance/test_gri.py`.

**입출력/함수:** `build_gri_index :: CanonicalDocumentGraph + printed-page map → IndexEntry[]`.

**선행:** TASK-003, TASK-002.

**구현 내용:** GRI 코드와 인쇄 페이지를 물리 페이지 후보로 매핑한다.

**연결 API:** `GET /v1/runs/{run_id}/quality`.

**검증:** `uv run pytest tests/acceptance/test_gri.py -q`.

**반드시 단언할 결과:** 페이지를 찾지 못한 것은 mismatch 확정 대신 unresolved 로 남긴다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-007 · 보증의견서와 범위 매칭 (P0)

**목적/요구사항:** FR-007.

**생성/수정 파일:** `packages/proofops/application/assurance.py`, `tests/acceptance/test_assurance.py`.

**입출력/함수:** `extract_assurance / match_assurance :: SourceRefs + ModelBinding + ClaimContext → AssuranceStatement / AssuranceMatch`.

**선행:** TASK-003, TASK-002, TASK-029.

**구현 내용:** 수준·기관·기준·대상 지표·기간·경계·제외를 구조화한다.

**연결 API:** `GET /v1/runs/{run_id}/assurance`.

**검증:** `uv run pytest tests/acceptance/test_assurance.py -q`.

**반드시 단언할 결과:** 기관명만 같은 별도 연도/사업장의 주장을 covered 로 만들지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-008 · 클레임 전수 추출 (P0)

**목적/요구사항:** FR-008.

**생성/수정 파일:** `packages/proofops/application/claims.py`, `apps/agent/src/proofops_agent/extraction.py`, `tests/acceptance/test_claims.py`.

**입출력/함수:** `discover_atomic_claims :: CanonicalDocumentGraph + scope → Claim[] + exclusions`.

**선행:** TASK-003, TASK-029.

**구현 내용:** 환경 영역의 원자 주장을 추출하고 비주장 제외 사유도 남긴다.

2026-09-09 사용자 승인 로컬 최적화 시험: 문장 분리·문맥 보존·후보 선별을
로컬에서 수행하고 LLM은 후보 문장 ID를 선택한다. 이 출력은 원자 주장 분해
이전의 후보이며 `atomicity=not_reviewed`다. `evaluation.prefilter_comparison`의
명시적 페이지 부분집합에서 전수 텍스트 입력과 비교한다. 로컬 미선택은
`unknown`이며 비주장/근거 부재가 아니다. `full` 추출 경로와 주제별 무할당
원칙을 유지하고, 표·그림 미처리 및 누락 페이지를 별도 기록한다.

**연결 API:** `GET /v1/runs/{run_id}/claims`.

**검증:** `uv run pytest tests/acceptance/test_claims.py -q`.

**반드시 단언할 결과:** 성과+목표 복합문장을 분리하고 full 모드에서 topic quota 로 잘라내지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-009 · 트랙·주제 독립 태깅 (P0)

**목적/요구사항:** FR-009.

**생성/수정 파일:** `packages/proofops/application/tagging/tracks.py`, `tests/acceptance/test_tracks.py`.

**입출력/함수:** `validate_track_candidates :: Claim[] + structured candidates → track/category candidates`.

**선행:** TASK-008, TASK-029.

**구현 내용:** goal/performance/management 를 문장 성격으로 결정한다.

**연결 API:** `GET /v1/runs/{run_id}/claims/{claim_id}`.

**검증:** `uv run pytest tests/acceptance/test_tracks.py -q`.

**반드시 단언할 결과:** 공급망 토픽의 미래 목표를 management 로 강제하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-010 · 동일 packet 태깅 3회 (P0)

**목적/요구사항:** FR-010.

**생성/수정 파일:** `packages/proofops/application/tagging/service.py`, `packages/proofops/application/tagging/consensus.py`, `apps/agent/src/proofops_agent/tagger.py`, `tests/acceptance/test_tagging.py`.

**입출력/함수:** `tag_replicates / form_consensus :: EvidencePacket + replicate 1/2/3 → TagRun[] + ConfirmedTags or review`.

**선행:** TASK-009, TASK-011, TASK-012, TASK-013, TASK-014, TASK-029, TASK-030, TASK-033.

**구현 내용:** 고정 evidence packet 에 replicate_id 1·2·3으로 세 번 실행한다.

**연결 API:** `GET /v1/runs/{run_id}/claims/{claim_id}`.

**검증:** `uv run pytest tests/acceptance/test_tagging.py -q`.

**반드시 단언할 결과:** 서로 다른 replicate 의 raw cache 재사용을 차단한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-011 · 동일 문서 근거 검색 (P0)

**목적/요구사항:** FR-011.

**생성/수정 파일:** `packages/proofops/application/evidence/retrieval.py`, `packages/proofops/adapters/aws/opensearch.py`, `tests/acceptance/test_retrieval.py`.

**입출력/함수:** `retrieve_evidence / freeze_packet :: Claim + same-document source filters → EvidencePacket`.

**선행:** TASK-006, TASK-007, TASK-008, TASK-002.

**구현 내용:** GRI→섹션→어휘/벡터 검색을 하되 허용 근거 범위를 검증한다.

**연결 API:** `GET /v1/runs/{run_id}/claims/{claim_id}`.

**검증:** `uv run pytest tests/acceptance/test_retrieval.py -q`.

**반드시 단언할 결과:** 다른 문서의 숫자 또는 같은 문서 먼 페이지 목표연도를 직접근거로 인정하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-012 · 인용 실재·정규화 검증 (P0)

**목적/요구사항:** FR-012.

**생성/수정 파일:** `packages/proofops/application/evidence/citations.py`, `tests/acceptance/test_citations.py`.

**입출력/함수:** `verify_source_ref :: SourceRef + original source snapshot → verified/rejected reference`.

**선행:** TASK-002, TASK-008.

**구현 내용:** source_id·범위·quote·해시·오프셋을 코드로 확인한다.

**연결 API:** `GET /v1/runs/{run_id}/sources/{source_id}`.

**검증:** `uv run pytest tests/acceptance/test_citations.py -q`.

**반드시 단언할 결과:** 발명된 인용은 무효이며 느슨한 fuzzy 매치만으로 확정하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-013 · 주장 귀속 검증 (P0)

**목적/요구사항:** FR-013.

**생성/수정 파일:** `packages/proofops/application/evidence/binding.py`, `tests/acceptance/test_binding.py`.

**입출력/함수:** `accept_binding :: ClaimContext + SourceRef + relation tags → accepted/undetermined/rejected`.

**선행:** TASK-011, TASK-012.

**구현 내용:** 지표·기업·사업장·Scope·기간과 표 행열 귀속을 검증한다.

**연결 API:** `GET /v1/runs/{run_id}/claims/{claim_id}`.

**검증:** `uv run pytest tests/acceptance/test_binding.py -q`.

**반드시 단언할 결과:** 같은 페이지의 다른 제품 비율을 해당 제품 근거로 인정하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-014 · 일반 사다리·라벨 (P0)

**목적/요구사항:** FR-014.

**생성/수정 파일:** `packages/proofops/domain/rules/engine.py`, `packages/proofops/domain/rules/goal.py`, `packages/proofops/domain/rules/performance.py`, `packages/proofops/domain/rules/management.py`, `tests/acceptance/test_rules.py`.

**입출력/함수:** `evaluate :: ConfirmedTags + RuleContext + RulePack → Decision`.

**선행:** TASK-000, TASK-025.

**구현 내용:** v2.0 사다리를 순수 함수로 계산하고 G/P/M 결손을 분리한다.

**연결 API:** `GET /v1/runs/{run_id}/claims/{claim_id}`.

**검증:** `uv run pytest tests/acceptance/test_rules.py -q`.

**반드시 단언할 결과:** 성과 E3는 방법과 covered 보증이 모두 있어야 하며 같은 입력의 결과 해시가 같다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-015 · 최상급·제품·범주형 특칙 (P0)

**목적/요구사항:** FR-015.

**생성/수정 파일:** `packages/proofops/domain/rules/exceptions.py`, `tests/acceptance/test_exceptions.py`.

**입출력/함수:** `apply_source_exceptions :: RuleContext + primitive facts → override/cap/gap`.

**선행:** TASK-014.

**구현 내용:** 원문의 최상급 AND 부재, 제품 비율 직접연결, 범주형 인증 규칙을 구현한다.

**연결 API:** `GET /v1/runs/{run_id}/claims/{claim_id}`.

**검증:** `uv run pytest tests/acceptance/test_exceptions.py -q`.

**반드시 단언할 결과:** 비교와 외부검증 둘 다 없을 때만 최상급 E0 강제 규칙을 발동한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-016 · 세이프하버 기록 경로 (P0)

**목적/요구사항:** FR-016.

**생성/수정 파일:** `packages/proofops/domain/rules/safe_harbor.py`, `tests/acceptance/test_safe_harbor.py`.

**입출력/함수:** `record_safe_harbor :: Category + evidence checklist + approved mapping → SafeHarborRecord`.

**선행:** TASK-014.

**구현 내용:** 범주별 가정·방법·출처·한계 체크리스트를 독립 저장한다.

**연결 API:** `GET /v1/runs/{run_id}/safe-harbor`.

**검증:** `uv run pytest tests/acceptance/test_safe_harbor.py -q`.

**반드시 단언할 결과:** 승인된 등급 매핑이 없으면 숫자 부재로 E0를 부여하지 않고 rule gap 을 표시한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-017 · 산업 적용·결측 (P0)

**목적/요구사항:** FR-017.

**생성/수정 파일:** `packages/proofops/domain/applicability.py`, `tests/acceptance/test_industry.py`.

**입출력/함수:** `resolve_industry_applicability :: Industry identity + verified mapping → applicable/N_A/undetermined`.

**선행:** TASK-025.

**구현 내용:** 버전 고정 산업 mapping 으로 적용성·필수성을 분리한다.

**연결 API:** `GET /v1/runs/{run_id}/summary`.

**검증:** `uv run pytest tests/acceptance/test_industry.py -q`.

**반드시 단언할 결과:** 알 수 없는 산업을 임의로 not_applicable 처리하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-018 · 유예·기준 효력 (P0)

**목적/요구사항:** FR-018.

**생성/수정 파일:** `packages/proofops/domain/regulatory.py`, `tests/acceptance/test_regulatory.py`.

**입출력/함수:** `resolve_deferral :: CompanyContext + approved timeline → required/advisory/undetermined`.

**선행:** TASK-025.

**구현 내용:** 승인된 기간·기업 조건으로 필수/참고 검토 축을 계산한다.

**연결 API:** `GET /v1/runs/{run_id}/summary`.

**검증:** `uv run pytest tests/acceptance/test_regulatory.py -q`.

**반드시 단언할 결과:** 효력 미확인 설정은 법정 위반이나 면책 확정 문구를 만들지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-019 · 인간 태깅 검토 (P0)

**목적/요구사항:** FR-019.

**생성/수정 파일:** `packages/proofops/application/reviews.py`, `apps/api/src/proofops_api/routers/reviews.py`, `apps/web/src/features/reviews/ReviewWorkspace.tsx`, `tests/acceptance/test_reviews.py`.

**입출력/함수:** `resolve_review :: ReviewResolve + actor + If-Match → atomic ReviewResolution`.

**선행:** TASK-010, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-022, TASK-037.

**구현 내용:** 검토자는 근거·요소·트랙을 수정하고 규칙엔진이 재채점한다.

**연결 API:** `POST /v1/reviews/{review_id}/resolve`.

**검증:** `uv run pytest tests/acceptance/test_reviews.py -q`.

**반드시 단언할 결과:** If-Match 충돌은 412, label 직접 수정 입력은 422다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-020 · 버전별 재채점 (P0)

**목적/요구사항:** FR-020.

**생성/수정 파일:** `packages/proofops/application/rescores.py`, `tests/acceptance/test_rescore.py`.

**입출력/함수:** `create_rescore :: new RulePack + immutable TagRevision → DecisionRevision or RETAG_REQUIRED`.

**선행:** TASK-019.

**구현 내용:** 파싱·태깅 재사용 가능성을 검사하고 새 결정 revision 을 만든다.

**연결 API:** `POST /v1/runs/{run_id}/rescores`.

**검증:** `uv run pytest tests/acceptance/test_rescore.py -q`.

**반드시 단언할 결과:** 요소 ontology 가 바뀌면 재태깅 필요를 알리고 오래된 요소를 새 정답처럼 쓰지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-021 · 감사 리포트·수정 제안 (P0)

**목적/요구사항:** FR-021.

**생성/수정 파일:** `packages/proofops/application/reporting.py`, `apps/web/src/features/reports/ReportPreview.tsx`, `tests/acceptance/test_report.py`.

**입출력/함수:** `build_report_model :: SnapshotManifest + immutable decisions → report data/templates`.

**선행:** TASK-019, TASK-026.

**구현 내용:** 결손·근거 위치·버전·검토·보증·세이프하버를 출력한다.

**연결 API:** `POST /v1/runs/{run_id}/exports`.

**검증:** `uv run pytest tests/acceptance/test_report.py -q`.

**반드시 단언할 결과:** 수정 제안은 없는 숫자를 채우지 않으며 미완료 건과 미확인 조항을 숨기지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-022 · 감사 이력 (P0)

**목적/요구사항:** FR-022.

**생성/수정 파일:** `packages/proofops/adapters/aws/audit.py`, `packages/proofops/domain/audit.py`, `tests/acceptance/test_audit.py`.

**입출력/함수:** `append_audit_transaction :: ChangeSet + expected audit HEAD → immutable event + new HEAD`.

**선행:** TASK-000, TASK-033.

**구현 내용:** 변경 전후 해시·행위자·revision·사유를 append-only 로 저장한다.

**연결 API:** `GET /v1/runs/{run_id}/audit`.

**검증:** `uv run pytest tests/acceptance/test_audit.py -q`.

**반드시 단언할 결과:** 현재 결과를 바꿔도 기존 export snapshot 과 감사 이벤트는 바뀌지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-023 · 다년도 비교 (P1)

**목적/요구사항:** FR-023.

**생성/수정 파일:** `packages/proofops/application/comparisons.py`, `apps/web/src/features/comparison/ComparisonPage.tsx`, `tests/acceptance/test_comparison.py`.

**입출력/함수:** `compare_years :: current/prior approved versions → change candidates/not_run`.

**선행:** TASK-021, TASK-008.

**구현 내용:** 같은 기업의 전년 버전이 있을 때 목표 변경·삭제 후보를 산출한다.

**연결 API:** `POST /v1/runs/{run_id}/comparisons`.

**검증:** `uv run pytest tests/acceptance/test_comparison.py -q`.

**반드시 단언할 결과:** 전년 문서 미제공 시 not_run 이며 이전 문서 근거로 올해 등급을 올리지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-024 · 광고 검토 별도 모드 (P1)

**목적/요구사항:** FR-024.

**생성/수정 파일:** `packages/proofops/application/mode_gate.py`, `tests/acceptance/test_advertising.py`.

**입출력/함수:** `select_mode_rulepack :: mode + approved rulepack → isolated rules or gate error`.

**선행:** TASK-025, TASK-014.

**구현 내용:** 광고 전용 승인 규칙팩만 해당 모드에 적용한다.

**연결 API:** `POST /v1/runs`.

**검증:** `uv run pytest tests/acceptance/test_advertising.py -q`.

**반드시 단언할 결과:** 공시 모드에 표시광고 규칙을 라벨 입력으로 주입하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-025 · 규칙팩 검증·활성화 (P0)

**목적/요구사항:** FR-025.

**생성/수정 파일:** `packages/proofops/application/rulepacks.py`, `scripts/verify_rulepack.py`, `tests/acceptance/test_rulepacks.py`.

**입출력/함수:** `validate_rulepack / activate_rulepack :: YAML+source metadata+gap registry → validated pack/status`.

**선행:** TASK-000.

**구현 내용:** 버전·발효일·근거검증 상태·hash·승인자를 검증한다.

**연결 API:** `POST /v1/rule-packs/{rule_pack_id}/activate`.

**검증:** `uv run pytest tests/acceptance/test_rulepacks.py -q`.

**반드시 단언할 결과:** 활성화는 새 run 기본값만 바꾸며 실행 중인 규칙 스냅샷은 바꾸지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-026 · 대시보드·상태 분리 (P0)

**목적/요구사항:** FR-026.

**생성/수정 파일:** `packages/proofops/application/summaries.py`, `apps/web/src/features/dashboard/RunSummary.tsx`, `tests/acceptance/test_dashboard.py`.

**입출력/함수:** `summarize_snapshot :: Run coverage + decisions + applicability → Summary`.

**선행:** TASK-019, TASK-027.

**구현 내용:** 결손·검토·등급·분모·적용제외·미처리 비율을 함께 표시한다.

**연결 API:** `GET /v1/runs/{run_id}/summary`.

**검증:** `uv run pytest tests/acceptance/test_dashboard.py -q`.

**반드시 단언할 결과:** E 분포 분모에 미판정·읽기실패를 숨겨 넣지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-027 · 전수성·부분 완료 (P0)

**목적/요구사항:** FR-027.

**생성/수정 파일:** `packages/proofops/application/coverage.py`, `apps/web/src/features/runs/CoveragePanel.tsx`, `tests/acceptance/test_coverage.py`.

**입출력/함수:** `update_coverage :: job/source/claim counters → consistent Coverage`.

**선행:** TASK-028, TASK-008.

**구현 내용:** 전체/처리/제외/실패/미분석 페이지·청크·주장 수를 보존한다.

**연결 API:** `GET /v1/runs/{run_id}`.

**검증:** `uv run pytest tests/acceptance/test_coverage.py -q`.

**반드시 단언할 결과:** 예산으로 중단된 작업은 completed 가 아닌 partial 이며 완전 검토 배지를 표시하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-028 · 내구 작업·재시도·취소 (P0)

**목적/요구사항:** FR-028.

**생성/수정 파일:** `apps/worker/src/proofops_worker/consumer.py`, `apps/worker/src/proofops_worker/relay.py`, `packages/proofops/adapters/aws/jobs.py`, `tests/acceptance/test_jobs.py`.

**입출력/함수:** `claim_job / commit_job / relay_outbox :: StageJob + message + lease → checkpoint/next event`.

**선행:** TASK-000, TASK-033.

**구현 내용:** SQS 중복 전달·워커 재시작에 견디는 lease/fencing/checkpoint 를 구현한다.

**연결 API:** `POST /v1/runs/{run_id}/cancel; POST /v1/runs/{run_id}/retry`.

**검증:** `uv run pytest tests/acceptance/test_jobs.py -q`.

**반드시 단언할 결과:** 죽은 워커의 늦은 결과가 새 시도의 결과를 덮지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-029 · 모델·외부전송 사전 점검 (P0)

**목적/요구사항:** FR-029.

**생성/수정 파일:** `scripts/preflight.py`, `packages/proofops/application/preflight.py`, `packages/proofops/adapters/aws/bedrock.py`, `tests/acceptance/test_preflight.py`.

**입출력/함수:** `check_runtime_binding :: Account binding + consent + allowed regions → Preflight`.

**선행:** TASK-000, TASK-037.

**구현 내용:** 모델 ID·리전·권한·스키마·image·token·동의 프로필을 확인한다.

**연결 API:** `POST /v1/preflight`.

**검증:** `uv run pytest tests/acceptance/test_preflight.py -q`.

**반드시 단언할 결과:** 허용되지 않은 리전 fallback 으로 문서를 전송하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-030 · 원가·토큰 예산 (P0)

**목적/요구사항:** FR-030.

**생성/수정 파일:** `packages/proofops/application/budget.py`, `packages/proofops/adapters/aws/usage.py`, `tests/acceptance/test_cost.py`.

**입출력/함수:** `reserve_budget / record_usage :: role call limits + attempts → token reservations + UsageLedger`.

**선행:** TASK-029, TASK-028.

**구현 내용:** 호출별 모델·토큰·지연·재시도·캐시·단가 스냅샷을 기록한다.

**연결 API:** `GET /v1/runs/{run_id}/cost`.

**검증:** `uv run pytest tests/acceptance/test_cost.py -q`.

**반드시 단언할 결과:** 단가 미설정은 unknown_cost 이며 0원으로 표시하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-031 · 스냅샷 export·다운로드 (P0)

**목적/요구사항:** FR-031.

**생성/수정 파일:** `packages/proofops/application/exports.py`, `apps/api/src/proofops_api/routers/exports.py`, `tests/acceptance/test_exports.py`.

**입출력/함수:** `create_snapshot / build_export / authorize_download :: run epoch + revision heads → immutable ExportSnapshot`.

**선행:** TASK-021, TASK-022.

**구현 내용:** JSON·CSV·HTML 감사 꾸러미와 manifest 를 만든다.

**연결 API:** `GET /v1/exports/{export_id}; POST /v1/exports/{export_id}/download`.

**검증:** `uv run pytest tests/acceptance/test_exports.py -q`.

**반드시 단언할 결과:** export 중 review 변경이 발생하면 revision 을 섞지 않고 snapshot 생성만 재시도한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-032 · 데이터셋·평가 분리 (P0)

**목적/요구사항:** FR-032.

**생성/수정 파일:** `evaluation/metrics/elements.py`, `evaluation/metrics/pipeline.py`, `evaluation/splits/company_split.py`, `tests/acceptance/test_evaluation.py`.

**입출력/함수:** `evaluate_dataset / verify_split :: fixed predictions + isolated gold → metrics with denominators`.

**선행:** TASK-000, TASK-014, TASK-008, TASK-010.

**구현 내용:** silver/fewshot/validation/holdout 를 회사 단위 분리한다.

**연결 API:** `GET /v1/evaluations/{evaluation_id}`.

**검증:** `uv run pytest tests/acceptance/test_evaluation.py -q`.

**반드시 단언할 결과:** 검토 확정 데이터를 holdout 에 자동 추가하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-033 · 재현성과 실행 식별 (P0)

**목적/요구사항:** NFR-001.

**생성/수정 파일:** `packages/proofops/domain/provenance.py`, `packages/proofops/adapters/cache/aws.py`, `tests/acceptance/test_reproducibility.py`.

**입출력/함수:** `canonical_hash / request_signature :: source+prompt+model+replicate+tenant → semantic signature`.

**선행:** TASK-000, TASK-043.

**구현 내용:** 동일 확정 입력·규칙·엔진으로 decision semantic hash 가 같아야 한다.

**연결 API:** `GET /v1/runs/{run_id}/audit`.

**검증:** `uv run pytest tests/acceptance/test_reproducibility.py -q`.

**반드시 단언할 결과:** 시간·행위자는 semantic hash 에서 제외하고 provenance hash 에는 별도로 남긴다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-034 · 가용성·지연 목표 (P0)

**목적/요구사항:** NFR-002.

**생성/수정 파일:** `tests/load/read_api.py`, `tests/integration/test_worker_recovery.py`, `tests/acceptance/test_slo.py`.

**입출력/함수:** `exercise_load_profile :: 20readers + 2runs/tenant + fault injection → measured SLI`.

**선행:** TASK-028, TASK-026.

**구현 내용:** 조회 p95 1초, 요청 수락 p95 2초를 초기 부하 시험 목표로 둔다.

**연결 API:** `GET /v1/health/ready`.

**검증:** `uv run pytest tests/acceptance/test_slo.py -q`.

**반드시 단언할 결과:** 미측정 수치를 달성 실적으로 표시하지 않고 계정·파일럿 수치를 기록한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-035 · 관측성과 비밀 제거 (P0)

**목적/요구사항:** NFR-003.

**생성/수정 파일:** `apps/api/src/proofops_api/telemetry.py`, `apps/worker/src/proofops_worker/telemetry.py`, `tests/acceptance/test_observability.py`.

**입출력/함수:** `emit_sanitized_event :: Structured lifecycle event → redacted logs/metrics/traces`.

**선행:** TASK-028, TASK-030.

**구현 내용:** trace_id 와 stage 오류·호출 지표를 남기고 문서 본문은 로그에서 제외한다.

**연결 API:** `GET /v1/runs/{run_id}/cost`.

**검증:** `uv run pytest tests/acceptance/test_observability.py -q`.

**반드시 단언할 결과:** fixture 의 API key·본문 문자열이 로그 수집 결과에 없음을 검사한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-036 · 계약 호환·접근성 (P0)

**목적/요구사항:** NFR-004.

**생성/수정 파일:** `apps/web/src/design/tokens.css`, `apps/web/src/components/SourceViewer.tsx`, `apps/web/src/components/StatusBadge.tsx`, `tests/acceptance/test_accessibility.py`.

**입출력/함수:** `render_accessible_workspace :: API DTOs + keyboard actions → accessible screens`.

**선행:** TASK-026, TASK-019.

**구현 내용:** API schema version 과 keyboard 접근·비색상 상태 구분을 제공한다.

**연결 API:** `GET /v1/runs/{run_id}/claims`.

**검증:** `uv run pytest tests/acceptance/test_accessibility.py -q`.

**반드시 단언할 결과:** 키보드로 근거 열기·태깅 수정·확정 취소가 가능하다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-037 · 인증·역할·테넌트 (P0)

**목적/요구사항:** SEC-001.

**생성/수정 파일:** `apps/api/src/proofops_api/auth.py`, `packages/proofops/application/authorization.py`, `tests/acceptance/test_auth.py`.

**입출력/함수:** `authorize / select_tenant :: session + membership + capability → AuthContext`.

**선행:** TASK-000.

**구현 내용:** Cognito+서버 세션과 tenant membership 으로 읽기/검토/관리 권한을 검사한다.

**연결 API:** `GET /v1/session; POST /v1/session/tenant`.

**검증:** `uv run pytest tests/acceptance/test_auth.py -q`.

**반드시 단언할 결과:** 테넌트 A 사용자가 B id 를 요청하면 존재 여부를 숨기는 404를 반환한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-038 · 업로드 격리 (P0)

**목적/요구사항:** SEC-002.

**생성/수정 파일:** `packages/proofops/application/uploads_security.py`, `infra/cdk/lib/compute-stack.ts`, `tests/acceptance/test_upload_security.py`.

**입출력/함수:** `verify_quarantined_pdf :: quarantine object + limits → verified/rejected source`.

**선행:** TASK-000, TASK-002.

**구현 내용:** 업로드를 격리 prefix 에서 검증 후 원본 vault 로 복사한다.

**연결 API:** `POST /v1/uploads/{upload_id}/complete`.

**검증:** `uv run pytest tests/acceptance/test_upload_security.py -q`.

**반드시 단언할 결과:** PDF 악성 링크·내장 액션을 실행하지 않고 초과 리소스 PDF 를 중단한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-039 · 외부통신·prompt injection (P0)

**목적/요구사항:** SEC-003.

**생성/수정 파일:** `tests/security/test_prompt_injection.py`, `packages/proofops/application/evidence/packet_guard.py`, `tests/acceptance/test_injection.py`.

**입출력/함수:** `guard_untrusted_packet :: untrusted PDF text + server metadata → bounded safe packet`.

**선행:** TASK-029, TASK-012.

**구현 내용:** PDF 문구를 데이터로만 취급하고 도구/모델/URL 을 서버 allowlist 로 제한한다.

**연결 API:** `POST /v1/preflight`.

**검증:** `uv run pytest tests/acceptance/test_injection.py -q`.

**반드시 단언할 결과:** PDF 의 다른 문서 조회·URL 전송·label 지정 지시가 권한을 바꾸지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-040 · 삭제·보존·복구 (P0)

**목적/요구사항:** SEC-004.

**생성/수정 파일:** `packages/proofops/application/retention.py`, `apps/worker/src/proofops_worker/deletion.py`, `tests/acceptance/test_retention.py`.

**입출력/함수:** `delete_document_tree / reapply_tombstones :: deletion manifest + retention policy → confirmed deletion status`.

**선행:** TASK-022, TASK-031.

**구현 내용:** 원본·파생물·검색·캐시·리뷰·메모리의 범위를 삭제 작업 manifest 로 추적한다.

**연결 API:** `POST /v1/documents/{document_id}/deletion-requests`.

**검증:** `uv run pytest tests/acceptance/test_retention.py -q`.

**반드시 단언할 결과:** 법적 보존 설정과 실제 삭제 완료 상태를 분리하고 TTL 만으로 삭제 완료 처리하지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-041 · 브라우저 세션 보호 (P0)

**목적/요구사항:** SEC-005.

**생성/수정 파일:** `apps/api/src/proofops_api/middleware.py`, `apps/api/src/proofops_api/session.py`, `tests/acceptance/test_session_security.py`.

**입출력/함수:** `verify_csrf / rotate_session / logout :: session cookie + Origin + CSRF → authorized write/session revoke`.

**선행:** TASK-037.

**구현 내용:** HttpOnly/Secure cookie, CSRF, Origin 검사, CSP 를 사용한다.

**연결 API:** `POST /v1/auth/logout`.

**검증:** `uv run pytest tests/acceptance/test_session_security.py -q`.

**반드시 단언할 결과:** CSRF 없는 변경 요청403, 토큰은 localStorage 와 URL 에 저장되지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-042 · 비밀·라이선스·공급망 (P0)

**목적/요구사항:** SEC-006.

**생성/수정 파일:** `scripts/check_licenses.py`, `infra/cdk/lib/iam.ts`, `.github/workflows/ci.yml`, `tests/acceptance/test_supply_chain.py`.

**입출력/함수:** `verify_supply_chain :: lockfiles + SBOM + license decisions → deployment gate`.

**선행:** TASK-000.

**구현 내용:** 의존성 잠금·SBOM·secret scan·라이선스/데이터 권리 gate 를 둔다.

**연결 API:** `POST /v1/preflight`.

**검증:** `uv run pytest tests/acceptance/test_supply_chain.py -q`.

**반드시 단언할 결과:** PyMuPDF 사용 승인이 없는 공개 배포에 해당 adapter 가 포함되지 않는다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-043 · 기존 코드 characterization 와 선택 이식 (P0)

**목적/요구사항:** NFR-001, FR-003.

**생성/수정 파일:** `legacy_reference/`, `evidence/legacy_inspection.json`, `tests/unit/test_legacy_characterization.py`.

**입출력/함수:** `frozen SHA source → verified pure utility/new-adapter migration`.

**선행:** TASK-000.

**구현 내용:** 26장의 R-01~R-05 이식 위험을 characterization 테스트로 확인하고, 허용된 최소 함수만 새 계약에 맞게 이식한다. 원본 commit·파일·라이선스 및 실제 검증 결과를 재사용 기록에 남기며, 기존 scorer·정책·gold label은 이식하지 않는다.

**검증:** `uv run pytest tests/unit/test_legacy_characterization.py -q`.

**반드시 단언할 결과:** A1/B1/B2 dangling-edge 사례를테스트로추가하고 raw 정책·goldlabel 의무단이식을차단한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.

### TASK-044 · AWS staging 실증·배포·복구 게이트 (P0)

**목적/요구사항:** NFR-002, SEC-006.

**생성/수정 파일:** `infra/cdk/`, `tests/e2e/`, `docs/DEPLOYMENT_EVIDENCE.md`.

**입출력/함수:** `verified image/bindings + approval → deployed staging artifact and rollback evidence`.

**선행:** TASK-000, TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021, TASK-022, TASK-025, TASK-026, TASK-027, TASK-028, TASK-029, TASK-030, TASK-031, TASK-032, TASK-033, TASK-034, TASK-035, TASK-036, TASK-037, TASK-038, TASK-039, TASK-040, TASK-041, TASK-042, TASK-043.

**구현 내용:** 조회 p95 1초, 요청 수락 p95 2초를 초기 부하 시험 목표로 둔다. 의존성 잠금·SBOM·secret scan·라이선스/데이터 권리 gate 를 둔다.

**검증:** `pnpm --dir infra/cdk exec cdk synth; pnpm --dir apps/web exec playwright test; uv run python scripts/preflight.py`.

**반드시 단언할 결과:** 승인된공개 PDF 의전과정·tenant 차단·review 경합·export 무결성·복구를실제로검증하고 not_run 항목을공개한다.

**진행:** 실패하는명시사례를먼저작성 → 실행실패확인 → 위인터페이스최소구현 → 같은테스트통과확인 → 관련 contract/security 회귀 → 문서/manifest 갱신.

**완료:** 공통 DoD 와위수용 기준모두충족. fixture/외부 환경미준비로미실행한경우 blocked/not_run 으로남긴다.


### TASK-045 · 기업·실행 옵션 레지스트리 (P0)

요구사항 FR-033, 선행 TASK-000/TASK-037. `packages/proofops/application/registry.py`, `apps/api/src/proofops_api/routers/registry.py`, `apps/web/src/features/upload/CompanySelector.tsx`, `tests/acceptance/test_registry.py`를 구현한다.

입력 actor/tenant 와 CompanyCreate, 출력 Company/CompanyPage/RuntimeOptions. 기업명이 같아도 법인을 자동 병합하지 않는다. 문서 생성 시 Company 와 profile 의 같은 tenant 존재/승인을 검증한다. 없는 기업·다른 tenant profile 에 대한 거부 테스트를 먼저 작성한다. `uv run pytest tests/acceptance/test_registry.py -q`가 통과하고 UI 가 승인 옵션을 조회해야 완료다.
