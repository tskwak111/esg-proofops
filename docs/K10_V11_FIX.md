# K10 v11 잔여 태깅·전송 수정 계약

기준은 `78cdfe2` / `FINALS_I10_POLICY`다. 새 `FINALS_K10_POLICY`(v1)와 `FINALS_K10_V2_POLICY`는 명시적인
hash opt-in이며 v11 기본값·과거 정책·태깅·판정·보고서 revision을 수정하지 않는다.
LLM은 추출·태깅만, 등급은 기존 Python 규칙엔진만 계산한다. K=3/F1,
원문·귀속·tenant/version/replica 가드와 추정치·Scope3·전망 보류를 유지한다.

K10은 짧은 common 지침과 기존 track 카드·tail을 조합하여 동일 16KiB 한도를
지킨다. evidence catalog·원문을 줄이지 않으며, 여전히 초과하면 무전송 보류한다.
M1 보고체계·조사 방법과 M5/M4를 독립 태깅하고, P1은 주장 술어에 직접 연결된
수량을 인용하도록 안내한다. G3 연도만, G4 Scope/지표명만, 일반 성과관리·감축
수단 확보 추진의 M4는 present 후보를 unknown으로 보류한다.
v2는 실제 LG 인용의 `Scope 1 및 Scope 2 배출량`까지 Scope 단독 가드를 확장한다.
v1 hash/reader/실측은 그대로 보존하며 v2는 별도 신규 선택이다. 이는 좁은 음성
가드이며 원문 밖 사실, 새 present 투표, absent 또는 새 등급 임계값을 만들지 않는다.

전송은 한 run의 scheduler가 소유한 배타적 HTTP/1 연결 pool(유휴 최대16,
30초)을 사용한다. TLS 인증 검증은 표준 SSL context를 유지한다. 완전히 읽고
파싱한 정상 응답만 연결을 반환하며 실패·부분/초과 응답·서버 close는 폐기한다.
연결 신원/재사용·connect+TLS 시간·TLS session 재사용·HTTP send 시작 여부를
기록한다. 기존 I10 진단은 send phase가 없으므로 11건 USD0.22를 회수하거나
재시도하지 않는다. 서버측 끊김의 세부 원인은 새 실측 없이 확정하지 않는다.

명시적인 connect() 실패로 HTTP request()가 시작되지 않았음이 증명된 경우만
한 번 재시도한다. 새 attempt_id·예약·scheduler admission·권한/가격 확인을 거친다.
request() 시작 이후 timeout/SSL EOF/disconnect/응답 실패는 도달 여부 unknown,
원래 비용 예약·해당 주장 보류를 유지한다. 재사용 연결은 자동 재접속을 금지한다.
기존 overload403 재시도와 동일한 전체 1회 transport retry allowance를 공유한다.

공개 API/DTO·hosted DB column 변경은 없다. 내부 broker의 새 선택적 인자
`allow_connect_not_sent=False`는 K10에서만 명시 활성화한다. broker는 무전송
예약을 actual=0/settled로 기록하고 다음 시도에 새 call_id/예약을 요구한다.
로컬 probe DB에는 K10 구성 시 `CREATE TABLE IF NOT EXISTS
probe_transport_attempts(attempt_id PRIMARY KEY, request_id, bound, state, diagnostic)`를
추가한다. 각 물리 예약은 기존 논리 USD0.02 envelope 안에서 직렬로 배정하며,
가능 도달 시도가 있으면 envelope를 회수하지 않는다. 시도별 bound를 논리 비용에
중복 합산하지 않는다. 기존 reader는 추가 table/receipt 필드를 무시하여 과거
probe_calls 비용을 그대로 읽는다. 기존 원장·예약·불변 영수증을 삭제하지 않는다.
Rollback은 신규 K10 배정을 중단하고 기존 v11 hash를 선택한다. K10 산출물은
호환 reader에 보존하며, K10을 모르는 reader에 신규 결과를 배정하지 않는다.
새 dependency·모델 변경·rulepack 변경·push/배포/클라우드 변경은 없다.

## K11: 동일 주장 기준연도·기준값 재추출

K11 opt-in `finals-20261013-k11-v2`는 G3에 기준연도와 기준값을 각각 원문 인용하고,
`normalized_value`를 단위 포함 기준값 인용 그대로 반환하도록 명시한다.
기준 수준 유지 목표는 동일 값의 G2/G3 역할을 원문 문맥으로 확인하며 다른 주장의 값을
차용하지 않는다. 서버의 인용·귀속·정규값 일치·K=3 가드와 Python 등급 계산은 그대로다.
LG p24 기존 응답은 두 값을 인용했지만 정규값 null로 보류됐다. 새 독립 3응답은 G3와
G2 모두 `951만 tCO₂e`로 합의했다. G4·G5·G6는 unknown이고 공개 확정등급은 미생성이다.
v12 기본값, K10 v1/v2, K11 중간 v1의 정책 hash·renderer·저장 응답을 보존한다.
새 v2 정책 hash는 `01ed39928d5a5c35671a78bd6eedb8e42b68a7ea40a1b0fccf4e444b32047c02`다.
API·DB·DTO 변경과 migration은 없다. 롤백은 K11 hash 선택을 중단하고 원래 v12 pin을
사용한다. 새 태깅·근거 산출물을 삭제하거나 기존 revision을 덮어쓰지 않는다.
재현: `python -m evaluation.k11_baseline --root <repo-root> --output <new-output> --live`.
실호출은 task USD0.2 및 공유 누적 원장을 적용한다. 저장 응답 검증은 `--verify-saved`로
실행하며 네트워크를 차단한다. K11 보고서의 회귀 재생은 추출 성능·모델 정확도를 혼동하지 않는다.
