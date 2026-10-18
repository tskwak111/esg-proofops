# GA1 · 비밀번호 없는 체험 및 읽기 전용 쇼케이스

적용 기준: `feature-GA1.md`, `guest-access` / `077579df`. 분석 정책
`f29385d0c74d1520350deb06eaa9e11b72c5829dfaefeb2417c4e8ac0fed4ebd`,
분석·원문 검증 경로, 기존 관리자/대회측 비밀번호 로그인 및 RC1 복사 계약은 유지한다.
이 문서는 백엔드 계약이며 운영 배포·실제 모델 호출·12개 사례의 현장 검증을 뜻하지 않는다.

## 설정 및 운영 입력

| runtime.env 키 | 값/검증 |
| --- | --- |
| `HOSTED_GUEST_ACCESS_UNTIL` | `2026-10-20T23:59:00+09:00` (행사 종료 권장값). 시간대 있는 ISO8601. 없거나 만료되면 신규 발급과 기존 guest 인증 비활성 |
| `HOSTED_GUEST_FRESH_RUNS_PER_DAY` | `2`, 정수 1~5 |
| `HOSTED_GUEST_SESSIONS_PER_IP_HOUR` | `30`, 양의 정수. 직전 3600초의 성공 발급 수 |
| `HOSTED_GUEST_UPLOADS_PER_DAY` | `60`, 양의 정수. KST 일일 모든 guest tenant의 성공 업로드 합산 상한 |
| `HOSTED_SHOWCASE_TENANT` | 쇼케이스 원본 tenant의 정규 UUID, 빈 값이면 비활성 |

기존 `HOSTED_AUTH_TRUSTED_PROXIES`는 운영 프록시의 실제 immediate peer만 유지한다.
이 목록에 있는 peer에서만 X-Forwarded-For의 마지막 IP를 신뢰한다. 클라이언트가
직접 보낸 XFF나 앞쪽 hop은 한도를 우회하지 못한다. 프록시 구성은 이 작업에서 변경하지 않는다.
운영 Vercel→Caddy→API 프록시 뒤에서는 peer IP가 사실상 하나이므로 IP당 세션
한도가 전체 세션 한도로 동작한다. 운영값은 `HOSTED_GUEST_SESSIONS_PER_IP_HOUR=600`
(시간당 600회)이며 전역 업로드 한도와 함께 적용한다.
기존 실행/업로드 플래그·동의 버전·RC1 설정을 유지한다. 승인된 비용 상한
`HOSTED_RUN_USD=1`, `HOSTED_DAY_USD=15`, `HOSTED_EVENT_USD=30`,
`HOSTED_EVENT_USD_CEILING=30`을 올리지 않는다. 더 낮은 기존 설정은 그대로 적용된다.

## GW1 HTTP 계약

- `GET /v1/guest`: 인증 없이 200 `{available, until, fresh_runs_per_day, showcase}`.
  `until`은 설정 ISO 문자열 또는 null. `showcase`는 guest 개방 여부와 별개다.
- `POST /v1/guest/session`: 본문·기존 세션 없이 정확한 허용 Origin 필요.
  호출마다 무작위 tenant UUID/user_sub 및 새 쿠키를 발급한다. 비밀번호 로그인과 같은
  `__Host-proofops_session; Secure; HttpOnly; SameSite=Lax; Path=/`를 쓴다.
  기존 로그인과 같이 신규 발급에는 CSRF 토큰이 필요 없고, 이후 쓰기에는 Origin과
  세션의 X-CSRF-Token이 모두 필요하다. 새 발급은 이전 브라우저 쿠키를 대체한다.
- 성공 JSON은 기존 `/v1/session` 필드(`user_id, tenant_id, role, csrf_token, expires_at`)와
  `role="guest"`, `guest={until, fresh_runs_today, fresh_runs_limit}`를 포함한다.
  기존 `/v1/session`에도 같은 guest 정보를 추가한다. 절대 만료는 min(8시간, until),
  idle 만료는 기존 30분이며 절대 만료를 연장하지 않는다.
- guest 오류는 `{code:"GUEST_...", error:{code:"GUEST_..."}}`이다. 최상위 code는
  고정 계약을 충족하며 기존 웹 error.code 처리도 유지한다. 비활성은
  403 `GUEST_ACCESS_CLOSED`, IP 한도는 429 `GUEST_SESSION_RATE_LIMIT`,
  새 분석 한도는 429 `GUEST_DAILY_LIMIT`, 업로드 한도는 429 `GUEST_UPLOAD_LIMIT`.
  IP 429의 Retry-After는 가장 오래된 발급이 창에서 빠지는 남은 초다.
- guest는 자기 tenant의 업로드·scope-plan 생성/선택·실행 생성/조회/취소·삭제 요청과
  로그아웃을 사용할 수 있다. `force_fresh`, 리뷰 resolve, 관리자 권한, tenant 전환은
  403. 타 방문자 문서·실행·결과·원문·source-page 접근은 404/403.
- 하루는 Asia/Seoul 기준이다. 새 분석은 접수 시 기존 spend 장부에서 센다.
  실패·취소·삭제·재시작으로 횟수가 복원되지 않는다. RC1 재사용과 같은 idempotency
  재요청은 이 검사보다 먼저 처리된다. 재사용은 새 spend/외부 호출을 만들지 않는다.
  기존 전체/사용자 실행 수·대기열·비용 상한은 함께 적용된다.
- 전체 guest tenant 합산 하루 성공 업로드는 `HOSTED_GUEST_UPLOADS_PER_DAY`(기본 60건)까지다.
  초과 시 HTTP 429 `GUEST_UPLOAD_LIMIT`; KST 자정에 새 일자를 집계한다. 비게스트는 제외한다.
  재시도·삭제·재시작으로 집계가 복원되지 않으며 저장 transaction에서 원자적으로 재검사한다.
- guest tenant당 하루 성공 업로드 5건. 동일 idempotency 재시도는 추가 집계하지 않는다.
  기본 새 분석 2건 외 재업로드·재사용 탐색 3건을 허용하는 행사 기준이다.
  삭제 후 재업로드도 5건 한도를 복원하지 않으며 검증 전과 저장 transaction 안에서
  재검사한다. 150MiB·300쪽·PDF 검사·업로드 단일 슬롯·7일 원본 삭제는 유지한다.
  브라우저 세션별 한도이며 사람별 식별을 주장하지 않는다. 새 세션 남용은 IP/전체 예산으로 제한한다.

## 쇼케이스

`GET /v1/showcase/documents`, `GET /v1/showcase/runs`는 모든 인증 세션에서 사용한다.
기존 CollectionPage `{items, next_cursor}`와 limit(1~100, 기본 20)/cursor를 사용한다.
실행 목록은 선택적 document_id 필터도 지원한다. 비활성은 빈 CollectionPage.
설정 tenant의 보존 중인 문서와 completed 실행만 목록에 포함하고 만료/삭제 자료는 숨긴다.
커서는 caller와 쇼케이스 목록 종류에 서명되어 개인 목록이나 다른 방문자에게 재사용할 수 없다.

기존 `GET /v1/documents/{id}`, `/original`, `/scope-plan`,
`GET /v1/runs/{id}`, `/result`, `/source-pages/{page}/manifest`, `/image`의 URL을 유지한다.
해당 쇼케이스 자원에 한해서 읽기 전용 context를 사용한다. 원본·snapshot·페이지 해시,
유효 세션 및 렌더링 후 재인가를 유지한다. 결과의 result_url·원문·이미지 링크도 그대로 동작한다.
개인 `/v1/documents`, `/v1/runs` 목록에는 쇼케이스를 섞지 않는다.

쇼케이스 문서의 scope 변경·삭제·재실행, completed 실행의 취소·리뷰 수정은
원본 tenant의 관리자/대회측에게도 HTTP에서 허용하지 않는다. 원본 데이터는 변경하지 않는다.
운영자는 공개할 자료만 들어 있는 tenant를 설정해야 한다. 고정 계약에 따라 이 tenant의
모든 보존 문서가 노출되며 12개를 코드에 하드코딩하거나 새로 합성하지 않는다.

## 저장·호환·롤백

새 `guest_session_starts`, `guest_audit`와 인덱스만 additive CREATE IF NOT EXISTS로 만든다.
기존 schema/version/분석 자료는 그대로다. 세션 발급·IP 제한·업로드 및 실행 한도 검사는
기존 SQLite writer transaction으로 직렬화한다. IP는 서버 비밀키 HMAC으로만 저장하고
3600초 뒤 정리한다. guest 감사 행은 role=guest, 무작위 tenant·사용자 HMAC·자원 ID만
기록하며 PDF/쿠키/CSRF/비밀번호를 기록하지 않는다. 감사 기록은 기존 audit_days 이내,
최대 30일에 정리한다. 만료 세션의 guest membership도 정리한다. 백업은 새 두 표도 비운다.

기능 종료는 UNTIL 제거/만료, 쇼케이스 종료는 tenant 설정 제거 후 설정 재로딩이다.
이전 바이너리로 롤백할 때는 서비스 중지 상태에서 guest 세션을 revoke하고 guest membership을
제거한 뒤 guest 설정을 지운다. 이전 바이너리는 guest 기간/한도를 알지 못하므로 이 절차가
필요하다. 문서·spend·삭제 장부를 초기화하지 않으며 기존 원본 보존/비용 정산을 유지한다.

검증: `tests/test_hosted_guest.py` 및 기존 password/public/RC1/PA6/W16 회귀.
실제 provider 전송·운영 tenant 접근·push·배포는 실행하지 않는다.
