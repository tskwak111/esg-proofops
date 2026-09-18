# 23 · 아키텍처 의사결정

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 의사결정 기록
상태는본개발명세의기술설계결정이며사용자의도메인승인범위를넘지않는다. 변동시원인·대안·회귀증거를새 ADR 에남긴다. 기존 ADR 을조용히덮지않는다.

### ADR-001 · Modular monolith + 실행 경계

**Context:** 한도메인에파싱·AI·UI 가필요.

**Decision:** domain 하나/API·worker·agent 실행분리.

**Alternatives:** microservices/K8s 는운영복잡도.

**Consequences:** 배포 image3종,계약하나는유지.

### ADR-002 · 원문 v2.0 우선

**Context:** 기존 repo 정책과원문다름.

**Decision:** 기존 scorer 교체,유틸/출처만이식.

**Alternatives:** 기존 score 복사시도메인 변경.

**Consequences:** 정책 parity 아닌원문 compliance 검증.

### ADR-003 · 파서 composable adapters

**Context:** 한국어복잡표와좌표차이.

**Decision:** OD 기본+표보조+vision+conflictgate.

**Alternatives:** 단일파서100%보장/전문서다수결거부.

**Consequences:** 원가늘지만잘못된근거자동 확정차단.

### ADR-004 · DynamoDB + S3

**Context:** 원문 AWS 선택·큰 artifact.

**Decision:** metadata DDB/본문 S3/transactionpointer.

**Alternatives:** RDB 추가나대형 DDBitem 부적합.

**Consequences:** FK/CAS/outbox 를 application 이보장.

### ADR-005 · SQS+DDB 내구성

**Context:** 작업중단·중복전달.

**Decision:** outbox/lease/fence/checkpoint.

**Alternatives:** API BackgroundTasks/agentmemory 소유거부.

**Consequences:** 더복잡하지만처리상태정직하게보존.

### ADR-006 · 3회고정 packet 태깅

**Context:** 원문자기일관성요구.

**Decision:** 같은 packet,distinctreplica,criticaldisagreementreview.

**Alternatives:** 3회다른 RAG/같은 rawcache 복사거부.

**Consequences:** 비용/일치도와정확도분리.

### ADR-007 · 근거 존재와 귀속 분리

**Context:** 같은페이지값도다른회사/기간가능.

**Decision:** exactcitation+typedbindingguard.

**Alternatives:** semantic 유사도만으로인정거부.

**Consequences:** 더많은 undetermined/사람검토.

### ADR-008 · 도메인 gap fail closed

**Context:** 일부사다리/조항미정.

**Decision:** nullabledecision+명시 gap.

**Alternatives:** 임의 E 기준생성/미지값 false 거부.

**Consequences:** 기능개발은가능,미승인자동판정제한.

### ADR-009 · OpenSearch 단일 generation

**Context:** 동일공시 RAG·tenant 격리.

**Decision:** typedfilters+1024d 새 indexversion.

**Alternatives:** 무필터 globalRAG/동일 index 차원변경거부.

**Consequences:** 고정비실측및원문재검증필요.

### ADR-010 · Cognito BFF 세션

**Context:** 미공개원고토큰보호.

**Decision:** opaqueHttpOnlysession+CSRF.

**Alternatives:** localStoragebearertoken 거부.

**Consequences:** 서버세션스토어/refresh 운영.

### ADR-011 · Immutable revision/export

**Context:** 감사결과재현.

**Decision:** 새태깅/판정 revision+epochsnapshot.

**Alternatives:** lastwritewins/동적최신 PDF 거부.

**Consequences:** 저장량증가,명확한삭제 manifest 필요.

### ADR-012 · AgentCore 기능 단계 도입

**Context:** 원문운영기술목록.

**Decision:** Runtime/observabilityP0,MemoryOFF,Gateway/Identity 조건부.

**Alternatives:** 모든기능의무사용거부.

**Consequences:** 대회요건추가시 feature 배치만재검토.

### ADR-013 · PyMuPDF 라이선스 gate

**Context:** 기존 parser 의라이선스영향.

**Decision:** 기본 PDFium/OD/pdfplumber;PyMuPDF 선택형.

**Alternatives:** 무검토 copy 배포거부.

**Consequences:** license 승인과실측후만활성화.

### ADR-014 · Schema-first · 합성/실증 구분

**Context:** 코덱스 handoff 정확성.

**Decision:** OpenAPI/JSONSchema/fixtures+실시험증거.

**Alternatives:** 문서만으로정확도100%주장거부.

**Consequences:** 환경미제공항목은명시 not_run.
