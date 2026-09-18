# TASK-041 · 브라우저 세션 보호 실행 증거

- 요구사항/수용 기준: SEC-005 / AT-041
- 작업일: 2026-09-09 (Asia/Seoul)
- 구현 범위: `verify_csrf`, `rotate_session`, `logout`, `POST /v1/auth/logout`, CSP
- 공유 파일 조정: Orca 메시지 `msg_f494484d4090`으로
  `apps/api/src/proofops_api/main.py` 및 `auth.py`의 TASK-041 독점 변경 승인을 받았다.

## 구현 결과

- CSRF 토큰 SHA-256 해시를 `secrets.compare_digest`로 비교하고, 배포
  `APP_ORIGIN`과 요청 `Origin`의 exact match를 함께 요구한다.
- 로그아웃은 쿠키 세션의 live/revoked/absolute/idle 상태를 CSRF보다 먼저
  확인하고, 성공 시 서버 레코드를 즉시 revoke한 뒤 Secure/HttpOnly/
  SameSite=Lax/Path=/ 속성으로 `__Host-proofops_session` 쿠키를 만료한다.
- 기존 로컬 hash-only 세션 저장소의 원자 rotation을 `rotate_session`이
  그대로 사용한다. TASK-037의 2-way racing rotation 및 old SID rejection
  회귀 테스트도 함께 통과했다.
- 모든 HTTP 응답에 self 중심 CSP를 적용했다. PDF blob은 `frame-src`에서만
  허용하고 object/script의 임의 외부 로드는 차단한다.
- 실제 HTTP 흐름 `GET /v1/session` CSRF 발급 → `POST /v1/auth/logout` →
  204/cookie 제거/server revoke → old cookie 401을 검증했다. 응답은 redirect나
  query URL을 만들지 않고, web source에는 `localStorage`/`sessionStorage` 사용이
  없으며 SID cookie는 HttpOnly다.

## Red → Green

1. 실패 테스트 작성 후 실행

   ```text
   uv run pytest tests/acceptance/test_session_security.py -q
   8 failed, 2 warnings in 0.25s
   ```

   실패 원인: `/v1/auth/logout` 미구현(404), `middleware.py`/`session.py` 부재,
   CSP 헤더 부재.

2. 최소 구현 후 최종 대상 테스트

   ```text
   uv run pytest tests/acceptance/test_session_security.py -q
   10 passed, 2 warnings in 0.24s
   ```

## 최종 검증 명령과 결과

```text
uv run ruff check apps/api/src/proofops_api/middleware.py apps/api/src/proofops_api/session.py apps/api/src/proofops_api/auth.py apps/api/src/proofops_api/main.py tests/acceptance/test_session_security.py
All checks passed!

uv run ruff format --check apps/api/src/proofops_api/middleware.py apps/api/src/proofops_api/session.py apps/api/src/proofops_api/auth.py apps/api/src/proofops_api/main.py tests/acceptance/test_session_security.py
5 files already formatted

uv run mypy apps/api/src/proofops_api/middleware.py apps/api/src/proofops_api/session.py apps/api/src/proofops_api/auth.py apps/api/src/proofops_api/main.py
Success: no issues found in 4 source files

uv run pytest tests/acceptance/test_auth.py tests/acceptance/test_session_security.py -q
37 passed, 2 warnings in 0.29s

uv run pytest tests/contracts/test_package_contracts.py -q
29 passed, 2 warnings in 0.48s

uv build --package proofops-api
Successfully built dist/proofops_api-0.0.0.tar.gz
Successfully built dist/proofops_api-0.0.0-py3-none-any.whl

git diff --check -- apps/api/src/proofops_api/middleware.py apps/api/src/proofops_api/session.py apps/api/src/proofops_api/auth.py apps/api/src/proofops_api/main.py tests/acceptance/test_session_security.py
exit 0
```

두 pytest 경고는 설치된 FastAPI TestClient의 Starlette/httpx 전환 deprecation
경고이며 테스트 실패나 TASK-041 동작 오류는 아니다.

## 실행하지 않은 게이트

### Coordinator acceptance

The worker result still used the incoming Host when APP_ORIGIN was absent.
Two real HTTP regressions reproduced unauthorized-origin logout and tenant
selection; a third reproduced missing credentialed CORS preflight handling.
The shared CSRF helper now fails closed without configured origin, and logout
reuses it. Starlette CORSMiddleware permits the single configured origin and
credentials with explicit methods/headers. Existing auth fixtures now supply
their trusted test origin. The combined auth/session/contract command passes
**69 tests** (27 + 13 + 29); focused Ruff/mypy exit 0. No cloud behavior is implied.

- 실제 Cognito/OIDC, DynamoDB/KMS 세션 저장소, AWS 변경: `not_run` — 계정·승인
  범위 밖이며 local synthetic/in-memory composition만 사용했다.
- 실제 브라우저 E2E 및 private customer data: `not_run` — 이번 수용 테스트는
  FastAPI TestClient 실제 HTTP 경계와 정적 web storage 금지 검사를 사용했다.
- 데이터 권리·법률·인간 승인: `blocked/not_run` — 독립 코드 구현과 무관한
  human-only gate로 유지했다.
- 전체 WIP 저장소 suite: `not_run` — 다른 작업자의 병렬 변경을 포함하므로
  TASK-041 및 직접 연계 auth/contract 회귀만 실행했다.
