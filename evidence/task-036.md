# TASK-036 verification evidence

Date: 2026-09-09 KST  
Fixture: `AT-036`, explicitly local synthetic data from `tests/e2e/local_browser_server.py`; no product model, AWS mutation, or customer PDF.

## TDD

- Red: `uv run pytest tests/acceptance/test_accessibility.py -q`
  - Exit 1: `1 passed, 2 failed`; the component bundle could not resolve the absent `SourceViewer`/`StatusBadge`, and focus restoration plus summary invalidation hooks were absent.
- Green: `uv run pytest tests/acceptance/test_accessibility.py -q`
  - Exit 0: `3 passed in 0.40s`.

## Browser acceptance

Harness command:

`uv run python tests/e2e/local_browser_server.py --host ::1 --port 4201 --origin 'http://[::1]:4201' --database /tmp/proofops-task036.IFgOoW/state.sqlite --dist apps/web/dist`

Orca browser page: `0bf462b5-8cd8-4bc6-a233-75380ac1ac7a`.

- The review screen accessibility snapshot exposed native buttons, links, checkboxes, selects, textarea, fieldsets, headings, and dialog labels.
- Keyboard `Space` on `원문 위치 열기` moved focus to the accessible source heading (`H3`, `1쪽`).
- Keyboard character selection changed P1 from `unknown` to `present`, then `absent`; keyboard input set the reason to `키보드 접근성 확인`.
- Keyboard `Space` on `변경 확인` opened the native modal and placed focus on `취소`; `Escape` closed it, restored focus to `변경 확인`, and preserved the P1 `absent` plus reason draft.
- On the claim detail route, keyboard `Space` loaded the real authenticated same-origin page preview. Page evaluation returned `{"preview":true,"highlight":false,"accessibleText":true,"newTab":true}`; the candidate/unverified location was not falsely highlighted, and the accessible text plus original-PDF new-tab link remained present.
- Visible status text (`연결 상태: 위치 후보`, `판정 대기`) accompanied the badge symbol/color, so meaning does not depend on color.

The harness was stopped and its Orca browser page was closed after verification.

## Focused verification

- `pnpm --dir apps/web run build`
  - Exit 0: TypeScript no-emit check and Vite production build passed; 49 modules transformed.
- `uv run pytest tests/acceptance/test_reviews.py tests/acceptance/test_dashboard.py -q`
  - Exit 0: `38 passed, 2 warnings in 2.08s` (existing Starlette/httpx deprecations).
- `uv run pytest tests/acceptance/test_claims.py tests/acceptance/test_auth.py -q`
  - Exit 0: `45 passed, 2 warnings in 1.79s` (existing Starlette/httpx deprecations).
- `uv run python scripts/validate_package.py`
  - Exit 0: `705` documentation/contract checks passed; this is recorded only as contract validation, not application validation.
- `git diff --check`
  - Exit 0, no whitespace errors.

Coordinator verification: report/accessibility acceptance passed 22 tests and the
TypeScript/Vite build passed. The existing browser run-progress regression first
failed because its exact status string did not account for the new visible badge
symbol; inspecting the rendered text confirmed the new run remained queued.
It now checks the actual status region, retains the late-response rejection, uses
the fixed Coverage DTO, and asserts summary refresh notification on retry plus
no notification from the aborted old tenant action. Running
`tests/e2e/run_progress_check.mjs` in Orca page
`f8dae1fb-54ad-4c9b-817c-2ada8aa36e4a` returned
`{"retry_poll_resumed":true,"stale_action_ignored":true,"summary_refresh":true}`.
The coordinator-owned local Vite server was then stopped.

## Not run

- Real model/AWS/customer-document tests: prohibited and unnecessary for this local synthetic acceptance slice.
- Human data, rights, legal, and deployment approval gates: `not_run`; no claim of production readiness.
