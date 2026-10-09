# INT1 통합 무인 프로필

`--analysis-profile finals-unattended-v1`은 새 run 전용이다. `analyze_report`는 쪽을 주지 않으면 AS1 `bounded-v1`을 적용하고 mixed-v1(주장≤10쪽·합집합≤30쪽), claim-source-v3, PT1 무인 처리, 선택된 줄바꿈 연결, glyph prefetch 4를 한 번에 켠다. 기존 로컬 기본과 과거 manifest는 그대로다. `finals_demo`는 `PROOFOPS_ANALYSIS_PROFILE=finals-unattended-v1`; 공개 요청은 `X-Pipeline-Profile: finals-unattended-v1`, 웹 설정은 `VITE_ANALYSIS_PROFILE=finals-unattended-v1`이다. q9 공개 handler도 같은 range·합산 가드를 사용하고 공유 원장 미설정 시 dispatch를 차단한다. HS1의 hosted 프로세스 연결·배포는 INT1 범위 밖이다. r108-public을 수정하지 않는다.

## 등급 표시와 불변 계약

확정 `decision`·`review_inputs`는 null이다. 숫자 잠정 등급이 없으면 `provisional_grade.display_type=range`, `display=잠정·범위`, `grade_range={floor,ceiling,open_elements,assumptions,rule_gap,rule_pack_sha256}`를 반환한다. `reason`에 보류 원인을 남긴다. 입력의 unknown/conflict/N/A를 바꾸지 않고 같은 순수 Python `_select` 사다리의 가능한 결과를 표시용 boolean 조합으로 계산한다. 사전분류 미합의는 모든 트랙의 합집합, 매핑/branch가 없는 규칙은 rulepack 전체 등급 범위로 넓힌다. 이는 확인되지 않은 도메인 규칙을 승인하는 등급이 아니다. 향후 원문 확인/태깅 수정으로 범위를 좁힐 수 있다. 검증된 present만 실제 사실 입력으로 유지한다.

## 단계 중첩

파싱된 전체 근거 그래프는 먼저 고정한다. 한 쪽의 추출 응답이 모두 돌아오면 그 쪽의 literal 주장부터 3회 사전분류·관계·요소 태깅을 시작한다. 다른 쪽 추출과 겹친다. 주장 안의 세 replica는 동일한 frozen packet을 읽으며 기존 합의·프롬프트는 유지한다. 초기 그래프는 전체 parse graph이고, 아직 완료되지 않은 claim-span attestation을 근거 승격에 사용하지 않는다. 원문 확인은 추출 뒤 한 번 수행하고 기존 전체 receipt cache로 즉시 재생 중복을 줄인다. 나중 검증된 원문 상태는 표시만 갱신하며 이미 실행된 태깅 사실/패킷을 소급 승격하지 않는다. 이 때문에 원문 검증 뒤 태깅하는 PT1보다 숫자 잠정등급이 적어질 수 있으며, 범위로 정직하게 남긴다.

쪽별 claim hash·parse checkpoint hash·graph hash·출력·usage·시간은 extract checkpoint의 `page_tag_pipeline`에 함께 저장한다. 최종 tag 단계는 동일 literal claim과 전체 parse graph를 확인한 뒤 결과를 재사용한다. 공개 전 기존 전체 source replay·tenant/version/head·lease 검사를 유지한다. 부분 실패는 terminal reason과 범위이며 확정 revision을 발행하지 않는다. 초기 파싱 완료분까지의 중첩은 하지 않는다(전체 근거 그래프를 고정해야 함).

## 비용과 계정 한도

공통 `SpendGuard` SQLite sidecar는 `BEGIN IMMEDIATE`로 run USD1.0·UTC일 USD7·행사 USD7 및 선택적 task/group 한도를 동시에 예약한다. 파서는 실제 페이지×고정 가격, 모델은 요청당 USD0.02(두 유료 attempt 포함)를 먼저 예약한다. 같은 요청 재전송과 정책 변경을 거절한다. 불명확한 전송은 전액 예약을 유지한다. 전송 전 provider ledger 행이 전혀 없는 실패만 0으로 정산한다. 기존 provider USD 한도/미정산과 R108 원장 가드는 계속 적용된다. 새 DB는 별도 sidecar이고 기존 SQL column migration/새 의존성이 없다.

`PROOFOPS_SPEND_LEDGER`와 `PROOFOPS_SPEND_EVENT`를 모든 프로세스에서 동일하게 지정해야 한다. HS1 인터페이스는 `SpendGuard(path,event_id=...)`, `configure_run(run_id,day=UTC 날짜)`, `reserve(run_id,provider,request_id,bound)` → dispatch → `settle(request_id,actual_or_None)`이다. 일·행사 한도는 LLM뿐 아니라 parser도 합산한다. 원장 접근은 trusted worker 경계이며 사용자 요청이 event/day/한도를 정하지 않는다. 기존 provider 원장을 초기화하지 않는다.

`PROOFOPS_OPENAI_RATE_OBSERVATION`은 24시간 이내의 모델·시각·응답 한도 헤더를 가진 private JSON이다. 계정 RPM/TPM와 잔여량에서 full token capacity 및 두 attempt를 예약할 수 있는 최대 16 슬롯을 선택한다. 관측 없으면 8 이하이고 낮은 운영자 상한을 존중한다. probe에서 관측한 16×0.02=USD0.32가 최소 동시 예약이다. 전체 파이프라인 HTTP semaphore는 추출/태깅을 합쳐 한도를 지킨다. 별도 Upstage provider 원장의 실패 요청 USD1 보수 예약은 그대로 유지하므로 실제 페이지 가격의 sidecar 노출보다 task 원장 노출이 클 수 있다. 유료 작업 상한은 더 보수적인 task 원장을 따른다.

## 재생과 rollback

run snapshot에 `analysis_profile_policy`와 canonical SHA-256을 저장하고 input_hash에 포함한다. tag checkpoint도 그 hash를 pin하며 변경된 reader 정책은 거절한다. 원문·parse manifest·태깅 replica·규칙·프롬프트 해시는 기존 경로대로 보존한다. 추가 필드는 새 프로필의 opaque checkpoint/optional API 표시 필드에만 존재한다. 기존 snapshot/revision/report를 재작성하지 않는다.

Rollback은 새 프로필 배정을 끄고 기존 기본을 사용한다. 새 프로필 checkpoint는 해당 reader를 유지하며 구버전 reader에 배정하지 않는다. 비용 sidecar 및 모든 provider 원장은 삭제/리셋하지 않는다. 기존 프로필의 configuration hash와 출력은 소급 변경하지 않는다.
