아래 개발 패키지를 기준으로 ESG ProofOps를 구현해라.

1. AGENTS.md와 docs/00_MASTER_SPEC.md를 먼저 읽어라. 도메인은 sources/PROJECT_DOMAIN_V2_ORIGINAL.md(v2.0)으로 고정한다. 사업 주제·판정 개념을 바꾸지 마라.
2. 기존 esg-evidence-audit는 docs/26_LEGACY_REUSE_AUDIT.md 기준으로 선택 이식한다. 과거 scorer/정책/골드라벨을 그대로 쓰지 마라.
3. docs/27_PARSING_AND_PROVENANCE.md와 docs/28_RULE_ENGINE_CONTRACT.md를 따른다. 원문 위치, 표 숫자 귀속, 불확실 상태, LLM 태깅/규칙 판정을 분리해라.
4. contracts/openapi.yaml, JSONSchema, config, fixtures, task_catalog를 구현 계약으로 삼아라. docs/31_DOMAIN_IMPLEMENTATION_GAPS.md의 빈 계약은 임의 채점 기준을 만들지 말고 지정된 blocked 상태로 처리해라.
5. 현재 저장소·branch·테스트 상태를 확인한 뒤 TASK-000부터 작업 DAG 순서로 진행해라. API·화면·DB·테스트를 함께 연결해라.
6. 각 Task는 실패 테스트→최소 구현→실제 검증→변경 및 미실행 항목 보고 순서로 완료해라. 외부 모델 호출·배포·push는 승인 범위를 확인해라.
7. 최종 완료를 말하기 전에 docs/25_DEFINITION_OF_DONE.md의 해당 수준 검증을 실행해라. 문서 검증과 실제 PDF 정확도/Bedrock/AWS 검증을 구분해라.

우선 현재 코드베이스의 상태와 TASK-000에서 수정할 범위를 확인하고 첫 Task를 수행해라.
