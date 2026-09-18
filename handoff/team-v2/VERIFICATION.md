# 패키지 검증 기록

이 패키지는 구현 지침·스키마·교육용 예제이며 C군 엔진 구현 완료가 아니다.

- input/policy/output JSON Schema 1.1 및 8개 합성 case 형식·hash·참조 검증: PASS.
- 잘못된 status/grade 필드/C5/중복 source/없는 source/가짜 검색완료/역전 기간 거부: PASS.
- 데이터 CSV 8종의 형식·참조 및 누락 근거/기업 split 혼입/보류에 status 부여/claim 연결 실패 거부: PASS.
- 8개 CSV의 145개 열 설명, 규칙 질문 18개 보존.
- 예제·템플릿은 실제 gold가 아니다. 데이터 최종 의미 검토와 실제 원문 검증은 not_run.
- 신규 C1~C4 제품 엔진·DART live·모델·실서비스 E2E/배포: not_run.
- 기존 팀 CI는 초기 실행에서 실패. README 인수인계 상대 링크의 fixture 문제는 게시 README를 절대 GitHub 링크로 수정.
- 초기 CI에서 real_extract_runner/upstage_tagging 실패 및 PRICE_RECHECK_REQUIRED도 관측됨.
  원인 재현·수정은 A의 A0 작업에 명시. 전체 CI 통과를 주장하지 않는다.

- 게시할 팀 checkout에서 tests/unit/test_package_validation.py + tests/acceptance/test_rules.py: 48 passed.
- 새 Python 검사 도구 2개 Ruff check/format: PASS. ZIP 4종 archive integrity: PASS.
- 이 검사는 신규 제품 엔진·모델 성능을 검증한 것이 아님.
