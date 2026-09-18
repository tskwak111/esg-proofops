# ESG ProofOps · 2인 개발 + 도메인 담당 인수인계

작성: 2026-09-18. 코드 기준: `254f22852ce4f0e09f283cb818ef73c09fddeaaa`.
이 패키지는 협업 계약·작업 지시·데이터 양식이다. 연계 모듈 구현 완료나 성능 인증이 아니다.

- 개발자 A(기존 개발자): [업무 분할·통합](TEAM_PLAN.md)
- 개발자 B(신규 개발자): [시작 안내](developer/START_HERE.md), [작업 계획](developer/IMPLEMENTATION_PLAN.md)
- 도메인/데이터 담당: [업무 안내](domain/START_HERE.md), [주석 가이드](domain/ANNOTATION_GUIDE.md), `domain/templates/*.csv`
- 공통 경계: [연계 계약](contract/CONTRACT.md), JSON Schema, 합성 입력·출력 예제
- 원문: `reference/PROJECT_V2_2.md`, `reference/RECONCILIATION_SPEC.md`; 해시 manifest 포함.

## 합의한 경계
A는 기존 E 입증 파이프라인과 제품 통합, B는 독립 DART·C1/C3 모듈을 맡는다.
B는 A의 API/DB/UI가 없어도 JSON 입력과 로컬 CLI로 개발·테스트할 수 있다.
도메인 담당은 원문 근거·정답 태그와 규칙 제안을 제공한다. 모호한 기준을 혼자 최종 법적 판단하지 않는다.
기존 G/P/M 등급과 라벨은 유지한다. 신규 C군은 별도 출력이며 기존 미정 계약을 자동 해제하지 않는다.
이 협업 계약은 연계 개발 경계에 적용하고 기존 v2.0 원문과 실행 계약은 소급 변경하지 않는다.

## 전달 방법
개발자에게는 private GitHub 코드 저장소와 developer-package.zip을, 데이터 담당에게는 domain-package.zip을 전달한다.
ZIP만으로 전체 앱을 실행하는 것은 아니다. B는 저장소를 clone해야 한다.
키·기업보고서 원본·.local·모델 응답 원본은 배포물에 포함하지 않는다. 공개 PDF도 권리를 확인한 뒤 별도 공유한다.
두 사람의 GitHub 아이디가 아직 없어 collaborator 초대는 하지 않았다. 계정 확인 후 저장소 소유자가 초대한다.
