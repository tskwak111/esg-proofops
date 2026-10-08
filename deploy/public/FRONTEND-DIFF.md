# Vercel submission frontend changes — documentation only

Inspected `/Users/ss020/Dev/ESG_ProofOps/.local/esg-proofops-submission` on2026-10-09.
No files in that checkout were changed. P1 is a locally verified hosted control plane,
not the complete R108 analysis/review/export backend. A base-URL change alone is insufficient.

| Current source/config | Required change before integration |
|---|---|
| `vercel.json` buildCommand hardcodes `VITE_DEMO_STATIC=true` | Keep static rollback build. Add a distinct hosted control-plane build with `VITE_API_BASE_URL=https://api.<owned-domain>`, `VITE_DEMO_STATIC=false`, `VITE_LOCAL_SYNTHETIC=false`. Vite values require rebuild; server flags are runtime controls. |
| `App.tsx:16–18` API base/local upload switches | Use exactly the TLS API origin. Web+API must share the same owned site, e.g. `app.example.com` / `api.example.com`; arbitrary Vercel preview domains cannot use the Lax cookie. Fixed preview must have separate backend/DB/secrets. |
| `features/session/api.ts:25` already uses `credentials: include` | Reuse this for all hosted fetches. New invite form POST `/v1/auth/invitation` JSON `{code}` (Origin supplied by browser); GET `/v1/session` returns existing user/tenant/role/CSRF/ISO expiry shape. Store session only in HttpOnly cookie, CSRF in memory; never access code/provider key in localStorage. |
| `App.tsx:71` calls `/local/submission` | Remove that bootstrap from hosted branch; call `/v1/runtime` for mode/limits/notice/readiness. Hosted never mounts `/local/*`. Do not call the existing full claim/summary/review/export pages while these endpoints are unwired. |
| `features/upload/UploadForm.tsx` currently creates company/document/version/ticket then multipart | Hosted upload is one bounded `application/pdf` POST `/v1/documents`, `credentials:include`, `X-CSRF-Token`, UUID `Idempotency-Key`; send entire original max50MiB/300pages. Receive `document_id`, source SHA, size/page_count/expiry. No browser PDF rewrite/chunking; no filename required. Handle413/422/503 and upload429/UPLOAD_BUSY+Retry-After1 (one validator at a time on4GB). |
| `features/live/LiveReport.tsx:78–106` browser slices/chunks10pages, POST `/api/live-report`, `X-Demo-Access-Code` | In hosted mode replace this flow with invite/session+original upload then POST `/v1/runs` `{document_id,selected_pages?:number[]}`; at most2 unique1-based original pages, default first2. API prepares the selected copy and binds both hashes. Legacy result DTO is a separate `legacy-lite-v1` path, never presented as R108 receipts. |
| RunForm/RunProgress expect current R108 DTOs | New explicit `r108-hosted-control-v1` DTO from `openapi.json`:202 gives `run_id`, `selected_pages`, `status_url`, status/profile/error/prepared SHA. Poll GET every2–5s; reconnect by run ID, and pause/reduce polling on hidden tabs. GET must never dispatch models. `partial_blocked/LIVE_BINDING_UNAVAILABLE` displays blocked analysis, not success or empty evidence. |
| Queue/errors/cancellation | Show active1/queued8/user1 limits, waiting state,429+Retry-After,503/accounting_pending, source expiry/reupload. POST `/v1/runs/{run_id}/cancel` with session+CSRF. Never automatically retry paid legacy/R108 on a failed attempt. |
| Upload consent/notice | Replace “non-retention” text with **“업로드한 원본 PDF는 이 서버에서 7일 동안 보관한 뒤 자동 삭제합니다. 관리자는 보관 기간이 끝나기 전에 삭제를 요청할 수 있습니다.”** Show selected2-page external transmission and actual provider/live-disabled state. Record `HOSTED_CONSENT_VERSION` with upload. Backup≤14d/audit≤30d remain configurable proposal values pending their confirmation. |
| Deletion UI | Admin POST `/v1/documents/{document_id}/deletion-requests` `{reason}` with CSRF+Idempotency-Key. Distinguish completed/failed; remove document/run views on tombstone404; a failed purge remains inaccessible and retryable. |
| DTO/client/schema | Generate/extend a dedicated client from `deploy/public/openapi.json`, keep full R108 DTOs separate. This control-plane API does not produce claims/grades/review/export. Complete approved OCR/R108-worker integration before enabling those UI paths. |
| `vercel.json` two55s Python functions | They are not used by hosted202/poll flow. Keep static rollback, disable legacy paid functions unless they use the same global broker. The current legacy `_limits.py` is not that broker. No cloud/config change in P1. |
| CSP/release record | Frontend `connect-src` must explicitly allow exact TLS API; API CSP does not configure Vercel CSP. Record frontend deployment ID, API image/commit, consent version, origin and server flags. Rollback: accept-new-runs off → static build; preserve ledger/tombstones and queued/unknown costs. |

Local web typecheck/build verifies the untouched current web, not a hosted UI migration.
Browser same-site/TLS canary and real AWS operation await domains/credentials and are not_run.

## P2 contract alignment for hosted-r108-web(8ae22b7)
The backend now supplies stage, queue_position, numeric progress0..1, inline result
and result_url; `completed` always requires a real fenced R108 publication. Partial
results remain partial_blocked and include hold reasons. Uploader deletion now works
with the existing reason/Idempotency client; remove its stale admin-only comment.
Use the P2 CONTRACT result DTO for claim cards and review forms: source quality,
original_page_num/page_map, unchanged source refs, elements, missing-evidence states,
possible_grade_range and nullable confirmed_grade. The current RunOutcomeView has
no claim/result renderer; add that in the submission UI task before a browser launch.
Reviewer/admin POST /v1/runs/{id}/reviews/{review}/resolve uses If-Match, CSRF and
Idempotency-Key and returns the existing human-confirmed decision. The selected-PDF
source refs must remain unchanged when submitted; original page labels are display
mapping only. Use /v1/runtime delete_policy/review_role/source_verifier/live_analysis
and preserve unknown/unverified/partial semantics. Source integrity failure409 is
not an empty successful result. Existing same-site/TLS/proxy checks remain not_run.
