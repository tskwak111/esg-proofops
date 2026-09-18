# TASK-001/045 web integration evidence

Date: 2026-09-09 (Asia/Seoul)

## Implemented scope

- Replaced the TASK-000 health placeholder with the same-origin session, tenant, permission, company, approved-profile, and PDF registration flow.
- `GET /v1/session` and all API JSON requests use `credentials: include`; absent and expired sessions, unavailable OIDC, no active tenant, insufficient role, empty registries, and server errors have explicit Korean UI states.
- Company loading follows every cursor page and aborts on tenant changes. Company creation has an in-flight guard, preserves its idempotency key for an unchanged retry, and discards stale tenant responses.
- Upload readiness requires a company plus approved rights, consent, and runtime selections. Missing consent or runtime disables the submit control and the submit handler independently refuses writes; an absent active rule pack is reported as a later analysis-execution blocker.
- The browser computes SHA-256 with WebCrypto, posts the document and version ticket with stable per-step idempotency keys, sends the real multipart form to an allow-listed target, completes the upload, and polls the returned same-origin version URL. Tenant changes abort work and clear all selections, file metadata, results, and retry state.
- Upload targets are limited to the exact local `/local/uploads/{uuid}/content` path on the API origin or an exact HTTPS `VITE_UPLOAD_ORIGIN`; arbitrary ticket URLs and unsafe status URLs are rejected before fetch.
- No dependency, component library, authentication bypass, cloud identity, or product scope was added to normal application code.

## Browser fixture checks

Fixture command:

```sh
npm --prefix apps/web run build
PORT=4187 node apps/web/test/browser-fixture.mjs
```

Checks were performed in Aside Chromium against the built UI. This fixture validates UI states and request sequencing; it is not presented as the composed-backend check below.

- Pre-change RED: the browser showed only the TASK-000 health baseline and no session, company, or upload form.
- Editor: two company pages were requested with cursors `null` and `page-2`; approved rights, consent, and runtime controls were keyboard-accessible.
- Missing consent: the consent control and PDF submit button were disabled, the actionable consent message was visible, and `GET /__fixture/state` returned `idempotency: []` (zero document/upload writes).
- Missing runtime: the runtime control and PDF submit button were disabled, the actionable runtime message was visible, and `GET /__fixture/state` returned `idempotency: []` (zero document/upload writes).
- Happy path: the 431-byte one-page PDF completed to ready version `88888888-8888-4888-8888-888888888888`; document, version-ticket, and complete requests each carried an idempotency key.
- Retry: an injected first document `503` produced a retry action. The two document attempts used the identical key `d172c075-5283-4b69-8b6d-36219478a96b`, after which ticket, multipart, complete, and ready polling succeeded.
- Unsafe transport: a ticket containing `https://unapproved.invalid/upload` was rejected in the UI as an unapproved upload address before multipart transport or completion.
- Missing session, OIDC-unavailable `503`, viewer role, and no-selected-tenant states were also inspected; only the configured same-origin `/auth/login?return_to=%2Fdocuments%2Fnew` pathway is linked.

Artifacts:

- `apps/web/test/browser-fixture.mjs`
- `evidence/task-001-web-fixture.pdf`

## Actual composed local API browser check

The test-only harness mounts the built UI on the real `proofops_api.main.create_app()` application, uses the composed SQLite Registry and UploadService plus AuthStore, and seeds only explicit synthetic fixtures from the acceptance-test approval helper. Its `/__e2e/login` route creates a generated Secure, HttpOnly, same-site session cookie; this route exists only in `tests/e2e/local_browser_server.py` and does not claim live Cognito/OIDC.

Commands:

```sh
harness_dir=$(mktemp -d)
uv run python tests/e2e/local_browser_server.py --port 4190 --database "$harness_dir/state.sqlite3"
shasum -a 256 evidence/task-001-web-fixture.pdf
curl -fsS http://127.0.0.1:4190/__e2e/state/2eb238ed-03c4-4163-8303-0a9bd427d3e2
```

Aside Chromium navigated to `http://127.0.0.1:4190/__e2e/login`, received the test session, loaded the real session/company/runtime-option endpoints, and submitted the native PDF form through the real multipart and complete routes. The UI reported ready version `2eb238ed-03c4-4163-8303-0a9bd427d3e2` with one page.

The stored-state result was:

```json
{
  "version_id": "2eb238ed-03c4-4163-8303-0a9bd427d3e2",
  "stored_sha256": "8cfddae2ffd8d38dbfcede1423d130f3e549bf5fb415183b46f2e0023fe2f2c4",
  "stored_size_bytes": 431,
  "snapshot_sha256": "8cfddae2ffd8d38dbfcede1423d130f3e549bf5fb415183b46f2e0023fe2f2c4",
  "page_count": 1,
  "document_revision": 2,
  "local_synthetic": true
}
```

The source `shasum` was the same `8cfddae2ffd8d38dbfcede1423d130f3e549bf5fb415183b46f2e0023fe2f2c4`.

## Verification

```sh
npm --prefix apps/web run typecheck
# passed: tsc --noEmit

npm --prefix apps/web run build
# passed: 31 modules transformed; dist built

node --check apps/web/test/browser-fixture.mjs
# passed

uv run python -m py_compile tests/e2e/local_browser_server.py
# passed

uv run ruff check tests/e2e/local_browser_server.py
# passed

uv run pytest tests/acceptance/test_upload.py tests/acceptance/test_registry.py -q
# 27 passed, 2 dependency deprecation warnings
```

Real Cognito, AWS/S3, external signed-upload origin, cloud deployment, and model calls were not run. The check used the approved local-synthetic composition only.

## Coordinator acceptance follow-up

- Root added unmount cancellation and `redirect: error` on multipart transport so a signed/local upload cannot follow a redirect to an unapproved origin.
- `pnpm --dir apps/web build`: exit 0, TypeScript plus Vite 31 modules.
- A fresh harness on 127.0.0.1:4190 and fresh SQLite state repeated the actual browser flow through the product submit handler. Native date values were entered with DOM input/change events because Orca's date fill reported success without changing the value; an explicit DOM button click triggered the form after Orca's reference click had no effect. These automation limitations did not change product code or replace backend requests.
- Ready version `04b73042-0a30-4bfb-adca-fa53698431df`: actual stored SHA-256 `8cfddae2ffd8d38dbfcede1423d130f3e549bf5fb415183b46f2e0023fe2f2c4` equals source and snapshot, 431 bytes, one page, document revision 2, local_synthetic=true. Verified through `curl -fsS http://127.0.0.1:4190/__e2e/state/04b73042-0a30-4bfb-adca-fa53698431df` and `shasum -a 256 evidence/task-001-web-fixture.pdf`.
- Computed browser styles retain the 760px content width and 44px button minimum under the composed CSP.

- Vite proxy verification: `API_PUBLIC_BASE_URL=http://127.0.0.1:4190 pnpm --dir apps/web exec vite --host 127.0.0.1 --port 4191 --strictPort` followed by `curl -fsS http://127.0.0.1:4191/v1/health/live` returned the actual composed API baseline health. Default port 8000 belonged to an unrelated application and was not changed.
