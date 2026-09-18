# 팀 개발 패키지 v2 · 전체 범위 상세판

이 버전이 `handoff/2026-09-18`의 분담·일정 안내를 대체한다. 날짜별 일정은 사용하지 않는다.
9월 21일은 각 담당의 1차 구현·자료 제출 목표다. 아래 전체 범위와 품질 검증을 삭제하는 마감이 아니다.
앱 기준 commit은 254f228, 팀 저장소 초기 snapshot은 09b574f. 이 문서는 앞으로 할 일을 설명하며 구현 완료를 뜻하지 않는다.

## 처음 받은 사람이 읽을 순서
1. `TEAM_PLAN.md`: 누가 무엇을 만들고 어디서 만나는지.
2. `SCOPE_MATRIX.md`: 전체 범위와 담당·통과 조건.
3. 개발자 A는 `developer-a/PLAYBOOK.md`, B는 `developer/START_HERE.md` → `developer/PLAYBOOK.md`.
4. 데이터 담당은 `domain/START_HERE.md` → `domain/ANNOTATION_GUIDE.md` → `domain/DATA_DICTIONARY.md`.
5. 공동 작업은 `contract/CONTRACT.md`, `contract/SCHEMA_GUIDE.md`, `delivery/INTEGRATION.md`.
6. 맡긴 사람은 `delivery/ASSIGNMENT_MESSAGES.md`의 문구를 복사해 전달한다.

## 파일 구분
- `domain/templates`: 빈 제출 양식. rules에는 질문만 미리 입력되어 있다.
- `domain/examples`: 교육용 합성 예제. 실제 gold로 사용 금지.
- `contract/examples`: JSON 계약의 양성·음성·보류 사례. 실제 판정엔진 아님.
- `reference`: 사용자 제공 원문. 조항·법률 사실 검증 완료라는 뜻 아님.
- `delivery`: PR·작업 상태·통합·출시 점검 양식.
- `VERIFICATION.md`: 이 패키지에서 실제 확인한 것과 not_run.

## 범위 유지 원칙
G/P/M 판정, E 본문+환경 Data+Appendix, 원문 검증, 수치·보증·검토·불변 보고서,
공시 패키지/DART/C1~C4, 평가·운영·발표 준비를 작업 목록에서 제거하지 않는다.
C1/C3부터 구현하되 C2/C4도 B의 전체 작업에 포함한다.
C5 회계판단은 원문 명세가 금지한 2단계이므로 실행 가드와 금지 사례 검증이 제출물이다.
광고·다년도·세이프하버·산업/유예는 기존 계약의 승인 게이트를 유지한다. 미정 규칙을 새로 지어내서 완료하지 않는다.

실제 과제는 작지 않다. 21일까지는 각자의 기능과 자료를 통합할 수 있는 형태로 제출하고,
이후 전체 연결·독립 평가·오류 수정을 계속한다. 기능 구현, 데이터 검토, 성능 입증은 별도 체크한다.
