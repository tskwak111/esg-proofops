# P1 self-review and requirement mapping

Baseline12ed952 → r108-public. Reviewed directly using shared differential-review and
spec-to-code-compliance instructions; this is not independent-agent verification.
Taskdeploy-P1 plus coordinatorDEC-19 (eventUSD5, Lightsail4GB) and user-approved original7d
are authoritative. A-08 Linux hosting overrides DESIGN's earlier Mac hosting recommendation.
Frozen reader/source policy modules, classification/domain logic, existing research ledger
and submission checkout were not edited. No upstream claim/review/export compatibility
is inferred from a health check or a blank PDF smoke.

| Requirement / source | Verdict | Enforcement and observed evidence |
|---|---|---|
| Explicit hosted, no local bypass / task§1, DESIGN§6 | implemented | main.create_app selects create_hosted_app, settings require hosted/disabled; staging/production local refusal unchanged; no/local routes in hosted OpenAPI; tests/test_hosted_public.py main/settings guards. |
| Invite/session persistence/tenant isolation / DESIGN§6 | implemented | hashed single-use SQLite invite and SID, stable HMAC CSRF, strong membership read,8h/30min expiry, rotate/revoke; HTTP cookie attributes, tenant404, restart session+CSRF passed in Docker. |
| Origin+CSRF/CORS / DESIGN§6 | implemented | exact HTTPS origin at startup, exact CORS/credentials/methods/headers, writes require CSRF, login exact Origin; hostile origin and missing CSRF rejected. No wildcard preview domains. |
| Upload limits/selected2pages / DESIGN§6 | implemented | receive byte cap including chunked body; cross-process upload slot1 prevents parallel body/validator OOM; existing SEC-002 quarantine subprocess, max300pages/50MiB; page selection uniqueness/bounds and source/prepared hashes; selected preparation subprocess bounded512MiB/20CPU-seconds/30s. |
| Original retention7d / approved user update | implemented | runtime Korean notice, consent version persisted;60s periodic API maintenance + worker/startup/CLI maintain; expiry test actually unlinks original; default7d, configurable only downward. |
| Purge/fence/no backup resurrection / DESIGN§5 | implemented for hosted stores | independent tombstone committed before payload unlink; complete document directory and document/run/idempotency rows removed; all remaining money records contain no source payload; purge failure remains blocked and retryable; old job publication rejected; restore checks matching ledger and tombstones. |
| Backup raw exclusion/max14d / DESIGN§5 | implemented for hosted stores | online SQLite backup has no raw source BLOB; excludes sessions/invites/memberships; only receipt/graph/export dirs copied, not original/prepared; earliest document creation+14d lifetime; document backup payload removed on early purge; test scans PDFs and retained quote. Existing research caches are never mounted/imported. |
| Audit30d / DESIGN§5 | implemented with accounting exception | settled per-run costs and deletion IDs expire; subject-free event aggregate preserves cap. Unknown costs cannot be dropped at TTL to free allowance; operator reconciliation remains required. Normal writers cannot delete immutable tombstones; TTL delete uses a narrowly scoped connection predicate after completed purge. |
| Atomic global/run/day/event budget / DESIGN§6, DEC-19 | implemented broker; live wiring blocked | single SQLite transaction reserves run envelope and nested calls once; micro-USD; KST day;0.50/5/5 ceilings; queue races cap correctly; receipt mismatch/timeout keep accounting_pending; late result after deletion settles money without payload; independent ledger survives state restore. |
| Queue active1/queued8/user1 / A-08 | implemented | immediate FIFO claim/fence, user2/day/global10/day,429Retry-After; concurrent12 submissions admit8, concurrent3 claims admit1; expired lease never redispatched, unknown money blocks new acceptance. |
| Hosted R108 pipeline/review/export / DESIGN§4,§7 | partial | offline hosted worker prepares selection and publishes partial_blocked/LIVE_BINDING_UNAVAILABLE. Full existing RunService/claim/review/export worker chain is not wired into isolated hosted stores. Linux OCR approval/quality evaluation and full pipeline broker/artifact migration are required before live launch. |
| Legacy/static rollback / DESIGN§7 | implemented safety boundary | backend flags exposed, static default, uploads/runs default closed, LIVE_DISABLED mandatory; legacy paid path refused because broker adapter is unwired; no automatic paid fallback. |
| Docker Linux4GB / task§3, coordinator | implemented locally | linux/arm64 frozen-lock image, non-root/read-only/network-none/3GiB limit, actual Uvicorn auth/upload202/poll/worker/purge/restart; image/startup/RSS/cgroup values in runtime-results.json. Live parser/JVM/OCR peak and amd64 not_run. |
| Vercel config diff only / task§4 | implemented | FRONTEND-DIFF.md grounded in submission vercel.json/App.tsx/session/api.ts/UploadForm/LiveReport. No frontend migration, push or cloud mutation. Existing web typecheck/build passed. |

Important attack/failure paths reviewed: foreign tenant UUID →404 before data access;
forged Origin/CSRF →403; body-length spoof/chunk overflow →413; invitation race →single
redemption; user/queue/cap races →transactional admission; cancel/delete during worker
→fence recheck before file publication; unknown provider response →reservation retained;
late response after deletion →cost-only settlement; restored old metadata →external ledger
and tombstone rejection; audit expiry →event total retained. Backup and restore are
operator-only and require the independently retained ledger; destroying all copies of
that ledger is not supported recovery. Source-free restored documents require reupload.

A fresh worktree exposed two baseline atomic-wiring unit tests depending on a developer's
real research budget file even though transports are mocked. Their fixture now redirects
composition.__file__ to tmp_path and provides a temporary empty presence-only fake ledger;
all original profile assertions remain, and production ledger guards are unchanged.
Full failure evidence remains in pytest-full.log; final suite in pytest-full-final.log.

Final resource-admission guard was added after the full-suite collection. It has a
failing-before regression, final focused/related tests and a rebuilt network-none
Docker smoke. The full suite validates the rest of the implementation at e4d71a0;
no unchanged broad check was repeated for this isolated hosted-only admission change.

## P2 self-review (deploy-P2; baseline 58ce7f3)
Applied shared differential-review and spec-to-code-compliance directly; no independent
agent or plugin fan-out was run. Scope: hosted API/store, provider factory seam,
private pipeline entry point, result/review adapters, Docker packaging and canary.

| Task requirement | Enforcement/evidence | Verdict |
|---|---|---|
| Existing R108 profiles and broker before every provider request/retry | hosted_r108.prepare_argv; HostedParseProbe/HostedLunaProbe transport overrides; fake real parse/extract/tag chain; separate retry reservations | Implemented on Mac; Linux explicitly unresolved |
| Money .50/run,5/day,5/event; default off/operator+paths | HostedSettings ceilings, create_run global envelopes, dispatch immediate reservation; operator config and key-only worker reads; broker-limit/unknown restart/cancel tests | Implemented |
| Claims/track/elements/source pages/holds/ranges/grades and human review | hosted_results uses unchanged LocalClaimStore/LocalTagStore/ReviewService; tenant+run gate, CSRF, reviewer role, CAS/idempotency; source replay retained | Implemented; partial results retain unknown |
| Submission state/result/deletion contract | normalized 0..1 progress, FIFO position, stage/result URL+inline DTO; uploader hash/admin deletion; CONTRACT/OpenAPI updated | Backend aligned; frontend claim rendering remains a separate UI task |
| Fake chain, excess/cancel/restart and key-free Docker | tests/test_hosted_analysis.py + existing hosted tests; rebuilt nonroot/network-none real HTTP smoke | Verified locally |
| One two-page paid Mac check <=.30 through hosted API, existing R108 ledger | hosted_live_probe.py loopback Uvicorn, existing shared decision lock and .30 pre-reservation; p2-live/live-result.json | See final P2 report/result |

Adversarial paths checked: unauthenticated/write-CSRF, foreign tenant result/review,
nonowner same-tenant deletion, editor human-confirmation denial, immutable source
replay and null-grade preservation, broker excess before HTTP, both schema retries,
late cancelled charge settlement, deleted-run publication fence, active source lock,
restart retaining unknown envelopes. Physical working files live under the document;
backup allowlist excludes the entire analysis tree; successful purge clears receipt
memory caches. No raw key/response/quote is added to hosted control/money rows.
No domain rule, frozen verifier, evidence admission, unknown/absent semantics or
legacy transport was weakened. Source/result reads and human resolution use the
hosted writer lock so tombstone+purge cannot race a public result/review operation.
Residual limits: Linux profile is uncommitted upstream development and not adopted;
no Linux paid chain/4GB live sizing, public same-site TLS/browser/Vercel canary,
provider-retention certification, cloud operation or push in this task.

Final P2 verification: stable full suite5455 passed/68 skipped (686.49s); focused integration69 passed/1 skipped; Ruff/format/mypy passed.
Initial broad run had one CONFIG_GATE_BLOCKED in the local approval test; isolated, adjacent and stable full reruns passed without weakening any guard.
Mac canary: original upload201/run202/result200,109 provider calls, USD0.046962 against .30 pre-reserved in the existing R108 ledger;21 claims/8 reviews,15 verified+6 unverified, all grades null; original/analysis payload purge completed.
