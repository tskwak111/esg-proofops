# TASK-019/001 local review web evidence

Date: 2026-09-09 KST

Scope: local-only React/API integration on IPv6 loopback ports 4201/4202. The browser fixture uses generated PDFs and the explicit local synthetic extractor/tagger; it makes no model or AWS calls and contains no customer document.

## Red reproduction

Before the router change, opening `/runs/<run-id>/reviews` rendered `새 문서 등록`. The focused browser check then timed out waiting for the claim quote, confirming that the declared run/claim/review routes were absent.

## Browser verification

Own Orca page: `70971d42-c28a-4f85-87a5-443b649e0569`.

- `tests/e2e/claim_workspace_check.mjs`: passed with `route`, URL `filters`, fixed `source_projection`, source-ticket renewal, `csrf_if_match`, preserved `draft_412`, and aborted/ignored `foreign_session` response all `true`. Its source text includes `<img src=x onerror=alert(1)>`; no injected image node was created.
- Actual generated verified-synthetic fixture: `/runs/<run>/reviews` loaded the real claims and review queue, showed P1-P6 as `unknown`, and displayed the explicit `로컬 합성 자료 검증 — 실제 모델 결과가 아닙니다.` marker.
- Actual review race: a competing resolve returned 200/review revision 2; the already-open editor sent `X-CSRF-Token`, quoted `If-Match: "1"`, and received 412. The UI retained `412 이후에도 보존할 로컬 초안`, loaded `서버 revision 2 · resolved`, and disabled overwrite. Escape closed the native confirmation dialog without losing the draft.
- Actual CSRF negative: source-view POST without the token returned `403 CSRF_INVALID`.
- Actual source projection: source-view POST returned a five-minute ticket, `preview=page` returned a PNG with natural width 1200, and the original PDF link retained `#page=1`. The source was `candidate`, so the UI rendered the page and accessible text but correctly rendered no bbox overlay.
- Actual tenant switch to the second fixture membership navigated to `/documents/new`; old run text and the review draft were absent. The focused check separately held an old claims response until after switching and confirmed its AbortSignal was aborted and its foreign marker was ignored.
- Actual run progress after the full parse/extract/tag checkpoints retained `문서 파싱: 완료`, `주장 추출: 완료`, and `근거 태깅: 완료`, then truthfully showed `사람 검토: 검토 대기`. The real run summary API response mounted beside progress, and no raw response field appeared in the page.

## Commands and results

```text
pnpm --dir apps/web run build
PASS: tsc --noEmit; Vite production build (46 modules)

uv run ruff check tests/e2e/local_browser_server.py
PASS

uv run ruff format --check tests/e2e/local_browser_server.py
PASS

uv run pytest -q tests/integration/test_local_tag_runner.py tests/integration/test_claim_api.py tests/integration/test_source_api.py tests/acceptance/test_reviews.py
PASS: 53 passed, 2 dependency deprecation warnings

uv run pytest -q tests/acceptance/test_parsing.py::test_actual_opendataloader_text_and_tables_keep_physical_pages_and_artifacts
PASS: 1 passed; actual parser artifact remains `fast_preview` with vision `not_run`

orca eval --page 70971d42-c28a-4f85-87a5-443b649e0569 --expression "import focused check"
PASS: {"csrf_if_match":true,"draft_412":true,"filters":true,"foreign_session_cleared":true,"route":true,"source_projection":true,"source_renew_once":true}

orca eval --page 70971d42-c28a-4f85-87a5-443b649e0569 --expression "import run progress check"
PASS: {"retry_poll_resumed":true,"stale_action_ignored":true}
```

## Not run

- Live model calls: `not_run`
- AWS/cloud changes: `not_run`
- Customer PDFs: `not_run`
- Accuracy/production-complete claims: not made
