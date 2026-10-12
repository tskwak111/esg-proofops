# E05 — 전송 오류 진단과 제한된 실험

기준 `bdbe050`, X7 QUALITY-STABILITY-SPEC §3 / execution-plan X7-E05.
403의 원인을 모르는 상태에서 제품 전송·재시도·권한 가드를 바꾸지 않는다.

`FINALS_E05_POLICY`는 I9에서 파생한 **명시 pin 전용** 정책이다. 기존 default,
I9/F1/T1/C24 정책과 과거 결과 파일은 유지한다. 운영 설정 변경은 조정자 작업이다.
`configure_response_policy`가 새 정책을 검증하고 오류 sidecar에 새 진단 해시를 기록한다.
모델 wire·등급·원문 검증·K=3·예약·partial projection은 기존 계약을 따른다.

기록은 document-owned private immutable sidecar(0600)다. CF-Ray/server 및 허용 헤더,
wire SHA/길이, 요청/예약/run/tenant/source 식별, replica/role, HTTP 버전, 새 연결 ID,
UTC/monotonic, handshake 합계·TTFB·total, 최근 1초/60초 dispatch 수를 보존한다.
TTFB는 pacing 후 전송 시작 기준이며 total은 호출 내부 pacing을 포함한다.
stdlib DNS/TCP/TLS 개별 시간은 미측정 null, handshake는 합계로만 표시한다.
본문·키·cookie·예외 메시지·환경변수는 sidecar에 기록하지 않는다.

API/DB schema migration은 없다. 새 sidecar는 기존 reader가 요구하지 않는 별도 파일이다.
Rollback은 새 실행에서 기존 I9 pin을 선택하는 방식이며, 새 실행의 저장된 pin을 바꾸거나
기존 sidecar/결과를 덮어쓰지 않는다. 새 pin도 기존 F1 hold 및 PB1 표/중복 표시를 보존한다.

진단 도구 `python -m evaluation.e05_transport_matrix --root <repo> --output <private-dir>`는
로컬 TLS h1/h2 echo를 먼저 실행한다. `--live`는 별도 승인된 소규모 확인에만 사용한다.
T1/F1 공개 원문 request를 bytes/hash로 고정하며 F1의 4096 output cap도 줄이지 않는다.
7조건 ×2본문 ×2회, 최대28회, 추가 retry0, 예약 USD0.007/회·최악 USD0.196,
작업 상한 USD0.5. 실패/미확인 비용은 전액 예약을 보존한다.
새 도구는 seed105 첫 라운드와 역순 두 번째 라운드로 A/B·B/A 순서를 교차한다.
H3은 stdlib→HTTPX 교량 대조이므로 이 차이를 단일 인과 변수라고 판단하지 않는다.
H5는 실제 HTTP/2 협상 여부를 기록하고 H4는 실제 connect trace로 재사용을 확인한다.
403 연속3회·명시 접근/정책/지역 거부·401/429·회계/네트워크 불확실은 실험을 중단한다.
거부에 UA/IP/계정 변경으로 대응하지 않는다. TLS 검증·고정 HTTPS origin·redirect0을 유지한다.

HTTPX 0.28.1은 기존 dev lock을 재사용한다. HTTP/2 실험용 h2 4.4.1 / hpack 4.2.0 /
hyperframe 6.1.0은 MIT이며 `evaluation/e05-requirements.lock`에 wheel SHA를 고정했다.
`uv pip install --require-hashes -r evaluation/e05-requirements.lock`로 진단 환경에만 설치하고
`uv run --no-sync ...`로 사용한다. production dependency와 workspace uv.lock은 바꾸지 않는다.
초기 h2 4.3.0 감사에서 [중복 Host 취약점](https://github.com/python-hyper/h2/security/advisories/GHSA-6hr6-w5qg-qmwg)을 확인해 최종 tool은 4.4.1로 고정했다.

E05 최초 live 표본은 h2 4.3.0·조건별 4회 cohort 순서로 이미28회를 사용했다.
이를 최종 tool의 역순 라운드 또는 4.4.1 live 검증이라고 기록하지 않는다.
최종 버전은 로컬/Linux에서 확인하고, 추가 paid 호출은 하지 않는다.
모두200이어도 인과/production 안정성이 입증되는 것은 아니다. c8g 16workers/8RPS는
조정자 승인 전 server diagnostic not_run이며, 로컬 결함 주입 결과와 구분한다.
