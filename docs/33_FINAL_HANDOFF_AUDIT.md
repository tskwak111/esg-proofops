# 33 · 최종 개발 인계 점검

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 이번 점검에서 반영한 구조 보완
| 발견한 연결 문제 | 반영한 계약 | 남겨 둔 검증 |
|---|---|---|
| 기존 scorer 의 OR/ANY 기준과 v2.0 사다리 차이 | grader 교체, source-derived YAML, 합성 경계 사례 | 실제 새 엔진 구현 테스트 |
| 동일 문서 text 중복 병합 후 dangling source | canonical alias·다중 provenance·edge endpoint 검사 | 실제 파서/graph 통합 시험 |
| native bbox·물리/인쇄 페이지 혼동 | canonical 좌표·affine·origin page mapping | 회전/CropBox PDF viewer 실증 |
| LLM3회가 같은 캐시/다른 RAG 를 읽을 가능성 | frozen packet + replicate signature | 실제 model 호출 ledger |
| S3/DDB/SQS 의 원자성 오해 | outbox·lease/fencing·불변 artifact 후 pointer publish | worker kill/duplicate fault test |
| 검토 중 export 의 mixed revision | epoch read fence + snapshot manifest | review/export 경합 테스트 |
| 업로드 UI 에 Company 선택 데이터 경로 누락 | FR-033/TASK-045, companies/runtime-options API | 등록→업로드 UI E2E |
| 규칙·조항·법제 미정 값을 임의 완성할 위험 | claim 별 gate, nullable 미판정, 근거검증 상태 | 도메인 담당자 승인 |
| README 실행 명령이 앱 완성으로 오인될 위험 | 문서 검증 명령과 구현 후 명령 명시 분리 | Codex 실제 구현 완료 증거 |

## 2. 인계 가능 범위
현재 아키텍처·파일 책임·API/스키마·상태 전이·파서조합·규칙 경계·검토/감사·보안·작업 순서는 문서에 정의했다. 코딩 에이전트는 새 제품을 재설계하지 않고 정해진 경계를 구현한다. 다만 사용자 계정의 AWS/모델/권리/대회 입력과 원문 자체의 미정 도메인 매핑은 이 문서가 창작해서 결정하지 않는다. 해당 값이 없는 상태에서 어떤 API/화면/판정 상태가 나와야 하는지까지 정해 두었다.

## 3. 실제 검증과 미실행
패키지 정적 검증의 실제 결과는 `evidence/package_validation.json`과 `.txt`를 확인한다. 이 결과는 JSON/YAML/schema/참조/요구사항/작업 DAG/합성 계약의 일관성을 뜻한다. 실제 repo 테스트·PDF 파싱 정확도·실제 모델 성능·클라우드 운영을 검증한 결과가 아니다. 미실행 항목은 `sources/source_manifest.json`, `evidence/legacy_inspection.json`,30장에 기재했다.

## 4. 최종 확인 기준
자료의 도메인 범위를 변경하지 않았는지, 원문/규칙 해시가 보존됐는지, grade 생성 권한이 순수 엔진에만 있는지, claim 별 source 를 추적할 수 있는지, 모델 결과가 실패를 성공으로 위장하지 않는지, 모든 requirement 에 API/task/test 가 연결되는지, 미정 영역이 구체적인 gate 로 표현되는지를 확인한다. 기능적으로 없는 것을 만들어졌다고 표시하지 않는다.
