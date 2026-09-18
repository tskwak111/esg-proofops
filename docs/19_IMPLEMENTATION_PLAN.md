# 19 · 구현 계획

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

> Agentic worker 실행 안내: 한 Task 씩 실패 테스트 → 최소 구현 → 검증 → 코드 검토 → 작은 commit 으로 진행한다. 다음 작업은 아래 dependency DAG 가 허용할 때만 시작한다.

**목표:** 원문 v2.0 도메인을 바꾸지 않고, PDF→근거→태깅→규칙→사람검토→감사 리포트를 구현한다.
**Architecture:** 모듈형 단일 Python domain, FastAPI/worker/AgentCore 실행 경계. S3+DynamoDB 의 immutable artifacts 와 CAS heads.
**Tech stack:** Python3.12/Java21, OpenDataLoader2.5.7, Bedrock+Strands, DynamoDB/S3/SQS/OpenSearch, React/TS.
**Spec:** `00_MASTER_SPEC.md`, `28_RULE_ENGINE_CONTRACT.md`, `27_PARSING_AND_PROVENANCE.md`.

## 1. 전역 제약
도메인·라벨 임의 변경 금지. 기준 조항/모델 ARN/성능 수치 생성 금지. full mode topic quota 금지. unknown→absent 변환 금지. source 없는 present 금지. grade 를 LLM 또는 사람이 직접 쓰는 API 금지. 텍스트유사도만으로근거 귀속금지. source/tenant/replicate/version hash 없이캐시 reuse 금지. 기존 연구코드 일괄삭제금지.

## 2. 단계별 작업
| Phase | 목표 | 주요 Tasks | 선행 조건 | 완료 기준 |
|---|---|---|---|---|
| 0 계약/기반 | repo·DTO·검증 harness·legacy snapshot |000,043 | 없음 | 계약 검증과가짜운영차단 |
| 1 순수규칙 | G/P/M 사다리·특칙·gap·근거모델 |002,025,014–018,033 |0 | synthetic rule/geometry/hash tests |
| 2 내구상태/권한 | auth/session·업로드검증·jobs/outbox·감사·preflight |037,041,038,001,028,022,029,042 |0/1 | tenant 차단·CAS·중복 retry 검증 |
| 3 문서구조 | OD/pdfplumber/vision 경계, tables/numeric/GRI |003–006 |1/2 | 원문→canonical provenance 검증 |
| 4 태깅·근거 | claims/assurance/RAG/citation/binding/3회/cost |007–013,030,039 |1/2/3 | frozen packet + source guard |
| 5 검토제품 | review/rescore/coverage/summary/UI |019,020,026,027,036 |4 | 수정→새 decision/audit, partial UX |
| 6 출력·평가 | report/export/eval/observability/load/deletion |021,031,032,034,035,040 |5 | 스냅샷·gold 격리·운영실증 |
| 7 AWS 실증 | deployment/restore/demo evidence |044 |모든 P0 | 실제 staging evidence 및잔여 gate 공개 |
| P1 보존 기능 | 다년도·광고별도모드 |023,024 |관련 P0+승인규칙 | mode 분리/not_run 확인 |

Phase 는 설명을 위한 작업 묶음이다. 실제 병렬 가능성/정확한 선행순서는 `contracts/task_catalog.json`의 dependencies 가정본이다. 예를들어비전 live 검증은 preflight 전완료할수없지만파서어댑터계약테스트는 synthetic packet 으로먼저가능하다. 규칙 확정 가능한부분을 태깅튜닝보다먼저검증한다.

## 3. Task 실행 절차
- [ ] Task 와연결된 Requirement·API/DTO·fixture·source section 을읽는다.
- [ ] 지정 test 파일에 positive/negative/race 테스트를먼저만든다. 아직함수가없거나행동이틀려실패함을확인한다.
- [ ] 파일/인터페이스책임을넘지않는최소구현을한다. 임의 domain 확장은하지않는다.
- [ ] Task 명령과관련 unit/contract 검증을실행하고실제 stdout/exitcode 를남긴다.
- [ ] formatting/type/build/security 영향검사를실행한다. external API 가필요한시험은승인없으면 not_run 이라고기록한다.
- [ ] 문서·schema·traceability 변경을함께반영하고작은 commit 을만든다. 다음 Task 로넘기기전검토한다.

## 4. 수직 slice checkpoint
첫 slice 는합성 PDF/source fixture→순수사다리→JSON 리포트다. 다음 slice 는공개 PDF+실 OD→확정태깅 fixture→원문링크, 이후실 Bedrock3회, 마지막 review+export 다. 합성 결과와실제추론결과를 metadata/UI 에서구별한다. 모든통합을마지막주에몰아서붙이지않는다.

## 5. 일정 입력
대회정확한2026제출마감/서비스허용/팀원수는사용자계정/공지로확인할입력이다. 공개대회페이지의월일만보고연도를단정하지않는다. 일정은대회마감에맞춰 Phase 별내부마일스톤을배정하되현재 명세에서없는팀원/시간예산을꾸며내지않는다. 역할은도메인담당(기준·gold) / 엔지니어링담당(코드·infra)으로유지하고동일인이겸임할수있다.


## 6. 한 가지 유효한 실행 순서

TASK-000 → TASK-002 → TASK-025 → TASK-037 → TASK-042 → TASK-043 → TASK-014 → TASK-017 → TASK-018 → TASK-029 → TASK-033 → TASK-038 → TASK-041 → TASK-045 → TASK-001 → TASK-015 → TASK-016 → TASK-022 → TASK-024 → TASK-028 → TASK-003 → TASK-030 → TASK-004 → TASK-006 → TASK-007 → TASK-008 → TASK-035 → TASK-005 → TASK-009 → TASK-011 → TASK-012 → TASK-027 → TASK-013 → TASK-039 → TASK-010 → TASK-019 → TASK-032 → TASK-020 → TASK-026 → TASK-021 → TASK-034 → TASK-036 → TASK-023 → TASK-031 → TASK-040 → TASK-044

P1 작업은 대회 P0 게이트의 선행 조건으로 강제하지 않는다. Task DAG 가 최종 기준이다.


## 7. 최종 Handoff 보완
TASK-045(기업·실행 옵션 API)를 Phase2의 문서 생성(TASK-001)보다 먼저 수행한다. 최종 실행 순서는 `contracts/task_execution_order.json`을 기준으로 한다. 상단의 예시 순서보다 이 기계 판독 순서가 우선한다.
