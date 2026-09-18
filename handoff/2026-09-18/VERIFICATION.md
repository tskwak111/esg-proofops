# 패키지 검증 · 2026-09-18

- contract/validate.py: PASS (3 JSON Schema, 합성 입력/출력, hash, status 분리, grade 유입/C5 거부).
- Ruff check 및 format check: PASS (새 validator).
- 기존 tests/acceptance/test_rules.py: 47 passed.
- scripts/validate_package.py: 797 checks passed; 문서/계약 검사이며 앱 성능 검증이 아님.
- CSV 8종: 헤더 및 열 수 검증, 미정 규칙 18행 확인.
- 패키지 예제는 모두 synthetic. 실제 gold labels는 아직 작성되지 않음.
- 신규 C1/C3 엔진 구현·DART live·실제 모델·전체 앱 E2E/성능/클라우드: not_run.
- 현재 추적 파일과 패키지의 알려진 키 패턴 검사: 후보 없음. 모든 종류의 비밀 부재를 보증하는 인증은 아님.
- Git 기록 전체를 게시하지 않고 254f228 기준 현재 추적 파일의 새 스냅샷으로 게시.
- .env 실제값, .local, 기업보고서 원본, legacy_reference, 설치 산출물은 제외.
