# FXB · 현재 응답 공개 확정 계약

새 C3 v2 정책 해시는 `c3-current-response-binding-v1`을 포함한다. 기존 C2/C3 v1과
FXB 이전 C3 v2 정책 및 v20 분석 정책 해시는 그대로 재생한다. 새 분석 실행은
`grade-relevant-unanimity-v2`와 새 C3 정책을 사용한다. 도메인 사다리는 바꾸지 않는다.

공개 확정에 사용하는 세 응답 각각은 현재 요청의 tenant/original/replica/role,
wire/schema/model/prompt/analysis policy/packet/request 해시와 일치해야 한다.
서버 transport는 현재 broker ledger의 request/signature/정산 receipt와 원시 provider
sidecar를 대조한 뒤에만 `authenticated=true`, `fresh_model_call=true`, `replay=false`
영수증을 발급한다. assembly는 요청을 재구성하고 응답 내용·provider ID·영수증 해시를
재검사한다. 원문 fingerprint·승인 rulepack·독립 3회·Python 판정 검사도 유지한다.
이 영수증은 신뢰된 서버 transport의 산출물이며 외부 사용자나 모델이 발급하지 않는다.

저장 응답·exact cache hit·과거 응답 투영·영수증 누락·결속 오류는 후보/검증용이며
새 assembly의 `public_auto_confirmed=false`다. 이전 정책으로 저장된 불변 공개 revision은
원래 reader로 읽지만 이전 정책의 새 publication 생성은 거부한다. 과거 결과를 수정하지 않는다.

F5 v2는 만장일치 conflict를 conflict로 보존하며 present/absent로 승격하지 않는다.
검토 상태와 Python의 grade/label=null 보류도 유지한다. 이전 F5/partial-facts의 재생은 유지한다.
API/DB column migration은 없고 rollback은 새 실행 배정을 중단하고 양쪽 reader를 보존한다.
실제 새 모델 세 회의 의미 정확도는 별도 승인된 실호출 검증 대상이다.
