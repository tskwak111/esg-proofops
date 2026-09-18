# Separate Upstage tagger authorization — 2026-09-18

Developer A / TASK-029 + real-tagging continuation, following preliminary
classification work. Changes are approval checks and transport enforcement;
no domain, Developer B, API/DB, tokenizer, runtime activation or dependency change.
Contract/migration/rollback: docs/local-upstage-tagging-contract.md final section.

The existing extractor gate retains its public signature and semantics (including
legacy Pro3/no-hash shape). A private helper shares tenant/time/provider/endpoint/
budget/consent validation with an explicitly different expected role. The new
public tagger gate additionally requires concrete source/rights membership and
complete frozen settings SHA256. It never rewrites a tagger binding into an
extractor binding to pass a check.

The transport now requires trusted `authorize(settings, request)->Preflight` composition.
Checks run before each count and paid invocation; expiry after counting still
blocks invocation. The callback must resolve the actual request packet hash to its trusted source/rights,
then resolve trusted grants and fresh time, and
is not itself user/model-supplied input. Authorization receipts are diagnostic
proof of which check ran; callers must separately retain complete approval artifacts.
They do not establish source quality, calibrated semantic correctness or token
accounting. Source/claim/consensus/Python-rule validation remains downstream.

Red-green checks reproduced absent gate, revoked approval not preventing a fake
HTTP dispatch, missing authorization receipt, and accidental extractor-preflight
reuse. All were repaired without issuing a real model request. Additional cases
cover altered model/prompt/schema/cap/profile/epoch, foreign tenant, expired grants,
missing/disallowed source, wrong rights, and invalid settings even when their
hash is re-signed. Legacy extractor and tagging integration regressions are run.

Orca run run_b8a6fc47aedd: Muse Spark1.3 Free contract review
(task_1014b5cae043) completed and terminal closed. The coordinator retained shared
provider/endpoint/budget checks but isolated role/hash/source requirements, addressing
the review's compatibility concern. Muse Spark1.2 Free code review
(task_7ef9ceb4c63f) completed; the terminal was closed. Its partial-preflight
counterexample was reproduced and fixed by requiring all eight approval checks.
The request is now passed to the callback so trusted composition can bind packet
hash to the authorized source; a no-dispatch test verifies that rejection path.
This is a required composition responsibility, not a claim that the real worker
mapping exists yet. The constructor change is intentional and documented.
A cached/stale callback remains invalid composition (fresh time required); a
Python callback is trusted application code, not a security token from a client.
The suggested settings-hash drift from additive receipt metadata was not accepted:
authorization is outside TaggingSettings/request signature/wire content, whose
existing hashing and transport regression tests continue to pass.

Paid model/AWS tests: not_run. New browser E2E: not_run (no UI/API change).
No new monetary reservations or calls; cumulative ledger remains the preceding
USD7.9372558150 committed/reserved of USD20, with six old unsettled reservations.
The full service still requires dual run bindings, provider token accounting and
preliminary/relationship supplier wiring. This is not production readiness.

## Verification

Focused command:
`uv run pytest tests/integration/test_upstage_tagging.py tests/integration/test_upstage_tagger_preflight.py tests/integration/test_upstage_runtime.py -q`
returned **87 passed**, two existing framework deprecation warnings, 2.71s.

Final post-review focused run: **89 passed**, two warnings, 3.01s.
Final full run:
`uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`
returned **2283 passed, 7 skipped, 2 warnings**, 188.24s. Skips are the unavailable
ignored legacy-reference snapshot; warnings are existing Starlette/httpx and anyio
deprecations. Log `/tmp/proofops-tagger-suite-final.txt`.

- Ruff check + format: pass, 307 files formatted.
- Mypy (packages, API, worker, agent, evaluation, load, staging gate): pass,175 files.
- Architecture checker and documentation/package validator: pass (821 doc/contract checks).
- All four Python packages built; web typecheck/build pass.
- Source/license/secret supply-chain gate: pass; dependency locks unchanged and
  dependency vulnerability network audits not repeated for this increment.
- Shared ledger read-only check:1380 rows,6 unsettled,USD7.9372558150; no increase.
- Both Orca review workers settled; terminals closed and no reclaimable workers.

The callback's `(settings, request)` signature is the final contract. The transport
requires all eight approval checks (not only the two tagger-specific checks).
Caller-side source resolution is demonstrated by a rejecting composition test;
this is not a claim that a production source-mapping implementation was wired.
