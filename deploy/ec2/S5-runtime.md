# S5 실행 설정 계약

새 정책은 `FINALS_S5_POLICY`의 hash를 `analysis_policy_sha256`으로 명시해 선택한다.
I9의 새 기본 `FINALS_I9_POLICY`(v9)는 v8 태깅에 S4 캐시·게시와 S5 실행 설정을 통합한다.
`FINALS_I7_POLICY`·`FINALS_I8_POLICY`와 모든 과거 hash/reader는 그대로 유지한다.
`live.json`의 `llm_max_workers`(1–16, 기본8), `llm_requests_per_second`(정수1–8,
기본4)는 새 실행 접수 시 private run options에 해시와 함께 고정한다.
대기 중 live 설정을 바꿔도 접수된 S5 실행의 값은 바뀌지 않는다.
구 정책에 RPS 키를 넣으면 소비되는 것으로 오인하지 않도록 명시적으로 거절한다.

추출/사전분류/관계/요소는 동일 물리 호출 상한을 공유한다. 요소→관계→사전분류→추출
순으로 기다리는 요청을 처리하며 역할 내부는 FIFO다. 8회 추월된 가장 오래된 요청을
우선하여 추출도 굶지 않는다. 형식 재시도와 허용된 structured 403 재시도는 매번 다시
입장한다. retry sleep/JSON 처리 동안 슬롯은 반환한다. 3개 replica 및 단계 barrier,
연속 opaque 403 K=3, 429 Retry-After, quota/가격·예약/정산·삭제/fence는 유지한다.
private provider receipt에 예약·큐 입장/퇴장·실행 종료·영수증 저장 시작 monotonic을
기록한다. HTTP/Broker 합친 구간을 순수 네트워크 지연으로 부르지 않는다.

Compose 환경파일의 `WORKER_CPUS`, `WORKER_MEMORY`가 실제 worker의 CPU/메모리/swap
cap과 worker 보고값에 같은 값을 준다. 기본은1.5CPU/2560m다.
`OCR_PROCESSES`는1–4(기본2), `PDFIUM_WORKERS`는1–4(기본4)이며
원시 OCR pool과 PDFium 표시 쪽 prefetch의 프로세스 수를 제어한다.
S5 OCR pool은 워커 프로세스 전체가 공유하므로 동시 reader 수만큼 cap을 곱하지 않는다.
PDFium 핸들을 thread에 공유하지 않으며 Tesseract OMP는1로 유지한다.
S5 원문 검증은 v13의 동일 v12/native 검증에 scoped raw reader만 주입한다.
OCR/native verifier bytes, 정책, 원본 및 근거 인정 기준은 변경하지 않는다.
새 worker의 실행 시 `worker-runtime.json`에 요청 설정과 실제 cgroup cap을 별도로
기록한다. API 프로세스의 cap을 worker의 실제 자원으로 기록하지 않는다.

c8g.2xlarge(8vCPU/16GiB) 후보는 worker6CPU/10g, active run1, OCR2, PDFium4다.
OCR4는 같은 입력 wall10% 개선·OOM0·메모리25% 여유가 확인될 때만 채택한다.
이 값은 권장 시험 시작점이며 인스턴스 성능이나5분 완료를 입증하지 않는다.
Compose 변수 변경은 container recreate가 필요하다. 실제 env/live/서버 적용은 조정자 작업이다.

공개 필수 DTO/DB column 변경·migration 없음. 새 private 옵션/영수증은 추가 필드다.
Rollback은 새 접수를 I7 hash와8workers/4RPS, 기존 Compose1.5CPU/2560m로 전환한다.
I7로 돌아갈 때 새 RPS 키도 제거한다. 접수된 과거 작업은 현재 live의 S5 RPS를 사용하지 않는다.
이미 접수한 S5 작업은 S5 reader가 있는 worker에서 완료/재생하고 과거 결과는 보존한다.
12workers/6RPS 승격은 LG+카카오 실실행 실패/보류/미정산 증가0·403 circuit0·4290 및
태깅15% 개선과 원문/의미 보존이 확인된 뒤에만 한다. 저장 응답 replay로 승격하지 않는다.

S5의 RPS 입력은 frozen provider_execution이다. 과거 F1 정책에 남은4RPS 필드는
역사적 호환성 값이며 새 scheduler의 전송 간격을 정하지 않는다.
긴429는 입장 후 전송 대기 중인 시도도 추가 HTTP를 차단한다. 브로커 예약 전 첫
 typed 거절만 미전송0으로 정산하며, 이전 유료 시도/브로커 이후 불확실 비용은 보존한다.
