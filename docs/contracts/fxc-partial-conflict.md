# FXC · 부분 회차 실패 시 conflict 보존

새 `grade-relevant-unanimity-v3`는 생존한 guarded 요소에 conflict가 있으면
다른 회차의 MODEL_UNAVAILABLE 등 허용된 부분 실패에도 conflict 후보를 보존한다.
서로 다른 유효 투표의 conflict 처리와 원문·provenance·provider replay 검사는 유지한다.
부분 회차의 present/absent는 승격하지 않고 검토 상태는 needs_review로 유지한다.
등급 관련 conflict의 Python 판정은 evidence_grade=null, label=null이다.

v3는 별도 fact assembly 정책 hash를 저장하며 새 로컬 v20 분석 실행의 기본값이다.
기존 v1/v2의 정책·hash·알고리즘과 이전 v20 분석 pin은 그대로 선택·재생한다.
`FINALS_I20_PRE_FXC_POLICY`는 FXB 시점 v20 정책을 보존한다.
API/DB 필드 변경이나 migration은 없다. 롤백은 새 실행에 이전 정책 pin을 지정하고
이미 저장된 v3 산출물과 호환 reader를 보존한다. 도메인 사다리는 변경하지 않는다.
실제 모델 호출·push·배포·EC2 변경 없이 합성 입력과 로컬 테스트로 검증한다.
