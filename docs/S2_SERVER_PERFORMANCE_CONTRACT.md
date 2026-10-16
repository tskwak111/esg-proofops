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

## 2026-10-15: v18/P2 기준 S2 회귀 수정

위 I3 실험의 `S2_POLICY`와 이번 `FINALS_S2_SPEED_POLICY`는 별도 정책이다.
이번 정책은 `FINALS_P2_POLICY`의 새 opt-in이며 기본 P2와 과거 정책은 보존한다.
원문 reader v19, P2 파서·좌표 가드, 동결된 packet과 3 replica는 그대로다.

- `exact-verified-read-v11`은 native/table v19 및 evidence I17의 전체 receipt를
  원본에서 한 번 재계산하고 전체 바이트 해시가 일치한 뒤 기존 projection을 적용한다.
  중첩 wrapper가 같은 원문 검증을 다시 호출하는 부분만 생략한다. cold claim 검증,
  transient 실패의 재시도와 unknown/보류 상태는 유지한다.
- 원문 reader의 private instance 메서드만 복제하여 한 번의 검증 안에서 동일한
  policy dict를 재사용한다. 양 경계에서 전체 reader/runtime policy를 다시 대조하며
  변경 시 실패한다. 공유·frozen module의 globals나 파일은 수정하지 않는다.
  새 파싱의 native 증명 생성에도 같은 실행 경로를 적용한다.
- 기존 PA7의 성공한 raw CPU OCR만 tenant/run/source/crop/padding/runtime 범위에서
  재사용한다. 2개 spawn process와 OMP 1, 8MiB/256개 상한을 유지한다.
  원문·glyph·귀속·수치 검사는 매번 실행하고 실패 OCR은 캐시에 넣지 않는다.
- whole receipt cache는 8개/32MiB로 제한한다. 메모리에 검증한 결과만 보관하며
  파일에서 cache를 불러오지 않는다. 원문·graph·전체 receipt·policy·tenant·runtime
  중 하나라도 바뀌면 새 검증을 수행한다.
- 새 table adapter와 policy snapshot 구현은 별도 SHA로 고정한다. 기존
  `parse_table_cache.py`의 byte pin과 I4/S1 과거 reader를 그대로 보존한다.
- 새 pin은 기존 anonymous-FD 게시 경로에도 등록한다. workspace 파일·권한·run·
  fence·페이지·reader/runtime 검사는 그대로이며 불일치하면 cold replay로 복귀한다.
- 마지막 continuation이 source 증명을 포함한 revision을 commit하고 pending이
  비었으면 추가 no-op batch를 실행하지 않는다. 태깅과 게시는 기존 원문 검증을
  계속 수행한다. 중간 revision, 실패·보류, lease·취소·예산 처리는 그대로다.

API/DB migration과 새 dependency는 없다. Rollback은 새 pin의 접수를 중단하고
기존 P2로 새 실행을 배정하며, 새 pin과 기존 실행의 reader·산출물은 보존한다.

## I21 통합: v20 의미 정책 + S2 실행 (2026-10-15)

기본 `finals-20261015-v21`은 `FINALS_I20_POLICY`에서 integration 이름과
verified-read 실행 정책만 변경한다. claim reader v21, native/table reader v20,
atomic-v3, W5/E06, grade-relevant unanimity, 제한된 C3 및 일반 C4/C5/C6 비활성은
그대로다. `FINALS_I20_POLICY`, 최초 로컬 v20, v19와 S2 opt-in hash는 별도로
등록하여 이전 실행의 의미를 바꾸지 않는다.

`exact-verified-read-v12`는 S2의 v11 실행을 등록된 v20/v21에 합성한다.
`i21_reader_execution.py`는 v21의 내부 v20/complete instance에만 동일한 policy
snapshot·성공 raw OCR cache·2개 CPU process를 적용한다. v4 prose admission을
건너뛰지 않는다. `i21_table_replay.py`는 v20의 전체 native/table receipt를
재계산하고 전체 해시가 일치한 뒤 projection을 적용한다. 두 새 adapter의 bytes를
실행 정책에 별도 SHA로 고정하며 기존 S2 adapter와 모든 source reader bytes를
보존한다. 원문·테넌트·run·graph·refs·전체 receipt·reader/runtime 경계와 transient
실패의 재검사는 유지한다. 마지막 committed batch의 빈 pending 이후 추가
no-op batch를 중단하고, v12의 private publication handoff도 기존 FD 경계를 따른다.

기존 저장 원문의 reader/dependency pin이 현재 runtime과 다르면 그대로 거절한다.
성능 측정을 위해 과거 receipt의 hash를 새 코드 hash로 덮어쓰지 않는다. 고정
원문·graph에 현재 정책의 새 receipt를 생성한 전후 계측과 과거 저장 응답 재생은
구별해서 보고한다. API/DB migration 및 새 dependency는 없다.
