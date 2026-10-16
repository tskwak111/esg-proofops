# OpenAI HTTP 오류 진단 계약 v1

HTTP 실패의 원인 식별 정보가 기존 transport에서 소실되어 HX1의 403을
복원할 수 없었다. 새 `HTTP_ERROR_POLICY`의 canonical hash를 각 진단에 기록한다.
태깅·추출 정책, wire body, 모델, 등급 계산과 기존 성공 receipt 의미는 바꾸지 않는다.

`<provider-ledger>.responses/<diagnostic-hash>.http-error.json`에 request body의
canonical hash, HTTP 상태, 검증된 x-request-id 및 숫자 Retry-After,
제한된 error code/type, 최대 1 MiB+1 읽기 결과의 SHA-256·크기·잘림 여부를 저장한다.
본문 문자열, error message/param, 요청 내용, 키, 쿠키는 저장하지 않는다.
request hash는 기존 probe ledger signature와 연결한다. request ID는 HTTP ID다.

새 sidecar는 0600 파일과 기존 0700 responses 디렉터리를 사용한다.
O_EXCL로 기존 기록을 덮어쓰지 않으며 저장 실패는 원래 HTTP 오류를 유지한다.
진단은 best effort이고 성공 receipt나 지출 정산의 증거로 사용하지 않는다.
403 재시도, uncertain 예약 해제, transport-stop 재설정은 추가하지 않는다.

공개 API·DB schema/migration은 없다. 과거 sidecar가 없는 결과는 진단 미확보다.
기존 replay는 성공 receipt와 기존 정책을 그대로 읽는다. Rollback은 새 sidecar
생성만 중단하고 저장된 파일·과거 결과·uncertain 예약·stop 기록은 보존한다.
비JSON·비정상 error 객체도 안전하게 기록하며 원래 HTTP 분류를 유지한다.
