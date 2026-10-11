# S2 서버 실행 정책

S2는 `584c280`의 I3 도메인·추출 wire·v11 원문 검증을 유지하는 명시적
`analysis_policy_sha256` opt-in이다. 기본 I3 및 조정자의 I4 정책을 바꾸지 않는다.

- HTTP 기본 동시성 16, 운영자의 명시적 1..16 설정 우선. 기존 공동 provider gate,
  429 admission 감소·Retry-After·불확실 호출 무재시도·비용 예약을 유지한다.
- CPU OCR은 별도 spawn 프로세스 2개, 각 OMP thread 1개다. PDFium handle은
  프로세스 간 공유하지 않는다. 원문 판정 코드와 frozen reader 파일은 변경하지 않는다.
- `exact-verified-read-v6`만 v11을 포함한다. 원문·테넌트·run·graph·정렬된 refs·
  전체 receipt·원문 reader policy/코드 SHA·runtime·환경이 같을 때만 fresh receipt를
  재사용한다. 기존 v1..v5 및 과거 analysis hash는 그대로 읽힌다.
- raw OCR 재사용은 같은 원문·crop·padding·테넌트·run·reader/runtime 범위에서만
  성공한 완전한 읽기를 보관한다. 8MiB/256개 process-local bound를 유지한다.
  미판독을 승인으로 바꾸지 않으며 failed 셀·recovered selection의 원래 처리를 유지한다.
- 별도 결과 게시 프로세스의 cold v11 replay도 보관된 page OCR 응답을 검증하고,
  원래 전체 receipt를 재계산한 뒤 byte hash를 대조한다. CPU raw 읽기만 병렬화한다.
  저장 source/receipt를 신뢰하는 것으로 이 검사를 대체하지 않는다.
- 새 실행의 불변 tagger ceiling은 2,000회다. 실제 발견한 주장 수에 27회
  (예비·관계·요소 각 3 replica × 최대 3 형식 시도)를 곱한 값과 ceiling 중 작은
  값을 별도로 적용한다. 계획은 tag checkpoint에 보존한다. 복구 작업도 기존 불변
  원장 상한을 넘지 않는다. 모든 유료 dispatch는 기존 USD 예약을 통과해야 한다.
- 작은 주장 집합에는 작은 allowance를 적용한다. 큰 집합·긴 응답은 2,000회 또는
  USD1보다 많은 비용을 요구할 수 있으므로 전수 완료를 보장하지 않는다. 예산 실패는
  BUDGET_EXHAUSTED로 공개하며 unknown/conflict/unreadable을 absent로 바꾸지 않는다.
- 원문 verified 주장 중 숫자·명시적 목표/감축/최상급 문구를 먼저 dispatch한다.
  이는 실행 순서이며 트랙·등급 기준이 아니다. 최종 record는 원래 source order를 따른다.

공개 API·DB column migration과 dependency 추가는 없다. 기존 opaque checkpoint와
불변 run budget을 사용하며 과거 snapshot/receipt/revision은 수정하지 않는다.
Rollback은 새 S2 pin의 접수를 중단하고 기존 S2 실행 reader를 유지한다. S2를 모르는
reader에 해당 실행을 배정하지 않는다. I4 통합 시 위 실행·budget 항목을 I4의 도메인
정책에 합성해 새 hash를 만들어야 하며, S2 hash를 I4 의미로 소급 해석하지 않는다.

실험의 USD0.60 공유 원장은 생산 실행의 USD1 한도와 별도다. 서버는 읽기 전용으로
조회했고 push·배포·EC2/runtime.env 변경은 하지 않는다. 실제 측정·제한은 요청된
`outputs/agent-results/R108-redesign/lab/perf/S2/S2-REPORT.md`와 원자료에 기록한다.
